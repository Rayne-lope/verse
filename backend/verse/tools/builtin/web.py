from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Any

from verse.persistence.keychain import get_api_key

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def open_url(url: str) -> str:
    target = url.strip()
    if not target:
        raise ValueError("url cannot be empty")
    if "://" not in target:
        target = f"https://{target}"
    subprocess.run(["open", target], check=True)
    return f"Opened {target}."


def web_search(query: str, count: int = 3) -> str:
    api_key = os.getenv("BRAVE_API_KEY") or get_api_key("brave")
    if not api_key:
        raise RuntimeError("Brave Search API key not found in env or Keychain")
    results = _brave_request(query, api_key, count)
    return _format_results(query, results)


def _brave_request(query: str, api_key: str, count: int) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "count": count})
    request = urllib.request.Request(
        f"{BRAVE_ENDPOINT}?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    web = payload.get("web", {})
    return list(web.get("results", []))


def _format_results(query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"No web results found for '{query}'."
    lines = [f"Top results for '{query}':"]
    for index, result in enumerate(results, start=1):
        title = result.get("title", "").strip()
        description = result.get("description", "").strip()
        url = result.get("url", "").strip()
        lines.append(f"{index}. {title} — {description} ({url})")
    return "\n".join(lines)
