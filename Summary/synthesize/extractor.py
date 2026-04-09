"""
阶段一：从单份部门规划材料中提取结构化材料要点。

主要职责：
  - 调用 LLM，输出 JSON（5个key，每个key对应 list[str]）
  - 自动重试（JSON解析失败或API异常）
  - 返回标准化结果，缺失的key补空列表
"""

import json
import re
import time
import logging
from pathlib import Path
from openai import OpenAI

from synthesize.config import (
    SECTIONS,
    DEEPSEEK_MODEL,
    TEMPERATURE_EXTRACT,
    MAX_RETRIES,
    ENABLE_SUBSECTION_LABEL_BACKFILL,
)
from synthesize.prompts import (
    EXTRACT_SYSTEM,
    EXTRACT_SYSTEM_SUBSECTION,
    EXTRACT_USER,
    build_subsection_extract_prompt,
)

logger = logging.getLogger(__name__)

# 所有合法的 section key
VALID_KEYS = {s["key"] for s in SECTIONS}
ROOT = Path(__file__).resolve().parent.parent
DEBUG_DIR = ROOT / "output" / "intermediate" / "debug_subsection_raw"


def extract_from_summary(client: OpenAI, summary_text: str, source_name: str = "") -> dict:
    """
    从一份部门规划中，按5个维度提取工作要点。

    Args:
        client      : 已初始化的 OpenAI 客户端（指向 DeepSeek）
        summary_text: 部门规划的纯文本内容
        source_name : 来源文件名，仅用于日志

    Returns:
        dict: {section_key: [bullet_str, ...], ...}，保证包含全部5个key
    """
    prompt = EXTRACT_USER.substitute(summary=summary_text)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"  [提取] {source_name}  尝试 {attempt}/{MAX_RETRIES}")
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                temperature=TEMPERATURE_EXTRACT,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
            )
            raw = response.choices[0].message.content
            data = _safe_load_json_with_repair(
                client=client,
                raw=raw,
                source_name=source_name,
                stage="main",
                expected_keys=sorted(VALID_KEYS),
            )
            normalized = _normalize(data, source_name)

            # 可选：为有子章节的大章节补充“子章节标签化”展示。
            # 注意：该步骤会额外触发一次子章节提取调用，默认关闭以节省 token。
            if ENABLE_SUBSECTION_LABEL_BACKFILL:
                try:
                    subsection_result = extract_subsections_from_summary(
                        client, summary_text, source_name=source_name
                    )
                    normalized = _inject_subsection_labels(normalized, subsection_result)
                except Exception as e:
                    logger.warning(f"  [提取] {source_name} 子章节标签化失败，保留原提取结果: {e}")

            return normalized

        except json.JSONDecodeError as e:
            logger.warning(f"  [提取] JSON解析失败（{source_name}，第{attempt}次）: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"  [提取] {source_name} 全部重试失败，返回空结果")
                return _empty_result()
            time.sleep(2 ** attempt)

        except Exception as e:
            logger.warning(f"  [提取] API异常（{source_name}，第{attempt}次）: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"  [提取] {source_name} 全部重试失败，返回空结果")
                return _empty_result()
            time.sleep(2 ** attempt)


def _normalize(raw: dict, source_name: str) -> dict:
    """
    标准化 LLM 返回的 JSON：
      - 保证所有5个key都存在
      - 每个value都是 list[str]
      - 过滤掉非法key
    """
    result = _empty_result()
    for key, value in raw.items():
        if key in VALID_KEYS:
            if isinstance(value, list):
                result[key] = [str(v).strip() for v in value if v]
            else:
                logger.warning(f"  [normalize] {source_name}: key={key} value不是列表，已忽略")
        else:
            logger.debug(f"  [normalize] {source_name}: 未知key '{key}'，已忽略")
    return result


def _empty_result() -> dict:
    return {s["key"]: [] for s in SECTIONS}


def _inject_subsection_labels(base_result: dict, subsection_result: dict) -> dict:
    """
    将子章节提取结果写回主提取结果，形如：
      "发展基础": ["【subsection_xxx｜持续深化理论武装...】xxx", ...]
      "建设任务": ["【subsection_xxx｜构建人才培养新体系】xxx", ...]
    仅覆盖 has_subsections=True 的大章节。
    """
    mapping = _load_config_mapping()
    section_subtitle_map = {
        section["section_key"]: {
            sub["key"]: sub.get("title", sub["key"])
            for sub in section.get("subsections", [])
        }
        for section in mapping.get("sections", [])
    }
    # 兼容中英文 section key：如 "发展基础" <-> "development_foundation"
    mapping_section_aliases = _build_mapping_section_aliases(mapping)

    for section in SECTIONS:
        if not section.get("has_subsections", False):
            continue
        section_key = section["key"]
        sub_map = {}
        for alias in mapping_section_aliases.get(section_key, [section_key]):
            if alias in subsection_result and isinstance(subsection_result.get(alias), dict):
                sub_map = subsection_result.get(alias, {})
                break
        if not isinstance(sub_map, dict) or not sub_map:
            continue

        # 子章节 title_map 优先按实际命中的 alias 取，找不到则再按中文 key 兜底
        title_map = {}
        for alias in mapping_section_aliases.get(section_key, [section_key]):
            if alias in section_subtitle_map:
                title_map = section_subtitle_map.get(alias, {})
                break
        if not title_map:
            title_map = section_subtitle_map.get(section_key, {})
        labeled_bullets: list[str] = []
        for sub_key, bullets in sub_map.items():
            if not isinstance(bullets, list):
                continue
            sub_title = title_map.get(sub_key, sub_key)
            for bullet in bullets:
                text = str(bullet).strip()
                if text:
                    # 同时展示子章节 key 和标题，便于在 extracted.json 排查映射链路
                    labeled_bullets.append(f"【{sub_key}｜{sub_title}】{text}")

        if labeled_bullets:
            base_result[section_key] = labeled_bullets

    return base_result


def _build_mapping_section_aliases(mapping: dict) -> dict[str, list[str]]:
    """
    建立 config.SECTIONS 中文 key 到 mapping section_key/title 的别名映射。
    """
    aliases: dict[str, list[str]] = {s["key"]: [s["key"], s["title"]] for s in SECTIONS}
    normalized_to_config_key = {
        _normalize_subsection_identifier(s["key"]): s["key"] for s in SECTIONS
    }
    normalized_to_config_key.update(
        {_normalize_subsection_identifier(s["title"]): s["key"] for s in SECTIONS}
    )

    for msec in mapping.get("sections", []):
        sec_key = str(msec.get("section_key", "")).strip()
        sec_title = str(msec.get("section_title", "")).strip()
        config_key = normalized_to_config_key.get(_normalize_subsection_identifier(sec_title))
        if not config_key:
            continue
        for candidate in [sec_key, sec_title]:
            if candidate and candidate not in aliases[config_key]:
                aliases[config_key].append(candidate)
    return aliases


def extract_subsections_from_summary(
    client: OpenAI,
    summary_text: str,
    source_name: str = "",
) -> dict:
    """
    从一份单部门规划中提取有子章节的大章节要点。

    返回：{section_key: {subsection_key: [bullet, ...], ...}}
    """
    mapping = _load_config_mapping()
    result = {}
    enabled_section_ids = {
        _normalize_subsection_identifier(s.get("key", ""))
        for s in SECTIONS
        if s.get("has_subsections", False)
    }
    enabled_section_ids.update(
        {
            _normalize_subsection_identifier(s.get("title", ""))
            for s in SECTIONS
            if s.get("has_subsections", False)
        }
    )

    for section in mapping.get("sections", []):
        if not section.get("subsections"):
            continue
        section_key = section["section_key"]
        section_title = str(section.get("section_title", ""))
        sec_key_norm = _normalize_subsection_identifier(section_key)
        sec_title_norm = _normalize_subsection_identifier(section_title)
        if sec_key_norm not in enabled_section_ids and sec_title_norm not in enabled_section_ids:
            logger.debug(
                f"  [子章节提取] {source_name} - 跳过未启用子章节章节: {section_key}/{section_title}"
            )
            continue
        logger.info(f"  [子章节提取] {source_name} - {section_key}")
        section_data = _extract_subsection_section(client, summary_text, source_name, section_key)
        result[section_key] = section_data
    return result


def _extract_subsection_section(
    client: OpenAI,
    summary_text: str,
    source_name: str,
    section_key: str,
) -> dict:
    prompt = build_subsection_extract_prompt(section_key, summary_text)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"  [子章节提取] {source_name} {section_key} 尝试 {attempt}/{MAX_RETRIES}")
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                temperature=TEMPERATURE_EXTRACT,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": EXTRACT_SYSTEM_SUBSECTION},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content
            _dump_debug_raw(
                stage="subsection_raw",
                source_name=source_name,
                raw=raw,
                section_key=section_key,
            )
            expected_subkeys = _get_expected_subsection_keys(section_key)
            data = _safe_load_json_with_repair(
                client=client,
                raw=raw,
                source_name=source_name,
                stage=f"subsection:{section_key}",
                expected_keys=expected_subkeys,
            )
            return _normalize_subsections(data, source_name)

        except json.JSONDecodeError as e:
            logger.warning(f"  [子章节提取] JSON解析失败（{source_name}，{section_key}，第{attempt}次）: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"  [子章节提取] {source_name} {section_key} 全部重试失败，返回空结果")
                return {}
            time.sleep(2 ** attempt)

        except Exception as e:
            logger.warning(f"  [子章节提取] API异常（{source_name}，{section_key}，第{attempt}次）: {e}")
            if attempt == MAX_RETRIES:
                logger.error(f"  [子章节提取] {source_name} {section_key} 全部重试失败，返回空结果")
                return {}
            time.sleep(2 ** attempt)


def _normalize_subsections(raw: dict, source_name: str) -> dict:
    result = {}
    mapping = _load_config_mapping()
    key_to_title = {}
    title_to_key = {}
    for section in mapping.get("sections", []):
        for subsection in section.get("subsections", []):
            sub_key = subsection["key"]
            title = str(subsection.get("title", "")).strip()
            key_to_title[sub_key] = title
            title_to_key[_normalize_subsection_identifier(title)] = sub_key
    valid_keys = set(key_to_title.keys())

    for key, value in raw.items():
        normalized_key = key if key in valid_keys else title_to_key.get(
            _normalize_subsection_identifier(str(key))
        )
        if normalized_key in valid_keys:
            if isinstance(value, list):
                result[normalized_key] = [str(v).strip() for v in value if v]
            else:
                logger.warning(
                    f"  [normalize_subsections] {source_name}: key={key} value不是列表，已忽略"
                )
        else:
            logger.debug(f"  [normalize_subsections] {source_name}: 未知子章节 key '{key}'，已忽略")
    return result


def _normalize_subsection_identifier(text: str) -> str:
    """
    归一化子章节标识，兼容模型返回“标题而非key”的情况。
    """
    s = str(text).strip().lower()
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"^[（(]?[一二三四五六七八九十0-9]+[)）、.．\-:：]*", "", s)
    s = s.replace("“", "").replace("”", "").replace("\"", "").replace("'", "")
    s = s.replace("【", "").replace("】", "").replace("[", "").replace("]", "")
    return s


def _safe_load_json_with_repair(
    client: OpenAI,
    raw: str | None,
    source_name: str,
    stage: str,
    expected_keys: list[str],
) -> dict:
    """
    先尝试直接解析 JSON，失败后走一次“JSON 修复”兜底。
    """
    cleaned = _strip_json_fences(raw)
    try:
        return json.loads(cleaned)
    except Exception as e:
        logger.warning(f"  [JSON修复] {source_name} {stage} 首次解析失败: {e}")
        repaired_text = _repair_json_via_llm(client, cleaned, expected_keys)
        repaired_cleaned = _strip_json_fences(repaired_text)
        try:
            repaired = json.loads(repaired_cleaned)
            _dump_debug_raw(
                stage="json_repair_success",
                source_name=source_name,
                raw=repaired_cleaned,
                section_key=stage,
            )
            return repaired
        except Exception as e2:
            _dump_debug_raw(
                stage="json_repair_failed",
                source_name=source_name,
                raw=f"ORIGINAL:\n{cleaned}\n\nREPAIRED:\n{repaired_text}",
                section_key=stage,
            )
            raise json.JSONDecodeError(
                f"JSON修复后仍解析失败: {e2}",
                repaired_cleaned if isinstance(repaired_cleaned, str) else "",
                0,
            )


def _repair_json_via_llm(client: OpenAI, broken_text: str, expected_keys: list[str]) -> str:
    """
    让模型把“非严格 JSON / 半截 JSON”修复成严格 JSON。
    """
    key_hint = ", ".join(expected_keys) if expected_keys else "保持原有 key"
    repair_prompt = (
        "你是 JSON 修复器。请将下面文本修复为严格 JSON 对象。\n"
        f"要求：\n1) 仅输出 JSON 对象本体\n2) key 仅使用这些候选：{key_hint}\n"
        "3) value 必须是数组（无内容时返回 []）\n4) 不得输出解释文字或代码块。\n\n"
        f"待修复文本：\n{broken_text}"
    )
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": "你是严谨的 JSON 修复助手。"},
            {"role": "user", "content": repair_prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def _strip_json_fences(text: str | None) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _get_expected_subsection_keys(section_key: str) -> list[str]:
    mapping = _load_config_mapping()
    for section in mapping.get("sections", []):
        if section.get("section_key") == section_key:
            return [sub.get("key", "") for sub in section.get("subsections", []) if sub.get("key")]
    return []


def _dump_debug_raw(stage: str, source_name: str, raw: str | None, section_key: str = "") -> None:
    """
    记录原始/修复后的响应，便于排查。
    """
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        safe_source = re.sub(r"[^\w\-.]+", "_", source_name)[:80] or "unknown"
        safe_section = re.sub(r"[^\w\-.:]+", "_", section_key)[:80]
        fname = f"{safe_source}__{stage}"
        if safe_section:
            fname += f"__{safe_section}"
        out = DEBUG_DIR / f"{fname}.txt"
        out.write_text((raw or "").strip(), encoding="utf-8")
    except Exception as e:
        logger.debug(f"  [debug] 写入调试文件失败: {e}")


def _load_config_mapping() -> dict:
    config_path = Path(__file__).resolve().parent / "config_mapping.json"
    return json.loads(config_path.read_text(encoding="utf-8"))
