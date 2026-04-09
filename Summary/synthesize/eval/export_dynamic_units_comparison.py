#!/usr/bin/env python3
"""
导出动态分点对比表（CSV + Markdown）。

输入：
  - output/intermediate/dynamic_units_plan.json
  - output/intermediate/dynamic_units_metrics.json

输出：
  - output/intermediate/dynamic_units_comparison.csv
  - output/intermediate/dynamic_units_comparison.md
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INTER = ROOT / "output" / "intermediate"
PLAN_FILE = INTER / "dynamic_units_plan.json"
METRICS_FILE = INTER / "dynamic_units_metrics.json"
CSV_FILE = INTER / "dynamic_units_comparison.csv"
MD_FILE = INTER / "dynamic_units_comparison.md"


def main() -> int:
    if not PLAN_FILE.exists() or not METRICS_FILE.exists():
        print("❌ 缺少输入文件，请先运行主流程生成 dynamic_units_plan/metrics。")
        print(f"- 需要: {PLAN_FILE}")
        print(f"- 需要: {METRICS_FILE}")
        return 1

    plan = json.loads(PLAN_FILE.read_text(encoding="utf-8"))
    metrics = json.loads(METRICS_FILE.read_text(encoding="utf-8"))
    rows = build_rows(plan, metrics)
    write_csv(rows, CSV_FILE)
    write_md(rows, MD_FILE)
    print(f"✅ 已导出: {CSV_FILE}")
    print(f"✅ 已导出: {MD_FILE}")
    return 0


def build_rows(plan: dict, metrics: dict) -> list[dict]:
    out = []
    sec_metrics = metrics.get("sections", {})
    for section_key, stat in sec_metrics.items():
        plan_item = plan.get(section_key, {})
        mode = stat.get("mode", "flat")
        selected = stat.get("selected", {})
        cand = stat.get("candidates", {})
        unit_titles = ""
        if mode == "split":
            unit_titles = " | ".join([u.get("title", "") for u in plan_item.get("units", [])])

        out.append(
            {
                "section_key": section_key,
                "section_title": stat.get("section_title", ""),
                "mode": mode,
                "bullet_count": stat.get("bullet_count", 0),
                "total_chars": stat.get("total_chars", 0),
                "selected_method": selected.get("method", ""),
                "selected_k": selected.get("k", ""),
                "selected_silhouette": selected.get("silhouette", ""),
                "selected_intra_similarity": selected.get("intra_similarity", ""),
                "keyword_k": cand.get("keyword", {}).get("k", ""),
                "keyword_silhouette": cand.get("keyword", {}).get("silhouette", ""),
                "keyword_intra_similarity": cand.get("keyword", {}).get("intra_similarity", ""),
                "embedding_k": cand.get("embedding", {}).get("k", ""),
                "embedding_silhouette": cand.get("embedding", {}).get("silhouette", ""),
                "embedding_intra_similarity": cand.get("embedding", {}).get("intra_similarity", ""),
                "unit_titles": unit_titles,
            }
        )
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_md(rows: list[dict], path: Path) -> None:
    lines = []
    lines.append("# 动态分点对比表")
    lines.append("")
    lines.append(
        "| 章节 | 模式 | bullets | 字数 | 采用方法 | 采用k | 采用sil | 采用intra | "
        "kw(k/sil/intra) | emb(k/sil/intra) | 分点标题 |"
    )
    lines.append("|---|---:|---:|---:|---|---:|---:|---:|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['section_title']}({r['section_key']}) | {r['mode']} | {r['bullet_count']} | "
            f"{r['total_chars']} | {r['selected_method']} | {r['selected_k']} | "
            f"{r['selected_silhouette']} | {r['selected_intra_similarity']} | "
            f"{r['keyword_k']}/{r['keyword_silhouette']}/{r['keyword_intra_similarity']} | "
            f"{r['embedding_k']}/{r['embedding_silhouette']}/{r['embedding_intra_similarity']} | "
            f"{r['unit_titles']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
