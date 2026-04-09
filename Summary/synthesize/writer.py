"""
阶段二：基于聚合后的要点列表，逐节调用 LLM 撰写正文段落；
        超字数节触发压缩；可选的全文引言生成。
"""

import json
import time
import logging
from pathlib import Path

from openai import OpenAI

from synthesize.config import (
    SECTIONS,
    DEEPSEEK_MODEL,
    TEMPERATURE_WRITE,
    MAX_RETRIES,
    COMPRESS_TOLERANCE,
    CONFIG_MAPPING_FILE,
    INTRO_WORD_RANGE,
    CONCLUSION_WORD_RANGE,
    WRITE_MAX_BULLETS_PER_SECTION,
    WRITE_MAX_BULLET_CHARS,
    WRITE_MAX_BULLETS_PER_SUBSECTION,
)
from synthesize.prompts import (
    WRITE_SYSTEM, WRITE_USER,
    WRITE_SYSTEM_SUBSECTION, WRITE_USER_SUBSECTION,
    build_subsection_write_prompt,
    COMPRESS_SYSTEM, COMPRESS_USER,
    INTRO_SYSTEM, INTRO_USER,
    CONCLUSION_SYSTEM, CONCLUSION_USER,
)

logger = logging.getLogger(__name__)

_MAPPING_JSON_CACHE: dict | None = None


def _load_mapping_json() -> dict:
    """加载 config_mapping.json（与 extractor 子章节 key 一致）。"""
    global _MAPPING_JSON_CACHE
    if _MAPPING_JSON_CACHE is None:
        root = Path(__file__).resolve().parent.parent
        path = root / CONFIG_MAPPING_FILE
        _MAPPING_JSON_CACHE = json.loads(path.read_text(encoding="utf-8"))
    return _MAPPING_JSON_CACHE


def _subsection_defs_for_section(section: dict) -> list[dict]:
    """
    子章节定义优先来自 config.SECTIONS 内嵌；否则从 config_mapping.json 读取。
    config.py 通常只设 has_subsections 而不重复写入 subsections 列表，避免此处为空导致整章无正文。
    """
    inline = section.get("subsections")
    if inline:
        return list(inline)
    sk = section.get("key", "")
    st = section.get("title", "")
    for msec in _load_mapping_json().get("sections", []):
        mk = msec.get("section_key", "")
        mt = msec.get("section_title", "")
        if mk == sk or mk == st or mt == sk or mt == st:
            return list(msec.get("subsections", []))
    return []


def _other_sections_text(current_section: dict, all_sections: list[dict]) -> str:
    """生成"其余各节负责"的简短列表，用于撰写 Prompt 防止跨节溢出。"""
    lines = []
    for s in all_sections:
        if s["id"] == current_section["id"]:
            continue
        lines.append(f"  第{s['id']}节「{s['key']}」：{s['description'][:30]}…")
    return "\n".join(lines)


def _count_chars(text: str) -> int:
    """统计中文字符数（去除空白和换行）。"""
    return len(text.replace("\n", "").replace(" ", ""))


def _dedupe_bullets(bullets: list[str]) -> list[str]:
    seen = set()
    out = []
    for b in bullets:
        key = b.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _trim_bullets_for_prompt(
    bullets: list[str],
    max_items: int,
    max_chars: int,
) -> list[str]:
    deduped = _dedupe_bullets(bullets)
    limited = deduped[:max_items]
    out: list[str] = []
    used = 0
    for b in limited:
        cur = _count_chars(b)
        if used + cur > max_chars and out:
            break
        if cur > max_chars and not out:
            out.append(b[:max_chars])
            break
        out.append(b)
        used += cur
    return out


def write_section(
    client: OpenAI,
    section: dict,
    bullets_or_subsections: object,
    all_sections: list[dict],
) -> str:
    """
    为单个章节撰写正文段落。

    Args:
        client              : OpenAI 客户端
        section             : config.SECTIONS 中的一个元素
        bullets_or_subsections: 普通章节时为 list[str]；带子章节时为 dict[str, list[str]]
        all_sections        : 全部章节列表（用于生成其他章节摘要，防溢出）

    Returns:
        str: 该章节的正文段落（不含标题）
    """
    if section.get("has_subsections", False):
        return write_section_with_subsections(
            client,
            section,
            bullets_or_subsections,
            all_sections,
        )

    bullets = bullets_or_subsections if isinstance(bullets_or_subsections, list) else []
    if not bullets:
        logger.warning(f"  [撰写] 第{section['id']}节「{section['key']}」无要点，生成占位文本")
        return "（本节暂无内容，请人工补充）"

    trimmed_bullets = _trim_bullets_for_prompt(
        bullets,
        max_items=WRITE_MAX_BULLETS_PER_SECTION,
        max_chars=WRITE_MAX_BULLET_CHARS,
    )
    if len(trimmed_bullets) < len(bullets):
        logger.info(
            f"  [token优化] 第{section['id']}节 bullets {len(bullets)}→{len(trimmed_bullets)}（提示裁剪）"
        )
    bullet_text = "\n".join(f"- {b}" for b in trimmed_bullets)
    min_w, max_w = section["word_range"]
    other_text = _other_sections_text(section, all_sections)

    prompt = WRITE_USER.substitute(
        section_title=section["title"],
        section_id=section["id"],
        bullets=bullet_text,
        other_sections=other_text,
        min_words=min_w,
        max_words=max_w,
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"  [撰写] 第{section['id']}节  尝试 {attempt}/{MAX_RETRIES}")
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                temperature=TEMPERATURE_WRITE,
                messages=[
                    {"role": "system", "content": WRITE_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
            )
            content = response.choices[0].message.content.strip()
            if content:
                return content
            raise ValueError("LLM 返回空内容")

        except Exception as e:
            logger.warning(f"  [撰写] 第{section['id']}节异常（第{attempt}次）: {e}")
            if attempt == MAX_RETRIES:
                return f"（第{section['id']}节生成失败，请人工补充）"
            time.sleep(2 ** attempt)


def write_section_with_subsections(
    client: OpenAI,
    section: dict,
    subsections: dict[str, list[str]],
    all_sections: list[dict],
) -> str:
    """
    为带子章节的章节逐小节撰写正文，并拼接成一个完整章节。
    """
    if not subsections:
        logger.warning(f"  [撰写] 第{section['id']}节「{section['key']}」无子章节要点，生成占位文本")
        return "（本节暂无内容，请人工补充）"

    outputs: list[str] = []
    min_w, max_w = section["word_range"]
    subsection_defs = _subsection_defs_for_section(section)
    if not subsection_defs and subsections:
        # 映射文件缺失时，按聚合结果中的 key 顺序兜底
        subsection_defs = [
            {"key": k, "title": k, "index": i + 1}
            for i, k in enumerate(sorted(subsections.keys()))
        ]
        logger.warning(
            f"  [撰写] 第{section['id']}节「{section['key']}」未在 config_mapping 中找到子章节定义，"
            f"按 aggregated 的 {len(subsection_defs)} 个 key 顺序撰写"
        )
    n_slots = max(len(subsection_defs), 1)
    average_words = int((min_w + max_w) / 2 / n_slots)

    for subsection in subsection_defs:
        key = subsection["key"]
        bullets = subsections.get(key, [])
        logger.info(f"  [撰写] 第{section['id']}节「{section['key']}」子节 {subsection['title']} ({len(bullets)} 条要点)")
        if not bullets:
            continue
        trimmed_sub_bullets = _trim_bullets_for_prompt(
            bullets,
            max_items=WRITE_MAX_BULLETS_PER_SUBSECTION,
            max_chars=WRITE_MAX_BULLET_CHARS,
        )
        if len(trimmed_sub_bullets) < len(bullets):
            logger.info(
                f"  [token优化] 第{section['id']}节子节 {subsection['title']} bullets "
                f"{len(bullets)}→{len(trimmed_sub_bullets)}（提示裁剪）"
            )
        prompt = build_subsection_write_prompt(
            section=section,
            subsection=subsection,
            bullets=trimmed_sub_bullets,
            target_words=average_words,
        )
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=DEEPSEEK_MODEL,
                    temperature=TEMPERATURE_WRITE,
                    messages=[
                        {"role": "system", "content": WRITE_SYSTEM_SUBSECTION},
                        {"role": "user",   "content": prompt},
                    ],
                )
                content = response.choices[0].message.content.strip()
                if content:
                    outputs.append(content)
                    break
                raise ValueError("LLM 返回空内容")
            except Exception as e:
                logger.warning(f"  [撰写] 第{section['id']}节子节{key}异常（第{attempt}次）: {e}")
                if attempt == MAX_RETRIES:
                    outputs.append(f"（子节{key}生成失败，请人工补充）")
                time.sleep(2 ** attempt)

    if not outputs:
        logger.warning(f"  [撰写] 第{section['id']}节「{section['key']}」所有子节均无有效输出")
        return "（本节暂无内容，请人工补充）"

    return "\n\n".join(outputs)


def compress_section(client: OpenAI, section: dict, content: str) -> str:
    """
    将超出字数上限的章节压缩至 max_words 以内。
    """
    max_w = section["word_range"][1]
    actual_w = _count_chars(content)

    prompt = COMPRESS_USER.substitute(
        section_title=section["title"],
        actual_words=actual_w,
        max_words=max_w,
        content=content,
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                temperature=0.3,   # 压缩用低温，减少改动
                messages=[
                    {"role": "system", "content": COMPRESS_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
            )
            compressed = response.choices[0].message.content.strip()
            if compressed:
                new_len = _count_chars(compressed)
                logger.info(f"         压缩后: {actual_w}→{new_len} 字")
                return compressed
            raise ValueError("LLM 返回空内容")

        except Exception as e:
            logger.warning(f"  [压缩] 第{section['id']}节异常（第{attempt}次）: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"  [压缩] 失败，保留原文")
                return content
            time.sleep(2 ** attempt)


def write_intro(client: OpenAI, sections: list[dict]) -> str:
    """生成全文开篇引言段落（可选调用）。"""
    titles_text = "\n".join(f"{s['id']}. {s['title']}" for s in sections)
    prompt = INTRO_USER.substitute(
        section_titles=titles_text,
        min_words=INTRO_WORD_RANGE[0],
        max_words=INTRO_WORD_RANGE[1],
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                temperature=TEMPERATURE_WRITE,
                messages=[
                    {"role": "system", "content": INTRO_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
            )
            content = response.choices[0].message.content.strip()
            if content:
                return content
            raise ValueError("LLM 返回空内容")
        except Exception as e:
            logger.warning(f"  [引言] 第{attempt}次异常: {e}")
            if attempt == MAX_RETRIES:
                return ""
            time.sleep(2 ** attempt)


def write_conclusion(client: OpenAI, sections: list[dict]) -> str:
    """生成全文结语段落（可选调用）。"""
    titles_text = "\n".join(f"{s['id']}. {s['title']}" for s in sections)
    prompt = CONCLUSION_USER.substitute(
        section_titles=titles_text,
        min_words=CONCLUSION_WORD_RANGE[0],
        max_words=CONCLUSION_WORD_RANGE[1],
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                temperature=TEMPERATURE_WRITE,
                messages=[
                    {"role": "system", "content": CONCLUSION_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
            )
            content = response.choices[0].message.content.strip()
            if content:
                return content
            raise ValueError("LLM 返回空内容")
        except Exception as e:
            logger.warning(f"  [结语] 第{attempt}次异常: {e}")
            if attempt == MAX_RETRIES:
                return ""
            time.sleep(2 ** attempt)
