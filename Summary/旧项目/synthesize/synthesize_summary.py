#!/usr/bin/env python3
"""
synthesize_summary.py
─────────────────────
自动合成学科办工作总结。

流程：
  1. 读取所有个人总结 MD 文件
  2. [阶段一] 逐份调用 LLM 提取9维度工作要点（JSON）
  3. 聚合：按节合并所有人的要点列表
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
)
from synthesize.extractor import extract_from_summary
from synthesize.writer import write_section, compress_section, write_intro, _count_chars

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
OUTPUT_MD       = OUTPUT_PATH / OUTPUT_FILE


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: 读取个人总结
# ─────────────────────────────────────────────────────────────────────────────

def load_individual_summaries() -> dict[str, str]:
    """
    返回 {文件名: 正文内容}，排除部门总结本身。
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


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: 聚合——按节合并所有人的要点
# ─────────────────────────────────────────────────────────────────────────────

def aggregate(all_extractions: dict[str, dict]) -> dict[str, list[str]]:
    """
    按 section_key 聚合，去除完全重复的条目。
    返回 {section_key: [bullet, ...]}（保留来源标注以供审查）
    """
    aggregated: dict[str, list[str]] = {s["key"]: [] for s in SECTIONS}

    for fname, extraction in all_extractions.items():
        # 用文件名末尾的字母作为来源标记（如 "C"、"L" 等）
        label = Path(fname).stem.split("总结")[-1].strip()  # e.g. "C"
        for key, bullets in extraction.items():
            if key in aggregated:
                for b in bullets:
                    tagged = f"[{label}] {b}" if label else b
                    aggregated[key].append(tagged)

    # 打印聚合统计
    for s in SECTIONS:
        k = s["key"]
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
    aggregated: dict[str, list[str]],
    with_intro: bool = True,
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
        bullets = aggregated.get(key, [])
        logger.info(f"  [撰写] 第{section['id']}节「{key}」（{len(bullets)} 条要点）...")
        results[key] = write_section(client, section, bullets, SECTIONS)

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
        lines.append("学科建设与发展规划办公室2023年度工作总结\n")
    else:
        lines.append("# 学科建设与发展规划办公室2023年度工作总结\n")

    # 引言
    if "intro" in written and written["intro"]:
        lines.append(written["intro"])
        lines.append("")

    # 九节正文
    zh_nums = ["一", "二", "三", "四", "五", "六", "七", "八", "九"]
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

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="合成学科办工作总结")
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
    logger.info("Step 1  读取个人总结")
    summaries = load_individual_summaries()
    if not summaries:
        logger.error(f"在 {INPUT_PATH} 未找到任何个人总结 MD 文件")
        sys.exit(1)
    logger.info(f"  共读取 {len(summaries)} 份个人总结\n")

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
    logger.info("Step 3  聚合要点")
    aggregated = aggregate(all_extractions)
    logger.info("")

    # ── Step 4 ──
    logger.info("═" * 55)
    logger.info("Step 4  阶段二：逐节撰写")
    written = run_writing(client, aggregated, with_intro=not args.no_intro)
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
