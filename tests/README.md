# Tests

Cross-module tests live in this directory. Tests that are tightly coupled to a specific implementation may live next to that implementation, but agent tool and runtime skill tests live here to keep production packages clean.

## Coverage Areas

- Agent tool-call loop and finalization.
- Runtime skill loading and one-turn context activation.
- Business database tool permission filtering.
- Business query guards: date window, rate limit, and Redis fallback behavior.
- MCP service protocol behavior.
- Conversation memory.
- Document conversion, cleaning, chunking, retrieval, and architecture boundaries.

## Run

```powershell
python -m pytest -q
```

For Windows environments where the default pytest temp directory has permission issues:

```powershell
python -m pytest -q --basetemp .pytest_tmp
```

Test data should use examples or temporary files. Real business questions, evaluation outputs, credentials, and connection values should not be committed.

