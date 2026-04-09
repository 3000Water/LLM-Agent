# 聚焦版子项目（发展基础）

该子项目用于快速迭代“第一大章节：发展基础”的映射与排他性参数，不跑全量 5 章流程。

## 做了什么

- 仅执行“发展基础”的提取
- 仅执行“发展基础”子章节提取
- 仅聚合“发展基础”并输出预览
- 使用独立缓存目录，避免影响主流程产物

## 运行方式

在项目根目录执行：

```bash
python synthesize_focus/synthesize_focus_dev_base.py
```

如果你只修改了聚合逻辑，想复用已有提取结果：

```bash
python synthesize_focus/synthesize_focus_dev_base.py --skip-extract
```

## 输出文件

- `output/focus_发展基础/intermediate/extracted_发展基础.json`
- `output/focus_发展基础/intermediate/subsection_extracted_发展基础.json`
- `output/focus_发展基础/intermediate/aggregated_发展基础.json`
- `output/focus_发展基础/发展基础_聚合预览.md`

## 说明

- 本脚本直接复用 `synthesize/extractor.py` 的提取逻辑，因此你调整 `config.py` 与 `config_mapping.json`（尤其排他性和小章节映射）后，可立即在聚焦版看到效果。
- 如需扩展到“建设任务”聚焦版，可平移同一脚手架并替换 `FOCUS_SECTION_KEY`。
