from __future__ import annotations

import random

import httpx


USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

def build_headers(*, user_agent: str, accept_language: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept-Language": accept_language,
        "DNT": "1",
    }

def choose_user_agent(default_user_agent: str, rotate: bool) -> str:
    if not rotate:
        return default_user_agent
    return random.choice(USER_AGENTS)


def build_async_client(
    *,
    timeout_seconds: float,
    follow_redirects: bool,
    user_agent: str,
    accept_language: str,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=follow_redirects,
        headers=build_headers(user_agent=user_agent, accept_language=accept_language),
        cookies={},
    )
