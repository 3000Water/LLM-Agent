# Mapping 环节快速实施指南

> 如何在现有项目基础上添加 Mapping 环节并使其工作

---

## 📋 快速检查清单

在开始之前，请确认您已有：

- ✅ `full_mapping_relationships.csv` 已生成（粒度到小章节的映射表）
- ✅ 现有的 `extractor.py`、`writer.py` 等基础模块
- ✅ Node/Python 环境以及 LLM API 密钥（如 DeepSeek）

---

## 🚀 分步实施

### 第一步：生成 `config_mapping.json`

**目标**：从 CSV 映射表生成结构化的 mapping 配置

**操作**：

```bash
# 1. 检查 mapping_manager.py 已在 synthesize 目录
ls synthesize/mapping_manager.py

# 2. 运行以生成 config_mapping.json
cd synthesize
python mapping_manager.py

# 输出：config/config_mapping.json
```

**验证**：

```bash
# 查看生成的文件结构
cat config/config_mapping.json | head -50

# 应该看到类似这样的结构：
# {
#   "sections": [
#     {
#       "section_id": 1,
#       "section_key": "development_foundation",
#       "section_title": "发展基础",
#       "subsections": [
#         {
#           "index": 1,
#           "title": "持续深化理论武装，党的全面领导不断加强",
#           "key": "subsection_abc123",
#           "sources": [
#             {
#               "file": "党委统战部十四五规划.md",
#               "weight": 0.85
#             }
#           ]
#         }
#       ]
#     }
#   ]
# }
```

---

### 第二步：改造 `extractor.py`

**目标**：让提取器按小章节映射分类内容（而不是按大章节）

**关键改动**：

```python
# extractor.py 中的改造

from prompts_mapping import (
    EXTRACT_SYSTEM,
    build_extract_prompt,
    gen_mapping_instructions
)
from mapping_manager import load_config_mapping

class Extractor:
    def __init__(self, config_mapping_path: str, llm_client):
        self.mapping = load_config_mapping(config_mapping_path)
        self.llm_client = llm_client
    
    def extract(self, doc_text: str, dept_name: str) -> Dict:
        """
        按小章节映射提取
        
        返回 JSON 格式：
        {
          "development_foundation": {
            "subsection_key_1": [...],
            "subsection_key_2": [...]
          },
          "construction_tasks": {...}
        }
        """
        # 构建提示词（包含小章节映射信息）
        prompt = build_extract_prompt(
            dept_title=dept_name,
            document_text=doc_text,
            config_mapping=self.mapping
        )
        
        # 调用 LLM
        response = self.llm_client.call(
            system_prompt=EXTRACT_SYSTEM,
            user_prompt=prompt,
            temperature=0.2  # 低温，减少分类发散
        )
        
        # 解析 JSON
        extracted = json.loads(response)
        return extracted
```

**改造步骤**：

1. 在 `extractor.py` 头部导入新模块：
   ```python
   from prompts_mapping import EXTRACT_SYSTEM, build_extract_prompt
   from mapping_manager import load_config_mapping
   ```

2. 改造 `__init__` 方法加载 mapping：
   ```python
   def __init__(self, config_mapping_path, llm_client):
       self.mapping = load_config_mapping(config_mapping_path)
       # ... 其他初始化
   ```

3. 改造 `extract` 方法的 prompt 构建部分（见上面代码）

---

### 第三步：集成 `mapping_aggregator.py`

**目标**：在提取和撰写之间加入聚合层

**操作**：

```python
# 在 synthesize_summary.py（主流程）中

from mapping_aggregator import MappingAggregator, save_aggregated_results

# 第一阶段：提取所有文档
all_extracts = {}
for dept_name, doc_path in documents:
    extracts = extractor.extract(doc_text, dept_name)
    all_extracts[dept_name] = extracts

# ✨ 第二阶段：聚合（NEW）
aggregator = MappingAggregator("config/config_mapping.json")
aggregated_all = aggregator.aggregate_all_sections(all_extracts)

# 保存中间产物用于调试
save_aggregated_results(aggregated_all, "debug/aggregated_all.json")

# 现在 aggregated_all 的结构是：
# {
#   "sections": {
#     "development_foundation": {
#       "section_key": "development_foundation",
#       "section_title": "发展基础",
#       "subsections": {
#         "subsection_key_1": {
#           "contents": [...],  ← 已聚合的多源内容
#           "source_distribution": {...}
#         }
#       }
#     }
#   }
# }
```

---

### 第四步：改造 `writer.py`

**目标**：让撰写器按小章节逐个生成文本

**关键改动**：

```python
# writer.py 中的改造

from prompts_mapping import (
    WRITE_SYSTEM,
    build_write_prompt
)

class Writer:
    def __init__(self, config_mapping_path: str, llm_client):
        self.mapping = load_config_mapping(config_mapping_path)
        self.llm_client = llm_client
    
    def write_subsection(
        self,
        section: Dict,
        subsection: Dict,
        aggregated_subsection: Dict,
        target_words: int
    ) -> str:
        """
        为单个小章节生成文本
        """
        # 构建提示词
        prompt = build_write_prompt(
            section=section,
            subsection=subsection,
            aggregated_subsection=aggregated_subsection,
            config_mapping=self.mapping,
            target_words=target_words
        )
        
        # 调用 LLM
        text = self.llm_client.call(
            system_prompt=WRITE_SYSTEM,
            user_prompt=prompt,
            temperature=0.6  # 稍高温度，文风更自然
        )
        
        return text
    
    def write_section(
        self,
        section: Dict,
        aggregated_section: Dict
    ) -> str:
        """
        为整个大章节生成文本（拼接所有小章节）
        """
        subsection_texts = []
        
        # 计算每个小章节的目标字数
        word_range = section.get('word_range', [800, 1200])
        avg_words = (word_range[0] + word_range[1]) / 2
        words_per_subsection = avg_words / len(section['subsections'])
        
        # 逐小章节生成
        for subsection in section['subsections']:
            ss_key = subsection['key']
            ss_agg = aggregated_section['subsections'].get(ss_key)
            
            if not ss_agg or not ss_agg['contents']:
                continue  # 跳过无内容的小章节
            
            text = self.write_subsection(
                section,
                subsection,
                ss_agg,
                int(words_per_subsection)
            )
            
            subsection_texts.append(text)
        
        # 拼接
        heading = f"## {section['section_title']}"
        return heading + "\n\n" + "\n\n".join(subsection_texts)
```

**改造步骤**：

1. 添加 mapping 相关导入
2. 在 `__init__` 中加载 mapping 配置
3. 添加 `write_subsection` 方法用于生成单个小章节
4. 改造 `write_section` 方法为逐小章节的调用，而非整节一次性生成

---

### 第五步：改造主流程 `synthesize_summary.py`

**目标**：将五个阶段串联起来

**核心改动**：

```python
# synthesize_summary.py（改造后的主流程框架）

from extractor import Extractor
from writer import Writer
from mapping_aggregator import MappingAggregator
from mapping_manager import load_config_mapping

def main():
    # 阶段一：提取
    print("【阶段一】提取...")
    all_extracts = {}
    for doc_path in documents:
        extracts = extractor.extract(read_file(doc_path), dept_name)
        all_extracts[dept_name] = extracts
    
    # 阶段二：聚合（新增）
    print("【阶段二】聚合...")
    aggregator = MappingAggregator(config_mapping_path)
    aggregated_all = aggregator.aggregate_all_sections(all_extracts)
    
    # 阶段三：撰写小章节
    print("【阶段三】撰写...")
    all_section_texts = {}
    mapping = load_config_mapping(config_mapping_path)
    
    for section in mapping['sections']:
        section_key = section['section_key']
        agg_section = aggregated_all['sections'][section_key]
        
        section_text = writer.write_section(section, agg_section)
        all_section_texts[section_key] = section_text
    
    # 阶段四：组装
    print("【阶段四】组装...")
    final_output = "\n\n".join(all_section_texts.values())
    
    # 保存
    print("【阶段五】保存...")
    with open(output_path, 'w') as f:
        f.write(final_output)
    
    print("✅ 完成！")
```

---

## 🧪 测试验证

### 测试 1：验证 config_mapping.json 完整性

```bash
python -c "
import json
with open('config/config_mapping.json') as f:
    config = json.load(f)
    for s in config['sections']:
        print(f'{s[\"section_title\"]}: {len(s[\"subsections\"])} 个小章节')
"

# 预期输出：
# 发展基础: 11 个小章节
# 发展环境: (某个数)
# 指导方针和主要目标: (某个数)
# 建设任务: 10 个小章节
# 组织与保障: (某个数)
```

### 测试 2：验证提取逻辑

```bash
python -c "
from synthesize.mapping_manager import load_config_mapping
from synthesize.prompts_mapping import gen_mapping_instructions

mapping = load_config_mapping('config/config_mapping.json')
instr = gen_mapping_instructions(mapping, 'development_foundation')
print(instr[:500])  # 打印前 500 字符
"
```

### 测试 3：运行完整流程演示

```bash
# 运行改造后的主流程（演示模式，不调用真实 LLM）
python synthesize/synthesize_with_mapping.py
```

---

## 🐛 常见问题排查

| 问题 | 原因 | 解决 |
|-----|------|------|
| `config_mapping.json` 不存在 | 尚未运行 `mapping_manager.py` | 执行：`python synthesize/mapping_manager.py` |
| 提取 JSON 格式错误 | Extractor 的 Prompt 需要调整 | 检查 `prompts_mapping.EXTRACT_USER` 与 LLM 的兼容性 |
| 小章节字数过多 | 撰写阶段的约束不够严格 | 在 `build_write_prompt` 中强化"目标字数"的表述 |
| 内容出现越界（涉及其他章节） | 没有提供完整的"其他章节"背景信息 | 调用 `gen_other_sections_summary` 补充上下文 |
| 多源内容出现重复 | 聚合时未做去重 | 在 Prompt 中明确要求"相似内容只保留一次" |

---

## 📊 质量检查点

完成后，请检查以下指标：

✅ **聚合完整性**
- 每个小章节都应有对应的聚合内容
- 所有部处文档都被至少一个小章节引用

✅ **字数均衡**
- 各大章节字数在配置的 `word_range` 内（±15% 容差）
- 大章节内的小章节字数分布相对均匀

✅ **内容质量**
- 无相邻段落重复或冗余
- 无"执行细节"（具体日期、会议名称）
- 包含具体数据、奖项、排名等核心指标

✅ **结构完整**
- 5 个大章节都有输出
- 21 个小章节都有文本（无空章节）

---

## 💡 进阶优化

完成基础集成后，可考虑：

1. **权重学习**：根据第一次运行的字数分布，调整 `subsection_index` 中的权重

2. **质量评分**：为每个生成的小章节添加自动评分，识别可能需要重写的部分

3. **增量更新**：仅重新处理变更的部处文档，而不是全量重新生成

4. **版本控制**：保存每次生成的中间产物，便于对比和追溯

---

## 📞 获取帮助

如果遇到问题，请检查：

1. `debug/` 目录中的中间产物（JSON 文件）
2. LLM API 调用日志
3. Prompt 与实际 LLM 模型的兼容性

祝您集成顺利！✨

