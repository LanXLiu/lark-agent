"""评估测试集的数据结构与读写。

测试集是 JSONL，一行一条样本。真实测试集含公司数据，**不入库**（放本地
eval_data/，已被 .gitignore 忽略）；仓库里只提供 testset.example.jsonl 示例。

字段：
  question         必填。用户会问的问题。
  ground_truth     必填。人工写的标准答案，用于评「答案正确性」。
  expected_sources 可选。这题应召回到的文档名列表，用于评「召回准不准」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalSample:
    question: str
    ground_truth: str
    expected_sources: list[str] = field(default_factory=list)


def load_testset(path: str | Path) -> list[EvalSample]:
    """读 JSONL 测试集。跳过空行；缺 question/ground_truth 的行报错定位到行号。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"找不到测试集 {p}。请复制 evaluation/testset.example.jsonl 到本地 "
            f"eval_data/testset.jsonl 并填入你自己的问答样本。"
        )
    samples: list[EvalSample] = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        question = obj.get("question")
        ground_truth = obj.get("ground_truth")
        if not question or not ground_truth:
            raise ValueError(f"{p}:{lineno} 缺少 question 或 ground_truth")
        samples.append(
            EvalSample(
                question=question,
                ground_truth=ground_truth,
                expected_sources=list(obj.get("expected_sources") or []),
            )
        )
    if not samples:
        raise ValueError(f"测试集 {p} 是空的")
    return samples
