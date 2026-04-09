"""
阶段二：基于聚合后的要点列表，逐节调用 LLM 撰写正文段落；
        超字数节触发压缩；可选的全文引言生成。
"""

import time
import logging
from openai import OpenAI

from synthesize.config import (
    SECTIONS, DEEPSEEK_MODEL, TEMPERATURE_WRITE, MAX_RETRIES, COMPRESS_TOLERANCE
)
from synthesize.prompts import (
    WRITE_SYSTEM, WRITE_USER,
    COMPRESS_SYSTEM, COMPRESS_USER,
    INTRO_SYSTEM, INTRO_USER,
)

logger = logging.getLogger(__name__)


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


def write_section(
    client: OpenAI,
    section: dict,
    bullets: list[str],
    all_sections: list[dict],
) -> str:
    """
    为单个章节撰写正文段落。

    Args:
        client      : OpenAI 客户端
        section     : config.SECTIONS 中的一个元素
        bullets     : 该章节聚合后的所有工作要点（list[str]）
        all_sections: 全部9节列表（用于生成其他节摘要，防溢出）

    Returns:
        str: 该章节的正文段落（不含标题）
    """
    if not bullets:
        logger.warning(f"  [撰写] 第{section['id']}节「{section['key']}」无要点，生成占位文本")
        return "（本节暂无内容，请人工补充）"

    bullet_text = "\n".join(f"- {b}" for b in bullets)
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
    prompt = INTRO_USER.substitute(section_titles=titles_text)

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
