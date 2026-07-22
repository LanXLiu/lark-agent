# knowledge/ingestion/file_to_markdown — 转 Markdown 核心

把各类文件内容渲染成 Markdown 的实现层，包含 VLM 识图、表格渲染和后处理，由同级 `converter` 与入库编排调用。

## 文件

| 文件 | 职责 |
|---|---|
| `unified_entry.py` | **统一入口**，按类型分发到下面各 `*_to_markdown`。 |
| `word_to_markdown.py` | Word → md。 |
| `pdf_to_markdown.py` | PDF → md。 |
| `pptx_visual_to_markdown.py` | PPT 视觉版：渲染成图后用 VLM 识别（留空 VLM key 则回退 python-pptx 文本版）。 |
| `image_to_markdown.py` | 图片 → md（OCR / VLM）。 |
| `html_to_markdown.py` / `json_to_markdown.py` | HTML / JSON → md。 |
| `structured_exporters.py` | 结构化导出（表格类）。 |
| `table_renderer.py` | 表格渲染成 markdown。 |
| `markdown_postprocess.py` | 转换后的 markdown 清理/规整。 |
| `vlm_client.py` | 视觉大模型客户端（识图/识表）。 |

## 说明

VLM 相关配置（url / api_key / model）在 `infrastructure/conf/config_local.yaml` 的 `MODELS.VLM` 段；未配置时视觉转换自动回退到纯文本方案。
