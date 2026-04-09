#!/usr/bin/env python3
"""
synthesize_summary.py
─────────────────────
自动合成“南京大学十四五规划汇总”。

流程：
  1. 读取所有单部门规划 MD 文件
  2. [阶段一] 逐份调用 LLM 提取5章节规划要点（JSON）
  3. 聚合：按章节合并多部门要点
  4. [阶段二] 逐节调用 LLM 撰写正文段落
  5. 可选：调用 LLM 生成开篇引言
  6. 组装 Markdown 并写入文件

中间结果保存至 output/intermediate/ 便于调试和重跑。

用法：
    .venv/bin/python synthesize/synthesize_summary.py [--skip-extract]

    --skip-extract  跳过提取阶段，直接读取已有的 intermediate JSON
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# 把项目根目录加入 path，保证 synthesize 包可导入
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from synthesize.config import (
    SECTIONS,
    INPUT_DIR,
    DEPT_SUMMARY_FILE,
    OUTPUT_DIR,
    OUTPUT_FILE,
    DEEPSEEK_BASE_URL,
    SECTION_HEADING_STYLE,
    COMPRESS_TOLERANCE,
    CONFIG_MAPPING_FILE,
    GENERATE_INTRO,
    GENERATE_CONCLUSION,
    DYNAMIC_UNITS_ENABLED,
    DYNAMIC_UNITS_METHOD,
    DYNAMIC_UNITS_MIN_BULLETS,
    DYNAMIC_UNITS_MIN_CHARS,
    DYNAMIC_UNITS_MIN_K,
    DYNAMIC_UNITS_MAX_K,
)
from synthesize.extractor import (
    extract_from_summary,
    extract_subsections_from_summary,
)
from synthesize.writer import (
    write_section,
    compress_section,
    write_intro,
    write_conclusion,
    _count_chars,
)
from synthesize.dynamic_units import build_dynamic_units

# ── 日志配置 ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 路径 ──────────────────────────────────────────────────────────────────────
INPUT_PATH      = ROOT / INPUT_DIR
OUTPUT_PATH     = ROOT / OUTPUT_DIR
INTER_PATH      = OUTPUT_PATH / "intermediate"
EXTRACT_CACHE   = INTER_PATH / "extracted.json"
SUBSECTION_EXTRACT_CACHE = INTER_PATH / "subsection_extracted.json"
OUTPUT_MD       = OUTPUT_PATH / OUTPUT_FILE


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: 读取单部门规划
# ─────────────────────────────────────────────────────────────────────────────

def load_individual_summaries() -> dict[str, str]:
    """
    返回 {文件名: 正文内容}，排除学校总规划文件本身。
    """
    files = {}
    for p in sorted(INPUT_PATH.glob("*.md")):
        if p.name == DEPT_SUMMARY_FILE:
            continue
        text = p.read_text(encoding="utf-8")
        # 去掉第一行 H1 标题（由脚本生成的 "# 文件名"），保留正文
        lines = text.splitlines()
        body = "\n".join(lines[2:] if lines and lines[0].startswith("#") else lines)
        files[p.name] = body.strip()
        logger.info(f"  已读取: {p.name}  ({len(body)} 字)")
    return files


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: 阶段一——逐份提取
# ─────────────────────────────────────────────────────────────────────────────

def run_extraction(client: OpenAI, summaries: dict[str, str]) -> dict[str, dict]:
    """
    返回 {文件名: {section_key: [bullet, ...]}}
    同时写入 EXTRACT_CACHE 作为断点续跑缓存。
    """
    # 读取已有缓存（支持断点续跑）
    cache: dict[str, dict] = {}
    if EXTRACT_CACHE.exists():
        cache = json.loads(EXTRACT_CACHE.read_text(encoding="utf-8"))
        logger.info(f"  读取提取缓存: {list(cache.keys())}")

    for fname, text in summaries.items():
        if fname in cache:
            logger.info(f"  [跳过] {fname}（已有缓存）")
            continue
        logger.info(f"  [提取] {fname} ...")
        result = extract_from_summary(client, text, source_name=fname)
        cache[fname] = result
        # 每次提取后立即写缓存，防止中途失败丢数据
        EXTRACT_CACHE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"         要点数: { {k: len(v) for k, v in result.items()} }")

    return cache


def run_subsection_extraction(client: OpenAI, summaries: dict[str, str]) -> dict[str, dict]:
    """
    从每份单部门规划中提取有子章节大章节的子节要点。

    返回：{文件名: {section_key: {subsection_key: [bullet, ...]}}}
    """
    cache: dict[str, dict] = {}
    if SUBSECTION_EXTRACT_CACHE.exists():
        cache = json.loads(SUBSECTION_EXTRACT_CACHE.read_text(encoding="utf-8"))
        logger.info(f"  读取子章节提取缓存: {list(cache.keys())}")

    for fname, text in summaries.items():
        if fname in cache:
            logger.info(f"  [子章节提取] 跳过 {fname}（已有缓存）")
            continue
        logger.info(f"  [子章节提取] {fname} ...")
        result = extract_subsections_from_summary(client, text, source_name=fname)
        cache[fname] = result
        SUBSECTION_EXTRACT_CACHE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"         子章节提取完成: { {k: len(v) for k, v in result.items()} }")

    return cache


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: 聚合——按节合并所有人的要点
# ─────────────────────────────────────────────────────────────────────────────

def aggregate(
    all_extractions: dict[str, dict],
    all_subsection_extractions: dict[str, dict],
) -> dict[str, object]:
    """
    聚合提取结果。
    返回结构：
      - 普通章节：{section_key: [bullet, ...]}
      - 有子章节章节：{section_key: {subsection_key: [bullet, ...]}}
    """
    aggregated: dict[str, object] = {}
    section_map = {s["key"]: s for s in SECTIONS}

    # 初始化聚合结构
    for s in SECTIONS:
        if s.get("has_subsections", False):
            aggregated[s["key"]] = {}
        else:
            aggregated[s["key"]] = []

    # 聚合普通章节内容
    for fname, extraction in all_extractions.items():
        label = Path(fname).stem.split("总结")[-1].strip()
        for key, bullets in extraction.items():
            section = section_map.get(key)
            if not section:
                continue
            if section.get("has_subsections", False):
                continue
            if key in aggregated and isinstance(aggregated[key], list):
                for b in bullets:
                    tagged = f"[{label}] {b}" if label else b
                    aggregated[key].append(tagged)

    # 聚合子章节内容
    for fname, extraction in all_subsection_extractions.items():
        label = Path(fname).stem.split("总结")[-1].strip()
        for section_key, subsection_map in extraction.items():
            if section_key not in aggregated or not isinstance(aggregated[section_key], dict):
                continue
            for subkey, bullets in subsection_map.items():
                if subkey not in aggregated[section_key]:
                    aggregated[section_key][subkey] = []
                for b in bullets:
                    tagged = f"[{label}] {b}" if label else b
                    aggregated[section_key][subkey].append(tagged)

    # 打印聚合统计
    for s in SECTIONS:
        k = s["key"]
        if s.get("has_subsections", False):
            count = sum(len(v) for v in aggregated[k].values())
            logger.info(f"  第{s['id']}节「{k}」: {count} 条子章节要点")
        else:
            logger.info(f"  第{s['id']}节「{k}」: {len(aggregated[k])} 条要点")

    # 保存聚合结果以供人工检查
    agg_file = INTER_PATH / "aggregated.json"
    agg_file.write_text(
        json.dumps(aggregated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"  聚合结果已保存: {agg_file}")

    return aggregated


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 & 5: 阶段二——逐节撰写 + 可选引言
# ─────────────────────────────────────────────────────────────────────────────

def run_writing(
    client: OpenAI,
    aggregated: dict[str, object],
    dynamic_unit_plan: dict[str, dict] | None = None,
    with_intro: bool = True,
    with_conclusion: bool = True,
) -> dict[str, str]:
    """
    返回 {section_key: paragraph_text}，以及可选的 "intro" key。
    """
    results: dict[str, str] = {}

    # 可选：生成引言
    if with_intro:
        logger.info("  [撰写] 生成引言...")
        results["intro"] = write_intro(client, SECTIONS)

    # 逐节撰写
    for section in SECTIONS:
        key = section["key"]
        plan = (dynamic_unit_plan or {}).get(key, {"mode": "flat", "bullets": aggregated.get(key, [])})
        if plan.get("mode") == "split":
            units = plan.get("units", [])
            subsection_bullets = {u["key"]: u.get("bullets", []) for u in units}
            section_for_write = dict(section)
            section_for_write["has_subsections"] = True
            section_for_write["subsections"] = [
                {"key": u["key"], "title": u["title"], "index": u["index"]} for u in units
            ]
            logger.info(
                f"  [撰写] 第{section['id']}节「{key}」动态分点：{len(units)} 个（method={plan.get('method')}）..."
            )
            results[key] = write_section(client, section_for_write, subsection_bullets, SECTIONS)
        else:
            bullets = plan.get("bullets", aggregated.get(key, []))
            logger.info(f"  [撰写] 第{section['id']}节「{key}」（{len(bullets)} 条要点）...")
            results[key] = write_section(client, section, bullets, SECTIONS)

    # 保存写作结果
    if with_conclusion:
        logger.info("  [撰写] 生成结语...")
        results["conclusion"] = write_conclusion(client, SECTIONS)

    # 保存写作结果
    write_file = INTER_PATH / "written.json"
    write_file.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"  撰写结果已保存: {write_file}")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Step 4.5: 压缩超标章节
# ─────────────────────────────────────────────────────────────────────────────

def run_compression(client: OpenAI, written: dict[str, str]) -> dict[str, str]:
    """
    对字数超过 max * COMPRESS_TOLERANCE 的章节触发压缩调用。
    """
    for section in SECTIONS:
        key = section["key"]
        content = written.get(key, "")
        if not content:
            continue
        actual = _count_chars(content)
        max_w = section["word_range"][1]
        if actual > max_w * COMPRESS_TOLERANCE:
            logger.info(
                f"  [压缩] 第{section['id']}节「{key}」{actual}字 > 上限{max_w}字×{COMPRESS_TOLERANCE}，触发压缩..."
            )
            written[key] = compress_section(client, section, content)
        else:
            logger.info(f"  [字数] 第{section['id']}节「{key}」{actual}字 ✓")
    return written


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: 组装最终 Markdown
# ─────────────────────────────────────────────────────────────────────────────

def assemble_markdown(written: dict[str, str]) -> str:
    """
    按固定结构组装完整的 Markdown 文档。
    标题样式由 config.SECTION_HEADING_STYLE 控制：
      "bold" → __一、标题__（与原文格式一致）
      "h2"   → ## 一、标题
    """
    lines: list[str] = []

    # 文档标题
    if SECTION_HEADING_STYLE == "bold":
        lines.append("南京大学“十四五”规划汇总\n")
    else:
        lines.append("# 南京大学“十四五”规划汇总\n")

    # 引言
    if "intro" in written and written["intro"]:
        lines.append(written["intro"])
        lines.append("")

    # 五节正文
    zh_nums = ["一", "二", "三", "四", "五"]
    for i, section in enumerate(SECTIONS):
        key   = section["key"]
        num   = zh_nums[i]
        title = section["title"]
        body  = written.get(key, "（内容缺失）")

        if SECTION_HEADING_STYLE == "bold":
            lines.append(f"__{num}、{title}__\n")
        else:
            lines.append(f"## {num}、{title}\n")

        lines.append(body)
        lines.append("")

    # 结语（非编号章节）
    if "conclusion" in written and written["conclusion"]:
        if SECTION_HEADING_STYLE == "bold":
            lines.append("__结语__\n")
        else:
            lines.append("## 结语\n")
        lines.append(written["conclusion"])
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="合成南京大学十四五规划汇总")
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="跳过提取阶段，直接从 intermediate/extracted.json 读取",
    )
    parser.add_argument(
        "--no-intro",
        action="store_true",
        help="不生成引言段落",
    )
    parser.add_argument(
        "--no-conclusion",
        action="store_true",
        help="不生成结语段落",
    )
    args = parser.parse_args()

    # 加载环境变量
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        logger.error("未找到 DEEPSEEK_API_KEY，请检查 .env 文件")
        sys.exit(1)

    # 初始化 OpenAI 客户端（指向 DeepSeek）
    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

    # 创建输出目录
    OUTPUT_PATH.mkdir(exist_ok=True)
    INTER_PATH.mkdir(exist_ok=True)

    # ── Step 1 ──
    logger.info("═" * 55)
    logger.info("Step 1  读取单部门规划")
    summaries = load_individual_summaries()
    if not summaries:
        logger.error(f"在 {INPUT_PATH} 未找到任何单部门规划 MD 文件")
        sys.exit(1)
    logger.info(f"  共读取 {len(summaries)} 份单部门规划\n")

    # ── Step 2 ──
    logger.info("═" * 55)
    logger.info("Step 2  阶段一：结构化提取")
    if args.skip_extract and EXTRACT_CACHE.exists():
        logger.info("  使用已有提取缓存（--skip-extract）")
        all_extractions = json.loads(EXTRACT_CACHE.read_text(encoding="utf-8"))
    else:
        all_extractions = run_extraction(client, summaries)
    logger.info("")

    # ── Step 3 ──
    logger.info("═" * 55)
    logger.info("Step 3  子章节提取（有子章节的大章节）")
    if args.skip_extract and SUBSECTION_EXTRACT_CACHE.exists():
        logger.info("  使用已有子章节提取缓存（--skip-extract）")
        subsection_extractions = json.loads(SUBSECTION_EXTRACT_CACHE.read_text(encoding="utf-8"))
    else:
        subsection_extractions = run_subsection_extraction(client, summaries)
    logger.info("")

    logger.info("═" * 55)
    logger.info("Step 4  聚合要点")
    aggregated = aggregate(all_extractions, subsection_extractions)
    logger.info("")

    logger.info("═" * 55)
    logger.info("Step 4.2  动态分点构建与方法对比")
    dynamic_plan, dynamic_report = build_dynamic_units(
        sections=SECTIONS,
        aggregated=aggregated,
        options={
            "enabled": DYNAMIC_UNITS_ENABLED,
            "method": DYNAMIC_UNITS_METHOD,
            "min_bullets_to_split": DYNAMIC_UNITS_MIN_BULLETS,
            "min_chars_to_split": DYNAMIC_UNITS_MIN_CHARS,
            "min_units": DYNAMIC_UNITS_MIN_K,
            "max_units": DYNAMIC_UNITS_MAX_K,
        },
    )
    dynamic_plan_file = INTER_PATH / "dynamic_units_plan.json"
    dynamic_plan_file.write_text(
        json.dumps(dynamic_plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    dynamic_report_file = INTER_PATH / "dynamic_units_metrics.json"
    dynamic_report_file.write_text(
        json.dumps(dynamic_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"  动态分点方案已保存: {dynamic_plan_file}")
    logger.info(f"  对比指标已保存: {dynamic_report_file}")
    logger.info("")

    # ── Step 5 ──
    logger.info("═" * 55)
    logger.info("Step 5  阶段二：逐节撰写")
    written = run_writing(
        client,
        aggregated,
        dynamic_unit_plan=dynamic_plan,
        with_intro=(GENERATE_INTRO and not args.no_intro),
        with_conclusion=(GENERATE_CONCLUSION and not args.no_conclusion),
    )
    logger.info("")

    # ── Step 4.5: 压缩超标章节 ──
    logger.info("═" * 55)
    logger.info("Step 4.5  字数校验与压缩")
    written = run_compression(client, written)
    # 保存最终写作结果（含压缩后）
    final_file = INTER_PATH / "written_final.json"
    final_file.write_text(
        json.dumps(written, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("")

    # ── Step 5 ──
    logger.info("═" * 55)
    logger.info("Step 5  组装 Markdown")
    md = assemble_markdown(written)
    OUTPUT_MD.write_text(md, encoding="utf-8")
    logger.info(f"  ✅ 已生成: {OUTPUT_MD}")
    logger.info(f"  字数约: {len(md.replace(' ','').replace(chr(10),'')):,}")


if __name__ == "__main__":
    main()
