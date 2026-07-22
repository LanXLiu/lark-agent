# Knowledge

`knowledge/` contains the knowledge-base pipeline: document ingestion, retrieval, evaluation, and shared knowledge-processing utilities.

The assistant decides when to call retrieval. This package provides the ingestion and retrieval capabilities it can use.

## Modules

| Module | Responsibility |
| --- | --- |
| [`ingestion/`](ingestion/README.md) | Document conversion, cleaning, chunking, ingestion orchestration, and vector writes |
| [`retrieval/`](retrieval/README.md) | Dense + BM25 hybrid recall, RRF fusion, rerank, filters, and parent-child context expansion |
| [`evaluation/`](evaluation/README.md) | Ragas evaluation for answer and retrieval quality |
| [`utils/`](utils/README.md) | Deduplication, hierarchy parsing, payload building, retry helpers, and sparse embedding utilities |

## Data Flow

```text
documents
  -> knowledge/ingestion
  -> MinIO raw / markdown / chunk objects
  -> Qdrant dense and sparse payloads

questions
  -> knowledge/retrieval
  -> RecallResult
  -> app/assistant

test sets
  -> knowledge/evaluation
  -> quality metrics
```

This module does not handle Lark messages and does not decide when to retrieve. Agent routing lives in `app/assistant`.

