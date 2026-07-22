"""API-key guard shared by the two MCP ASGI applications."""

from __future__ import annotations

import os
from typing import Any

from starlette.responses import JSONResponse


class ApiKeyGuard:
    """Validate Bearer or X-API-Key headers without altering MCP transport internals."""

    def __init__(self, app: Any, api_key_env: str) -> None:
        self.app = app
        self.api_key_env = api_key_env

    async def __call__(self, scope, receive, send) -> None:
        expected = os.getenv(self.api_key_env, "").strip()
        if expected and scope["type"] == "http" and scope.get("path", "").rstrip("/").endswith("/mcp"):
            headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
            authorization = headers.get("authorization", "")
            bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
            supplied = headers.get("x-api-key", "") or bearer
            if supplied != expected:
                response = JSONResponse({"detail": "Invalid MCP API key"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
