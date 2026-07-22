# RAG 评估

用 [Ragas](https://docs.ragas.io/) 评估问答质量，裁判模型用百炼（DashScope）。
评估运行线上同一套 agent助手问答（`app.assistant.agent`），覆盖实际召回和生成；评测时关闭联网补充，只评知识库检索质量。

## 数据放哪里

评估需要一份真实问答测试集。为便于版本管理，仓库把「示例」和「你自己的数据」分开：

- 仓库自带 `knowledge/evaluation/testset.example.jsonl`：几条示范格式的样例，照着它写；
- 你自己的测试集放本地 `eval_data/testset.jsonl`（`.gitignore` 已忽略该目录，方便你放业务问答而不必提交）；
- 评估结果输出到本地 `eval_results/`（同样已忽略）。

按下面「准备测试集」把示例复制成你自己的一份，即可跑通。

## 准备测试集

复制示例，改成你自己的问答：

```bash
mkdir -p eval_data
cp knowledge/evaluation/testset.example.jsonl eval_data/testset.jsonl
# 然后编辑 eval_data/testset.jsonl
```

每行一条 JSON：

| 字段 | 必填 | 说明 |
|---|---|---|
| `question` | ✅ | 用户会问的问题（建议从飞书历史提问里挑真实问题） |
| `ground_truth` | ✅ | 人工写的标准答案 |
| `expected_sources` | ⬜ | 这题应召回到的文档名列表，用于评「召回准不准」 |

```jsonl
{"question": "报销流程怎么走", "ground_truth": "先提单...", "expected_sources": ["财务制度"]}
```

## 运行

```bash
pip install -r requirements-eval.txt      # 只需装一次（ragas 等评估依赖）
python -m knowledge.evaluation.run_eval             # 默认读 eval_data/testset.jsonl
# 或指定：
python -m knowledge.evaluation.run_eval --testset eval_data/testset.jsonl --collection knowledgebase
```

需要 `.env` 里配好 `BAILIAN_API_KEY` 等（和跑机器人所需的配置一致）。

## 指标含义

| 指标 | 判什么 | 需要 ground_truth |
|---|---|---|
| `faithfulness` | 答案是否忠于检索片段（防幻觉） | 否 |
| `answer_relevancy` | 答案是否切题 | 否 |
| `answer_correctness` | 答案对不对（对比标准答案） | 是 |
| `context_precision` | 召回片段是否精准 | 是 |
| `context_recall` | 召回是否覆盖标准答案所需信息 | 是 |
| `source_hit_rate` | 期望文档有多少被实际召回（纯代码，不花钱） | 需 expected_sources |

> Ragas 指标每条样本会多次调用大模型，比较费 token。测试集大时留意用量。
