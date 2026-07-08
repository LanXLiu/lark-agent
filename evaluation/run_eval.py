"""RAG 评估跑批入口。

流程：读本地测试集 → 逐条调用 service.qa_service 拿到「答案 + 检索片段 + 来源」
→ 用 Ragas（百炼当裁判）算答案/召回质量指标，另加一个纯代码的「来源命中率」
→ 打印汇总 + 把逐条明细写到本地 eval_results/（含真实答案，不入库）。

用法：
  # 测试集默认读 eval_data/testset.jsonl（本地，不入库），可用 --testset 指定
  python -m evaluation.run_eval
  python -m evaluation.run_eval --testset eval_data/testset.jsonl --collection knowledgebase

依赖：pip install -r requirements-eval.txt
需要 .env 里配好 BAILIAN_API_KEY 等（同机器人运行所需的配置）。
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from evaluation.datamodel import EvalSample, load_testset


def _build_qa_service(collection: str):
    """按机器人同样的方式构造问答服务（复用 service 层，评的就是线上那套 Agent 工具调用）。"""
    from service.llm_client import BailianChatClient
    from service.agent.graph import AgentService
    from recall.hybrid_recall import HybridRecaller

    llm = BailianChatClient(
        api_key=os.environ["BAILIAN_API_KEY"],
        base_url=os.getenv("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model=os.getenv("BAILIAN_MODEL", "deepseek-v4-pro"),
        timeout_seconds=float(os.getenv("BAILIAN_TIMEOUT_SECONDS", "60")),
    )
    # 评测按单轮跑（answer 不传历史）。评测环境默认关闭降级联网，只评知识库检索质量，
    # 与线上 Agent 工具调用一致（LLM 自主调 search_knowledge、分数阈值兜底）。
    return AgentService(
        llm_client=llm,
        recaller=HybridRecaller(),
        collections=collection,
        top_k=int(os.getenv("RAG_TOP_K", "5")),
        enable_rerank=os.getenv("RAG_ENABLE_RERANK", "true").lower() in {"1", "true", "yes"},
        candidate_top_k=int(os.getenv("RAG_CANDIDATE_TOP_K", "50")),
        max_tool_rounds=max(1, int(os.getenv("RAG_MAX_TOOL_ROUNDS", "4"))),
        recall_quality_min=float(os.getenv("RAG_RECALL_QUALITY_MIN", "0.68")),
        enable_web_search=False,
    )


def _source_hit(expected_sources: list[str], hit_filenames: list[str]) -> float | None:
    """来源命中率（纯代码，不花钱）：期望文档里有多少被实际召回到。

    没标 expected_sources 的样本返回 None（不参与该指标平均）。
    做包含匹配（大小写不敏感），容忍文件名带路径/后缀差异。
    """
    if not expected_sources:
        return None
    got = [f.lower() for f in hit_filenames if f]
    hit = 0
    for exp in expected_sources:
        e = exp.lower().strip()
        if any(e in g or g in e for g in got):
            hit += 1
    return hit / len(expected_sources)


def run(testset_path: str, collection: str, out_dir: str) -> None:
    load_dotenv()
    samples: list[EvalSample] = load_testset(testset_path)
    print(f"[eval] 测试集 {testset_path}：{len(samples)} 条")

    qa = _build_qa_service(collection)

    # 逐条跑问答，收集 Ragas 需要的字段 + 来源命中
    questions: list[str] = []
    answers: list[str] = []
    contexts: list[list[str]] = []
    ground_truths: list[str] = []
    source_hits: list[float | None] = []
    per_sample: list[dict] = []

    for i, s in enumerate(samples, start=1):
        result = qa.answer(s.question)
        ctx = [h.content for h in result.hits]
        filenames = [h.filename for h in result.hits]
        sh = _source_hit(s.expected_sources, filenames)

        questions.append(s.question)
        answers.append(result.answer or "")
        contexts.append(ctx or ["（无检索片段）"])
        ground_truths.append(s.ground_truth)
        source_hits.append(sh)
        per_sample.append(
            {
                "question": s.question,
                "answer": result.answer,
                "ground_truth": s.ground_truth,
                "expected_sources": s.expected_sources,
                "recalled_sources": filenames,
                "source_hit": sh,
                "no_answer": getattr(result, "no_answer", False),
            }
        )
        print(f"[eval] ({i}/{len(samples)}) 已问答：{s.question[:30]}")

    # Ragas 评估（延迟 import，让不装 ragas 的人也能看代码）
    print("[eval] 调用 Ragas 计算指标（这一步会多次调用大模型，稍慢）……")
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        answer_correctness,
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    from evaluation.ragas_setup import build_judge_embeddings, build_judge_llm

    dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        }
    )
    ragas_result = evaluate(
        dataset,
        metrics=[
            faithfulness,        # 答案是否忠于检索片段（防幻觉）
            answer_relevancy,    # 答案是否切题
            answer_correctness,  # 答案对不对（对比 ground_truth）
            context_precision,   # 召回片段是否精准
            context_recall,      # 召回是否覆盖了标准答案所需信息
        ],
        llm=build_judge_llm(),
        embeddings=build_judge_embeddings(),
    )

    # 汇总
    scores = ragas_result.to_pandas().mean(numeric_only=True).to_dict()
    graded = [h for h in source_hits if h is not None]
    if graded:
        scores["source_hit_rate"] = sum(graded) / len(graded)

    print("\n========== 评估结果（均值）==========")
    for k, v in scores.items():
        print(f"  {k:20s}: {v:.4f}")
    print("=====================================")

    # 明细落盘（含真实答案，写到 gitignore 的本地目录）
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / "details.jsonl").open("w", encoding="utf-8") as fp:
        for row in per_sample:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[eval] 明细已写入 {out}/（details.jsonl + summary.json）")


def main() -> None:
    ap = argparse.ArgumentParser(description="RAG 评估（Ragas + 百炼裁判）")
    ap.add_argument(
        "--testset",
        default=os.getenv("EVAL_TESTSET", "eval_data/testset.jsonl"),
        help="测试集 JSONL 路径（默认 eval_data/testset.jsonl，本地不入库）",
    )
    ap.add_argument(
        "--collection",
        default=os.getenv("RAG_COLLECTION", os.getenv("QDRANT_COLLECTION", "knowledgebase")),
        help="要评估的 Qdrant collection",
    )
    ap.add_argument(
        "--out",
        default=os.getenv("EVAL_OUT_DIR", "eval_results"),
        help="结果输出目录（默认 eval_results/，本地不入库）",
    )
    args = ap.parse_args()
    run(args.testset, args.collection, args.out)


if __name__ == "__main__":
    main()
