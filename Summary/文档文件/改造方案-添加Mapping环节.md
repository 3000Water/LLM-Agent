# 十四五规划项目 - Mapping 环节改造方案

> 基于旧项目框架 + full_mapping_relationships.csv 实现小章节细节汇总

---

## 📋 问题诊断

当前状态：
- ✅ config.py 有 5 个大章节 (SECTIONS)
- ❌ **小章节缺少细节描述**：发展基础 11 个子章节、建设任务 10 个子章节
- ✅ full_mapping_relationships.csv 已有粒度到小章节的源文件映射关系

关键缺失：**中间层的数据结构** → 无法让 LLM 的提取/撰写 Prompt 感知小章节

---

## 🔧 改造方案概览

```
【旧流程】
部处文档（Markdown）
    ↓
提取（EXTRACT） → 大章节分类
    ↓
聚合（AGGREGATE） → 按大章节拼接
    ↓
撰写（WRITE） → 生成大章节正文
    ↓
输出汇总文档

【新流程】加入 Mapping 环节
部处文档（Markdown）
    ↓
提取（EXTRACT） → 按小章节映射分类
    ↓
[NEW] Mapping 聚合（AGGREGATE_WITH_MAPPING）→ 按小章节汇聚源内容
    ↓
撰写（WRITE） → 按小章节生成正文
    ↓
输出汇总文档
```

---

## 💾 第一步：生成 mapping 配置文件

### 1.1 从 CSV 解析小章节

**目标**：从 full_mapping_relationships.csv 中提取结构化信息

**新增文件**：`config_mapping.json`

```json
{
  "sections": [
    {
      "section_id": 1,
      "section_key": "development_foundation",
      "section_title": "发展基础",
      "subsections": [
        {
          "index": 1,
          "title": "持续深化理论武装，党的全面领导不断加强",
          "key": "party_leadership",
          "sources": [
            {
              "file": "党委统战部十四五规划.md",
              "weight": 0.85,
              "description": "党的全面领导、思想政治工作"
            },
            {
              "file": "纪委\"十四五\"规划.md",
              "weight": 0.15,
              "description": "党风廉政建设、监督职能"
            }
          ]
        },
        {
          "index": 2,
          "title": "落实立德树人根本任务，人才培养成效显著",
          "key": "talent_cultivation",
          "sources": [
            {
              "file": "本科人才培养\"十四五\"发展规划-本科生院.md",
              "weight": 0.75,
              "description": "一流本科专业建设、教学质量"
            },
            {
              "file": "研究生院十四五规划.md",
              "weight": 0.25,
              "description": "博士培养体系、学位点建设"
            }
          ]
        },
        // ... 其余 9 个子章节
      ]
    },
    {
      "section_id": 4,
      "section_key": "construction_tasks",
      "section_title": "建设任务",
      "subsections": [
        {
          "index": 1,
          "title": "构建人才培养新体系",
          "key": "task_talent_system",
          "sources": [
            {
              "file": "本科人才培养\"十四五\"发展规划-本科生院.md",
              "weight": 0.7,
              "description": "本科培养体系改革"
            },
            {
              "file": "研究生院十四五规划.md",
              "weight": 0.2,
              "description": "研究生培养体系改革"
            }
          ]
        },
        // ... 其余 9 个小类
      ]
    }
  ]
}
```

**生成方式**：
1. 解析 CSV 文件
2. 按大章节 + 子标题聚合
3. 从映射关系提取 sources 和 weight
4. 输出为 JSON

---

## 🎯 第二步：改造提取阶段 (Extraction)

### 2.1 改造提取 Prompt

**关键改动**：从"按大章节分类"改为"**按小章节映射分类**"

```python
# 旧 Prompt（985211）
EXTRACT_SYSTEM = """
请将内容按以下9个工作维度进行提取：
1. 主题教育
2. 一流学科培优
...
"""

# 新 Prompt（十四五 + Mapping）
EXTRACT_SYSTEM = """
请按照【南京大学"十四五"规划】的【小章节映射结构】进行提取。

【发展基础 - 11 个子章节】：
- (一) 党的全面领导加强 → 来源：党委统战部、纪委
- (二) 人才培养成效 → 来源：本科生院、研究生院
- ...

【建设任务 - 10 个小类】：
- (一) 人才培养新体系 → 来源：本科/研究生院
- (二) 队伍建设新机制 → 来源：人力资源处
- ...

【提取要求】：
1. 对每个小章节，提取对应源文件中的相关内容
2. 在 JSON 中以"小章节 key"作为分组单位
3. 标注每条内容来自哪个小章节
"""

# JSON 输出结构示例（对标 config_mapping.json）
{
  "development_foundation": {
    "party_leadership": [
      {
        "content": "强化党的全面领导...",
        "source_file": "党委统战部十四五规划.md",
        "relevance": 0.9
      }
    ],
    "talent_cultivation": [
      {
        "content": "建设一流本科专业...",
        "source_file": "本科人才培养...md",
        "relevance": 0.95
      }
    ]
  },
  "construction_tasks": {
    "task_talent_system": [...]
  }
}
```

### 2.2 改造 extractor.py

```python
# 伪代码
class Extractor:
    def __init__(self, config_mapping_path):
        self.mapping = load_json(config_mapping_path)  # 加载小章节映射
        
    def extract(self, doc_text, dept_title):
        """
        基于小章节映射提取内容
        """
        # 1. 识别这份文档对应 mapping 中的哪些小章节
        relevant_subsections = self._match_subsections(dept_title)
        
        # 2. 对每个小章节，用对应的 Prompt 提取
        result = {}
        for section in self.mapping['sections']:
            for subsection in section['subsections']:
                prompt = self._build_extract_prompt(
                    subsection_title=subsection['title'],
                    subsection_key=subsection['key'],
                    expected_sources=subsection['sources']
                )
                extracted = llm_call(prompt, doc_text)
                result[subsection['key']] = extracted
        
        return result
```

---

## 🔀 第三步：改造聚合阶段 (Aggregation)

### 3.1 新增聚合器：MappingAggregator

```python
class MappingAggregator:
    """
    基于小章节映射的内容聚合器
    """
    def __init__(self, config_mapping_path):
        self.mapping = load_json(config_mapping_path)
    
    def aggregate_subsection(self, subsection_key, all_extracted_contents):
        """
        聚合单个小章节的所有源内容
        
        subsection_key: 如 "party_leadership"
        all_extracted_contents: {dept_name: {subsection_key: [...]}}
        
        返回：该小章节的汇聚内容 + 源信息
        """
        aggregated = []
        source_map = {}
        
        for dept_name, dept_extracts in all_extracted_contents.items():
            if subsection_key in dept_extracts:
                for item in dept_extracts[subsection_key]:
                    aggregated.append(item)
                    source_map[dept_name] = source_map.get(dept_name, 0) + 1
        
        return {
            "key": subsection_key,
            "contents": aggregated,
            "source_distribution": source_map,
            "total_items": len(aggregated)
        }
    
    def aggregate_section(self, section_key, all_extracted_contents):
        """
        聚合整个大章节（所有小章节）
        """
        section = self._find_section(section_key)
        aggregated_subsections = {}
        
        for subsection in section['subsections']:
            aggregated_subsections[subsection['key']] = \
                self.aggregate_subsection(subsection['key'], all_extracted_contents)
        
        return aggregated_subsections
```

**中间产物** → `aggregated_by_mapping.json`

```json
{
  "development_foundation": {
    "party_leadership": {
      "key": "party_leadership",
      "contents": [
        {
          "text": "强化党的全面领导...",
          "source_file": "党委统战部...",
          "relevance": 0.9
        }
      ],
      "source_distribution": {
        "党委统战部": 3,
        "纪委": 1
      }
    },
    "talent_cultivation": {...}
  }
}
```

---

## ✍️ 第四步：改造撰写阶段 (Writing)

### 4.1 改造撰写 Prompt

**关键差异**：从"整个大章节一次性生成"改为"**逐小章节生成，然后拼接**"

```python
WRITE_SUBSECTION = Template("""\
【任务】生成"$section_title"中"$subsection_title"部分的内容

【背景信息】：
- 出现位置：$section_title 的第 $subsection_index 个要点
- 相关部门：$source_departments
- 内容来源：聚合自 $source_count 个部门规划

【要点提炼】：
$aggregated_bullets

【要求】：
1. 文风保持与其他小章节一致（部门级抽象层次）
2. 字数目标：$target_words 字
3. 不涉及执行细节（如具体会议时间）
4. 整合多个源信息时只提一次相同事项
5. 突出南大特色和规划新意

【输出】：
直接输出段落文本，不包含标题。
\""")
```

### 4.2 改造 writer.py

```python
class Writer:
    def __init__(self, config_mapping_path):
        self.mapping = load_json(config_mapping_path)
    
    def write_subsection(self, section_key, subsection_key, aggregated_data):
        """
        生成单个小章节的正文
        """
        section = self._find_section(section_key)
        subsection = self._find_subsection(section, subsection_key)
        
        # 计算此小章节的目标字数
        # （大章节总字数 / 小章节数）
        total_word_range = section['word_range']
        target_words = (total_word_range[0] + total_word_range[1]) / 2 / len(section['subsections'])
        
        prompt = WRITE_SUBSECTION.substitute(
            section_title=section['title'],
            subsection_title=subsection['title'],
            subsection_index=subsection['index'],
            source_departments=", ".join([s['file'] for s in subsection['sources']]),
            source_count=len(subsection['sources']),
            aggregated_bullets=self._format_bullets(aggregated_data['contents']),
            target_words=int(target_words)
        )
        
        text = llm_call(prompt, temperature=0.6)
        return {
            "subsection_key": subsection_key,
            "text": text,
            "word_count": len(text)
        }
    
    def write_section(self, section_key, all_subsection_results):
        """
        将所有小章节的正文拼接为大章节
        """
        section = self._find_section(section_key)
        
        # 小章节按映射顺序拼接
        subsection_texts = []
        for subsection in section['subsections']:
            result = all_subsection_results.get(subsection['key'])
            if result:
                subsection_texts.append(result['text'])
        
        # 根据 config.SECTION_HEADING_STYLE 确定标题格式
        heading = self._format_heading(section['title'])
        
        return heading + "\n" + "\n".join(subsection_texts)
```

---

## 🔄 第五步：集成到主流程

### 5.1 改造 synthesize_summary.py

```python
# 新的主流程
def synthesize_with_mapping(config_path, config_mapping_path, input_dir, output_path):
    """
    基于 Mapping 的合成流程
    """
    
    # 1. 加载配置
    config = load_config(config_path)
    mapping = load_config(config_mapping_path)
    
    # 2. 扫描所有部处文档
    dept_docs = scan_directory(input_dir)
    
    # ━━━ 第一阶段：提取 ━━━
    extractor = Extractor(config_mapping_path)
    all_extracts = {}
    
    for dept_name, doc_path in dept_docs.items():
        print(f"提取：{dept_name}")
        doc_text = read_file(doc_path)
        extracts = extractor.extract(doc_text, dept_name)
        all_extracts[dept_name] = extracts
        
        # 保存中间产物用于调试
        save_json(f"debug/extracts_{dept_name}.json", extracts)
    
    # ━━━ 第二阶段：聚合（加入 Mapping） ━━━
    aggregator = MappingAggregator(config_mapping_path)
    aggregated_by_mapping = {}
    
    for section in mapping['sections']:
        section_key = section['section_key']
        print(f"聚合：{section['section_title']}")
        
        aggregated_by_mapping[section_key] = \
            aggregator.aggregate_section(section_key, all_extracts)
        
        # 保存中间产物
        save_json(f"debug/aggregated_{section_key}.json", 
                  aggregated_by_mapping[section_key])
    
    # ━━━ 第三阶段：撰写 ━━━
    writer = Writer(config_mapping_path)
    output_sections = []
    
    for section in mapping['sections']:
        section_key = section['section_key']
        print(f"撰写：{section['section_title']}")
        
        # 逐小章节生成
        subsection_results = {}
        for subsection_agg_data in aggregated_by_mapping[section_key].values():
            result = writer.write_subsection(
                section_key,
                subsection_agg_data['key'],
                subsection_agg_data
            )
            subsection_results[subsection_agg_data['key']] = result
        
        # 拼接成整个大章节
        section_text = writer.write_section(section_key, subsection_results)
        output_sections.append(section_text)
    
    # ━━━ 第四阶段：组装输出 ━━━
    final_output = "\n\n".join(output_sections)
    save_file(output_path, final_output)
    print(f"✅ 完成：{output_path}")
```

---

## 📊 数据流图

```
部处文档 × N
    ↓
【Extraction 阶段】
Extractor.extract()
    ↓ 按小章节 key 分类
    ↓
extracts JSONs（每个部处文档 → 小章节内容映射）
    ↓ [保存 debug/]
    ↓
【Aggregation 阶段】 🔴 NEW
MappingAggregator.aggregate_section()
    ↓ 按小章节汇聚
    ↓
aggregated_by_mapping.json（大章节 → 小章节 → 汇聚内容）
    ↓ [保存 debug/]
    ↓
【Writing 阶段】
Writer.write_subsection() ← 逐小章节生成
    ↓
Writer.write_section() ← 拼接小章节
    ↓
output_sections = [section1, section2, ...]
    ↓
【Assembly 阶段】
最终输出汇总文档
```

---

## 🛠️ 实施清单

| 步骤 | 文件 | 优先级 | 预计工作量 |
|-----|------|--------|---------|
| 1 | 创建 `config_mapping.json`（从 CSV 解析） | 🔴 高 | 1h |
| 2 | 创建 `mapping_aggregator.py` | 🔴 高 | 1h |
| 3 | 改造 `extractor.py` Prompt | 🔴 高 | 1h |
| 4 | 改造 `writer.py`（小章节逐生成） | 🔴 高 | 1.5h |
| 5 | 改造 `synthesize_summary.py` 主流程 | 🔴 高 | 1h |
| 6 | 调试 + 测试（单个部处文档） | 🟡 中 | 1h |
| 7 | 全量运行 + 质量检查 | 🟡 中 | 1h |

**总计**：约 7-8 小时

---

## 💡 关键设计决策

| 决策 | 理由 |
|-----|-----|
| **Mapping 层单独文件** | 与 config.py 解耦，便于调整小章节映射关系 |
| **逐小章节生成文本** | 每个小章节独立控制字数，防止某个大章节畸形膨胀；便于单独重跑 |
| **Weight 字段** | 指导 LLM 在聚合多源时识别主次关系（85% vs 15%） |
| **保存 debug/ 中间产物** | 出现偏差时快速定位（是提取问题还是聚合问题还是撰写问题） |
| **Subsection index + title** | 便于 Prompt 中说"第X个要点"，与原规划文档的顺序保持一致 |

---

## ✅ 验收标准

1. ✓ `config_mapping.json` 包含所有 5 个大章节 + 21 个小章节的映射
2. ✓ 提取阶段能按小章节 key 输出 JSON
3. ✓ 聚合阶段生成 `aggregated_by_mapping.json`
4. ✓ 撰写阶段逐小章节生成，拼接后总字数在预期范围内
5. ✓ 最终输出的 5 个大章节各部分结构清晰、内容连贯
6. ✓ 中间产物便于人工审查和调试

