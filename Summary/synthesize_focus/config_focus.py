"""
聚焦版配置：仅用于“发展基础”章节的快速提取与聚合调试。
"""

from pathlib import Path

# 项目根目录（Summary）
ROOT = Path(__file__).resolve().parent.parent

# 输入与输出
INPUT_DIR = ROOT / "markdown_output" / "source"
DEPT_SUMMARY_FILE = "南京大学“十四五”规划.md"

OUTPUT_DIR = ROOT / "output" / "focus_发展基础"
INTERMEDIATE_DIR = OUTPUT_DIR / "intermediate"

# 产物文件
EXTRACT_CACHE_FILE = INTERMEDIATE_DIR / "extracted_发展基础.json"
SUBSECTION_EXTRACT_CACHE_FILE = INTERMEDIATE_DIR / "subsection_extracted_发展基础.json"
AGGREGATED_FILE = INTERMEDIATE_DIR / "aggregated_发展基础.json"
PREVIEW_MD_FILE = OUTPUT_DIR / "发展基础_聚合预览.md"

# 仅聚焦这一节
FOCUS_SECTION_KEY = "发展基础"
FOCUS_SECTION_TITLE = "发展基础"
