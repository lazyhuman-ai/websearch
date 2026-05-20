from __future__ import annotations

from websearch_service.types import SearchRequest


ENGINE_HEADER_OVERRIDES: dict[str, list[dict[str, str]]] = {
    "google_web": [
        {"Referer": "https://www.google.com/", "Upgrade-Insecure-Requests": "1"},
    ],
    "bing_web": [
        {"Referer": "https://www.bing.com/", "Upgrade-Insecure-Requests": "1"},
    ],
    "brave_web": [
        {
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        },
    ],
    "duckduckgo_lite": [
        {"Referer": "https://duckduckgo.com/"},
    ],
    "github": [
        {"Referer": "https://github.com/"},
    ],
}


def build_engine_headers(
    engine_name: str,
    request: SearchRequest,
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": request.language,
        "DNT": "1",
    }
    for profile in ENGINE_HEADER_OVERRIDES.get(engine_name, []):
        headers.update(profile)
    if extra_headers:
        headers.update(extra_headers)
    return headers
