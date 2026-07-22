# knowledge/ingestion/cleans — Markdown 清洗

在切片前统一清理 Markdown，减少页眉页脚、目录、页码、重复段落和短噪声对召回质量的影响。

## 主要模块

| 文件 | 职责 |
|---|---|
| `pipeline.py` | 清洗步骤编排与统一入口 |
| `base.py` | 清洗器基础结构 |
| `boilerplate.py` | 模板化正文处理 |
| `header_footer.py` | 页眉页脚处理 |
| `toc.py` / `page_number.py` | 目录和页码处理 |
| `dedup.py` | 重复段落处理 |
| `short_noise.py` / `empty_blocks.py` | 短噪声和空块处理 |
| `closing.py` / `decoration.py` | 结尾与装饰内容处理 |

统一入口：

```python
from knowledge.ingestion.cleans import clean_markdown

result = clean_markdown(markdown_text)
```
