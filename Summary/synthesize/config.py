"""
5个固定章节的定义。
每个 section 包含：
  - id          : 序号
  - key         : 短名，用于 JSON key
  - title       : 最终输出的章节标题（与规划汇总结构一致）
  - description : 该节涵盖的工作范围，用于提示 LLM 做分类提取
  - exclude     : 明确不属于本节的内容类型（排他说明，防止跨节溢出）
  - word_range  : (min, max) 期望撰写的汉字字数区间
"""

SECTIONS = [
    {
        "id": 1,
        "title": "发展基础",
        "key": "发展基础",
        "has_subsections": False,
        "description": (
            "本章聚焦学校“十四五”时期的既有基础与现实起点，强调“已经形成、已经取得、"
            "已经具备”的条件和成效，表达层级以现状、成果、基础能力为主。"
            "核心范围包括：党的全面领导基础、人才培养基础、人才队伍基础、科研创新基础、"
            "文化传承与学术体系基础、服务国家战略基础、国际交流合作基础、学科建设基础、"
            "依法治校与治理能力基础、校园文化与民生保障基础、多校区协同发展基础。"
            "典型证据锚词：已建成、已形成、已建立、已取得、持续提升、现有、目前、累计、位居。"
        ),
        "exclude": (
            ""
        ),
        "word_range": [4200, 5000]
    },
    {
        "id": 2,
        "title": "发展环境",
        "key": "发展环境",
        "has_subsections": False,
        "description": (
            "本章聚焦学校发展所处的外部环境与阶段条件，强调“形势判断、机遇挑战、约束条件、"
            "问题诊断”，为后续方针目标与建设任务提供背景依据。"
            "核心范围包括：国家战略与国际形势、科技与教育竞争格局、政策导向与区域需求、"
            "学校发展阶段特征、主要短板与风险挑战、环境约束下的发展判断。"
            "典型证据锚词：外部环境、形势、机遇、挑战、约束、压力、趋势、窗口期、短板、瓶颈。"
        ),
        "exclude": (
            ""
        ),
        "word_range": [1100, 1500]
    },
    {
        "id": 3,
        "title": "指导方针和主要目标",
        "key": "方针目标",
        "has_subsections": False,
        "description": (
            "本章聚焦学校“十四五”时期的顶层设计，强调“为什么发展、按什么原则发展、"
            "发展到什么程度、按什么路径推进”，表达层级以指导思想、基本原则、发展目标、总体思路为主。"
            "核心范围包括：指导思想、遵循原则、阶段性与中长期目标、总体推进路径与战略安排。"
            "典型证据锚词：坚持、以...为指导、原则、目标、到...年、总体思路、战略安排、路径。"
        ),
        "exclude": (
            ""
        ),
        "word_range": [3600, 4000]
    },
    {
        "id": 4,
        "title": "建设任务",
        "key": "建设任务",
        "has_subsections": False,
        "description": (
            "本章聚焦落实方针目标的任务体系与行动路径，强调“做什么、怎么做、由谁推进、"
            "形成什么阶段成效”，表达层级以任务项、举措项、工程项、机制项为主。"
            "核心范围包括十个任务方向：人才培养、队伍建设、科研创新、文化传承、学科生态、"
            "开放办学、社会服务、多校区协同、师生感受提升、党的建设。"
            "典型证据锚词：实施、推进、构建、打造、完善、建立、重点任务、专项行动、工程、计划。"
        ),
        "exclude": (
            ""
        ),
        "word_range": [18500, 21500]
    },
    {
        "id": 5,
        "title": "组织与保障",
        "key": "组织保障",
        "has_subsections": False,
        "description": (
            "本章聚焦规划落地的保障体系，强调“组织领导、社会协同、资源统筹、实施机制与监督评估”，"
            "为建设任务提供持续执行条件。"
            "核心范围包括：党的领导保障、社会合作保障、资源协调保障、规划实施保障。"
            "典型证据锚词：领导机制、责任分工、协同联动、资源配置、要素保障、督查评估、闭环落实。"
        ),
        "exclude": (
            ""
        ),
        "word_range": [900, 1300]
    }
]

# ── 输出格式 ──────────────────────────────────────────────────────────────────
# "bold"  → 原文格式：__一、标题__
# "h2"    → Markdown 格式：## 一、标题
SECTION_HEADING_STYLE = "bold"

# 字数超标容忍比例（超出 max * COMPRESS_TOLERANCE 则触发压缩）
COMPRESS_TOLERANCE = 1.15

# ── 路径配置 ──────────────────────────────────────────────────────────────────
INPUT_DIR = "markdown_output/source"   # 单部门规划源文件目录
DEPT_SUMMARY_FILE = "南京大学“十四五”规划.md"  # 排除该文件（学校总规划原文）
OUTPUT_DIR = "output"
OUTPUT_FILE = "部处十四五规划汇总_合成.md"
CONFIG_MAPPING_FILE = "synthesize/config_mapping.json"

# ── LLM 配置 ──────────────────────────────────────────────────────────────────
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
TEMPERATURE_EXTRACT = 0.2   # 提取阶段：低温，减少发散
TEMPERATURE_WRITE = 0.6     # 撰写阶段：稍高，文风更自然
MAX_RETRIES = 3

# —— 引言配置 ──────────────────────────────────────────────────────────────────
GENERATE_INTRO = True
INTRO_WORD_RANGE = [250, 350]

# —— 结语配置 ──────────────────────────────────────────────────────────────────
GENERATE_CONCLUSION = True
CONCLUSION_WORD_RANGE = [100, 200]

# —— 动态分点配置 ────────────────────────────────────────────────────────────────
DYNAMIC_UNITS_ENABLED = True
# auto: 比较关键词/embedding指标后自动选择；keyword/embedding: 强制指定
DYNAMIC_UNITS_METHOD = "auto"
DYNAMIC_UNITS_MIN_BULLETS = 8
DYNAMIC_UNITS_MIN_CHARS = 600
DYNAMIC_UNITS_MIN_K = 2
DYNAMIC_UNITS_MAX_K = 8

# —— Token 优化配置 ──────────────────────────────────────────────────────────────
# 主提取阶段是否额外回填子章节标签到 extracted.json（会增加一次子章节提取调用）
ENABLE_SUBSECTION_LABEL_BACKFILL = False
# 写作提示中每章最多保留多少条 bullets（超出时按去重+截断裁剪）
WRITE_MAX_BULLETS_PER_SECTION = 120
# 写作提示中 bullets 文本最大字符数（超过则截断）
WRITE_MAX_BULLET_CHARS = 12000
# 子节写作提示中每个子节最多保留多少条 bullets
WRITE_MAX_BULLETS_PER_SUBSECTION = 40