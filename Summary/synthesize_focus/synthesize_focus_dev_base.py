#!/usr/bin/env python3
"""
聚焦版脚本：仅执行第一大章节“发展基础”的提取与聚合。

目标：
1) 仅调用“发展基础”相关提取，减少调参迭代成本
2) 单独缓存，避免污染主流程 output/intermediate 结果
3) 输出结构化聚合 JSON + 可读 Markdown 预览
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from synthesize.config import DEEPSEEK_BASE_URL
from synthesize.extractor import (
    extract_from_summary,
    extract_subsections_from_summary,
)
from synthesize_focus.config_focus import (
    INPUT_DIR,
    DEPT_SUMMARY_FILE,
    OUTPUT_DIR,
    INTERMEDIATE_DIR,
    EXTRACT_CACHE_FILE,
    SUBSECTION_EXTRACT_CACHE_FILE,
    AGGREGATED_FILE,
    PREVIEW_MD_FILE,
    FOCUS_SECTION_KEY,
    FOCUS_SECTION_TITLE,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_individual_summaries() -> dict[str, str]:
    files: dict[str, str] = {}
    for p in sorted(INPUT_DIR.glob("*.md")):
        if p.name == DEPT_SUMMARY_FILE:
            continue
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        body = "\n".join(lines[2:] if lines and lines[0].startswith("#") else lines)
        files[p.name] = body.strip()
    return files


def run_focus_extraction(client: OpenAI, summaries: dict[str, str]) -> dict[str, list[str]]:
    cache: dict[str, list[str]] = {}
    if EXTRACT_CACHE_FILE.exists():
        cache = json.loads(EXTRACT_CACHE_FILE.read_text(encoding="utf-8"))
        logger.info("读取聚焦提取缓存：%d 份", len(cache))

    for fname, text in summaries.items():
        if fname in cache:
            logger.info("[跳过提取] %s（已有缓存）", fname)
            continue
        logger.info("[提取] %s", fname)
        result = extract_from_summary(client, text, source_name=fname)
        cache[fname] = result.get(FOCUS_SECTION_KEY, [])
        EXTRACT_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cache


def run_focus_subsection_extraction(
    client: OpenAI,
    summaries: dict[str, str],
) -> dict[str, dict[str, list[str]]]:
    cache: dict[str, dict[str, list[str]]] = {}
    if SUBSECTION_EXTRACT_CACHE_FILE.exists():
        cache = json.loads(SUBSECTION_EXTRACT_CACHE_FILE.read_text(encoding="utf-8"))
        logger.info("读取聚焦子章节提取缓存：%d 份", len(cache))

    for fname, text in summaries.items():
        if fname in cache:
            logger.info("[跳过子章节提取] %s（已有缓存）", fname)
            continue
        logger.info("[子章节提取] %s", fname)
        result = extract_subsections_from_summary(client, text, source_name=fname)
        cache[fname] = result.get(FOCUS_SECTION_KEY, {})
        SUBSECTION_EXTRACT_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return cache


def aggregate_focus(
    extracted: dict[str, list[str]],
    subsection_extracted: dict[str, dict[str, list[str]]],
) -> dict[str, object]:
    all_bullets: list[str] = []
    subsection_map: dict[str, list[str]] = {}

    for fname, bullets in extracted.items():
        label = Path(fname).stem.split("总结")[-1].strip()
        for bullet in bullets:
            tagged = f"[{label}] {bullet}" if label else bullet
            all_bullets.append(tagged)

    for fname, sub_map in subsection_extracted.items():
        label = Path(fname).stem.split("总结")[-1].strip()
        for sub_key, bullets in sub_map.items():
            subsection_map.setdefault(sub_key, [])
            for bullet in bullets:
                tagged = f"[{label}] {bullet}" if label else bullet
                subsection_map[sub_key].append(tagged)

    aggregated = {
        "section_key": FOCUS_SECTION_KEY,
        "section_title": FOCUS_SECTION_TITLE,
        "section_bullets_count": len(all_bullets),
        "subsections_count": len(subsection_map),
        "section_bullets": all_bullets,
        "subsections": subsection_map,
    }

    AGGREGATED_FILE.write_text(
        json.dumps(aggregated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("聚合结果已保存：%s", AGGREGATED_FILE)
    return aggregated


def build_preview_markdown(aggregated: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append(f"# {FOCUS_SECTION_TITLE}（聚焦版聚合预览）")
    lines.append("")
    lines.append(
        f"- 大章节要点总数：{aggregated.get('section_bullets_count', 0)}"
    )
    lines.append(
        f"- 子章节数量：{aggregated.get('subsections_count', 0)}"
    )
    lines.append("")
    lines.append("## 大章节直提要点")
    lines.append("")
    for b in aggregated.get("section_bullets", []):
        lines.append(f"- {b}")

    lines.append("")
    lines.append("## 子章节聚合要点")
    lines.append("")
    for sub_key, bullets in aggregated.get("subsections", {}).items():
        lines.append(f"### {sub_key}")
        lines.append("")
        for b in bullets:
            lines.append(f"- {b}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="聚焦版：仅跑发展基础提取与聚合")
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="跳过提取阶段，直接读取聚焦缓存",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        logger.error("未找到 DEEPSEEK_API_KEY，请检查 .env 文件")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)

    summaries = load_individual_summaries()
    if not summaries:
        logger.error("未读取到任何部门规划文件：%s", INPUT_DIR)
        sys.exit(1)
    logger.info("共读取 %d 份单部门规划", len(summaries))

    if args.skip_extract and EXTRACT_CACHE_FILE.exists():
        extracted = json.loads(EXTRACT_CACHE_FILE.read_text(encoding="utf-8"))
        logger.info("使用聚焦提取缓存")
    else:
        extracted = run_focus_extraction(client, summaries)

    if args.skip_extract and SUBSECTION_EXTRACT_CACHE_FILE.exists():
        subsection_extracted = json.loads(
            SUBSECTION_EXTRACT_CACHE_FILE.read_text(encoding="utf-8")
        )
        logger.info("使用聚焦子章节提取缓存")
    else:
        subsection_extracted = run_focus_subsection_extraction(client, summaries)

    aggregated = aggregate_focus(extracted, subsection_extracted)
    preview = build_preview_markdown(aggregated)
    PREVIEW_MD_FILE.write_text(preview, encoding="utf-8")
    logger.info("聚合预览已保存：%s", PREVIEW_MD_FILE)


if __name__ == "__main__":
    main()
