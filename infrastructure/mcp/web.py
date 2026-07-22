"""Public web search and page reading operations for the web MCP."""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from infrastructure.mcp.config import required_env_float, required_env_int

def web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")
    api_url = os.getenv("TAVILY_API_URL", "").strip()
    if not api_url:
        raise RuntimeError("TAVILY_API_URL is not configured")
    requested = int(arguments.get("max_results") or 5)
    max_results = max(1, min(requested, required_env_int("WEB_MCP_MAX_RESULTS", maximum=10)))
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced" if arguments.get("search_depth") == "advanced" else "basic",
        "include_answer": True,
        "max_results": max_results,
    }
    response = httpx.post(
        api_url,
        json=payload,
        timeout=required_env_float("WEB_MCP_TIMEOUT_SECONDS"),
    )
    response.raise_for_status()
    data = response.json()
    results = [
        {
            "title": str(item.get("title") or ""),
            "url": str(item.get("url") or ""),
            "content": str(item.get("content") or "")[:1200],
            "score": item.get("score"),
        }
        for item in (data.get("results") or [])[:max_results]
    ]
    structured = {"answer": data.get("answer") or "", "results": results}
    blocks = [str(structured["answer"])] if structured["answer"] else []
    blocks.extend(f"[{item['title']}]({item['url']})\n{item['content']}" for item in results)
    return {"text": "\n\n".join(blocks) or "No relevant public web results found.", "structured_content": structured}


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http/https URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not supported")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("URL hostname cannot be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private, loopback, and local network URLs are not allowed")


def web_fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    timeout = required_env_float("WEB_MCP_TIMEOUT_SECONDS")
    max_chars = required_env_int("WEB_MCP_FETCH_MAX_CHARS", maximum=50000)
    current_url = url
    response: httpx.Response | None = None
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(4):
            _validate_public_url(current_url)
            response = client.get(current_url, headers={"User-Agent": "lark-agent-web-mcp/0.1"})
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            break
        else:
            raise RuntimeError("Too many redirects")
    if response is None or response.is_redirect:
        raise RuntimeError("Unable to resolve webpage redirect")
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise ValueError(f"Unsupported webpage content type: {content_type or 'unknown'}")
    if "text/html" in content_type:
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    else:
        title = ""
        text = response.text
    text = text[:max_chars]
    structured = {"url": str(response.url), "title": title, "content": text}
    return {"text": f"{title}\n{text}".strip(), "structured_content": structured}
