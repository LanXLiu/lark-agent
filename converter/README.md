# converter — 格式转换器（分发层）

各种文件格式的转换入口。按文件类型分发到对应转换器，产出统一的中间结果，交给 `file_to_markdown` 做真正的 markdown 渲染。

## 文件

| 文件 | 职责 |
|---|---|
| `converter_factory.py` | 按文件类型/后缀选转换器。 |
| `base.py` | 转换器基类 / 统一接口。 |
| `docx_converter.py` | Word。 |
| `pdf_converter.py` | PDF。 |
| `pptx_converter.py` | PowerPoint。 |
| `excel_converter.py` | Excel。 |
| `image_converter.py` | 图片。 |
| `json_converter.py` | JSON。 |

## 说明

本模块负责「按格式分发 + 前处理」，把内容真正渲染成 markdown 的逻辑在 `file_to_markdown/`（含 VLM 识图、表格渲染、后处理）。
