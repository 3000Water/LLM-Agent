"""
校验 synthesize/config_mapping.json 的结构完整性。

用法：
    python synthesize/mapping/validate_mapping.py
"""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "synthesize" / "config_mapping.json"

REQUIRED_SECTION_IDS = {1, 2, 3, 4, 5}
REQUIRED_SUBSECTIONS = {
    3: ["指导思想", "遵循原则", "发展目标", "总体思路"],
    5: ["党的领导", "社会合作", "资源协调", "规划实施"],
}


def main() -> int:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sections = data.get("sections", [])
    errors: list[str] = []

    seen_section_ids = set()
    seen_section_keys = set()
    seen_subsection_keys = set()

    for section in sections:
        sid = section.get("section_id")
        skey = section.get("section_key", "").strip()
        stitle = section.get("section_title", "").strip()
        subs = section.get("subsections", [])

        if sid in seen_section_ids:
            errors.append(f"重复 section_id: {sid}")
        seen_section_ids.add(sid)

        if not skey:
            errors.append(f"section_id={sid} 缺失 section_key")
        elif skey in seen_section_keys:
            errors.append(f"重复 section_key: {skey}")
        else:
            seen_section_keys.add(skey)

        if not stitle:
            errors.append(f"section_id={sid} 缺失 section_title")

        if not isinstance(subs, list):
            errors.append(f"section_id={sid} 的 subsections 不是数组")
            continue

        actual_titles = []
        for sub in subs:
            title = str(sub.get("title", "")).strip()
            key = str(sub.get("key", "")).strip()
            index = sub.get("index")

            actual_titles.append(title)
            if not title:
                errors.append(f"section_id={sid} 存在空子章节标题")
            if not key:
                errors.append(f"section_id={sid} 的子章节「{title}」缺失 key")
            elif key in seen_subsection_keys:
                errors.append(f"重复 subsection key: {key}")
            else:
                seen_subsection_keys.add(key)
            if not isinstance(index, int):
                errors.append(f"section_id={sid} 的子章节「{title}」缺失整数 index")

            sources = sub.get("sources", [])
            if not isinstance(sources, list):
                errors.append(f"section_id={sid} 的子章节「{title}」sources 不是数组")
            elif len(sources) == 0:
                errors.append(f"section_id={sid} 的子章节「{title}」sources 为空")

        required = REQUIRED_SUBSECTIONS.get(sid)
        if required:
            missing = [name for name in required if name not in actual_titles]
            if missing:
                errors.append(
                    f"section_id={sid} 缺失必需子章节: {', '.join(missing)}"
                )

    missing_ids = REQUIRED_SECTION_IDS - seen_section_ids
    if missing_ids:
        errors.append(f"缺失章节 ID: {sorted(missing_ids)}")

    if errors:
        print("❌ config_mapping 校验失败：")
        for err in errors:
            print(f"- {err}")
        return 1

    print("✅ config_mapping 校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
