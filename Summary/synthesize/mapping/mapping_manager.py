"""
功能：从 full_mapping_relationships.csv 生成 config_mapping.json
"""

import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Any

# 兼容直接运行：python synthesize/mapping/mapping_manager.py
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from synthesize.config import SECTIONS


class MappingBuilder:
    """从 CSV 构建 Mapping 配置"""
    REQUIRED_SUBSECTIONS = {
        "指导方针和主要目标": ["指导思想", "遵循原则", "发展目标", "总体思路"],
        "组织与保障": ["党的领导", "社会合作", "资源协调", "规划实施"],
    }
    
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.mappings = []
        self._load_csv()
    
    def _load_csv(self):
        """加载 CSV 并解析"""
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.mappings.append(row)
    
    def build_config(self) -> Dict[str, Any]:
        """
        构建 config_mapping.json 结构
        
        CSV 格式：最大章节 | 子标题 | 贡献文件 | 映射特征
        
        返回：
        {
          "sections": [
            {
              "section_id": int,
              "section_key": str,
              "section_title": str,
              "subsections": [
                {
                  "index": int,
                  "title": str,
                  "key": str,
                  "sources": [
                    {"file": str, "weight": float, "description": str}
                  ]
                }
              ]
            }
          ]
        }
        """
        # 第一步：按节分组
        sections_dict = {}
        subsections_dict = {}
        
        for row in self.mappings:
            section_title = self._normalize_section_title(row['最大章节'].strip())
            subtitle = row['子标题'].strip() if row['子标题'] else ""
            file_name = row['贡献文件'].strip() if row['贡献文件'] else ""
            mapping_feature = row['映射特征'].strip() if row['映射特征'] else ""
            
            if not section_title:
                continue
            
            # 确保这个大章节在字典中
            if section_title not in sections_dict:
                sections_dict[section_title] = []
                subsections_dict[section_title] = {}
            
            # 如果有子标题（即有小章节），记录映射
            if subtitle and file_name:
                subsection_key = self._gen_subsection_key(subtitle)
                
                if subsection_key not in subsections_dict[section_title]:
                    subsections_dict[section_title][subsection_key] = {
                        "title": subtitle,
                        "key": subsection_key,
                        "sources": []
                    }
                
                # 解析占比（从映射特征中提取，如"占比85%"）
                weight = self._parse_weight(mapping_feature)
                
                subsections_dict[section_title][subsection_key]["sources"].append({
                    "file": file_name,
                    "weight": weight,
                    "description": self._gen_description(mapping_feature)
                })
        
        # 第二步：构建最终的 config 结构
        config = {"sections": []}
        section_id = 1
        
        # 按大章节顺序处理
        section_meta = self._section_meta_by_title()
        section_order = [s["title"] for s in SECTIONS]
        
        for section_title in section_order:
            if section_title not in subsections_dict:
                continue
            
            # 以 config.SECTIONS 为准，确保 section_key 与主流程一致（中文）
            section_key = section_meta[section_title]["key"]
            section_id = section_meta[section_title]["id"]
            
            # 按子标题出现顺序排列
            subsections_list = list(subsections_dict[section_title].values())
            for idx, subsection in enumerate(subsections_list, start=1):
                subsection['index'] = idx
            
            config["sections"].append({
                "section_id": section_id,
                "section_key": section_key,
                "section_title": section_title,
                "subsections": subsections_list
            })
        self._validate_required_subsections(config)
        return config

    def _validate_required_subsections(self, config: Dict[str, Any]) -> None:
        """校验关键章节的小节数量与标题完整性。"""
        section_map = {s["section_title"]: s for s in config.get("sections", [])}
        for section_title, required_titles in self.REQUIRED_SUBSECTIONS.items():
            section = section_map.get(section_title)
            if not section:
                raise ValueError(f"缺失必需章节：{section_title}")
            actual_titles = [s.get("title", "").strip() for s in section.get("subsections", [])]
            missing = [t for t in required_titles if t not in actual_titles]
            if missing:
                raise ValueError(
                    f"章节「{section_title}」缺失必需子章节：{', '.join(missing)}"
                )

    @staticmethod
    def _normalize_section_title(title: str) -> str:
        """
        统一章节标题，消除 CSV 与 config 中的细微差异。
        """
        t = (title or "").strip()
        aliases = {
            "组织保障": "组织与保障",
            "指导方针与主要目标": "指导方针和主要目标",
        }
        return aliases.get(t, t)

    def _section_meta_by_title(self) -> Dict[str, Dict[str, Any]]:
        """
        返回按标题索引的章节元数据，全部来自 config.SECTIONS。
        """
        meta = {}
        for s in SECTIONS:
            title = self._normalize_section_title(s["title"])
            meta[title] = {"id": s["id"], "key": s["key"], "title": s["title"]}
        return meta
    
    @staticmethod
    def _gen_section_key(title: str) -> str:
        """生成大章节的 key"""
        mapping = {
            "发展基础": "发展基础",
            "发展环境": "发展环境",
            "指导方针和主要目标": "方针目标",
            "建设任务": "建设任务",
            "组织与保障": "组织保障"
        }
        return mapping.get(title, title.lower().replace(" ", "_"))
    
    @staticmethod
    def _gen_subsection_key(title: str) -> str:
        """生成小章节的 key（简化版，去掉中文，用下划线）"""
        stable_mapping = {
            "指导思想": "guiding_ideology",
            "遵循原则": "guiding_principles",
            "发展目标": "development_targets",
            "总体思路": "overall_approach",
            "党的领导": "party_leadership",
            "社会合作": "social_collaboration",
            "资源协调": "resource_coordination",
            "规划实施": "planning_implementation",
        }
        if title in stable_mapping:
            return stable_mapping[title]

        # 未定义稳定 key 时，使用哈希兜底，避免 key 冲突
        import hashlib
        hash_val = hashlib.md5(title.encode()).hexdigest()[:8]
        return f"subsection_{hash_val}"
    
    @staticmethod
    def _parse_weight(feature_text: str) -> float:
        """
        从映射特征文本中解析权重
        例如："占比85%" → 0.85
        """
        import re
        match = re.search(r'占比(\d+)%', feature_text)
        if match:
            return float(match.group(1)) / 100
        
        # 如果没有明确占比，根据描述推断
        if "占大篇幅" in feature_text or "完全对应" in feature_text:
            return 1.0
        elif "作为补充" in feature_text:
            return 0.2
        else:
            return 0.5  # 默认等权重
    
    @staticmethod
    def _gen_description(feature_text: str) -> str:
        """生成此源文件对该小章节的贡献描述"""
        # 简单方案：直接返回映射特征
        return feature_text


def save_config_mapping(config: Dict, output_path: str):
    """保存为 JSON"""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"✅ 已保存：{output_path}")


def load_config_mapping(config_path: str) -> Dict:
    """加载 config_mapping.json"""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ────────────────────────────────────────────────────────────────────────────
# 使用示例
# ────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    csv_path = "synthesize/mapping/full_mapping_relationships.csv"
    output_path = "synthesize/config_mapping.json"
    
    builder = MappingBuilder(csv_path)
    config = builder.build_config()
    
    # 打印结构预览
    print("生成的 Mapping 结构预览：")
    for section in config["sections"]:
        print(f"\n📌 {section['section_title']}（{len(section['subsections'])} 个小章节）")
        for subsection in section['subsections']:
            print(f"  ({subsection['index']}) {subsection['title']}")
            for source in subsection['sources']:
                print(f"     ← {source['file']}（权重 {source['weight']:.0%}）")
    
    # 保存
    save_config_mapping(config, output_path)
