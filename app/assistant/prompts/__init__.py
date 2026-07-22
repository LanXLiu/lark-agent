"""集中管理项目里所有 LLM prompt（纯字符串常量 + 少量纯 format 辅助）。

设计约束：本包**只含字符串常量与纯函数，不 import 任何项目内模块**，
是依赖图的叶子——service.* / file_to_markdown.* 均可安全 import，无循环风险。

- agent：Agent 系统提示、降级联网作答
- qa：答案生成的固定文案（片段拼接逻辑在 app/assistant/qa_service.py）
- memory：对话摘要、flush 抽事实
- vlm：文档转换的视觉模型（VLM）转写提示（PPT / Word 内嵌图）
"""
