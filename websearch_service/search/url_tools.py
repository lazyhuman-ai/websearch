from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlparse

import httpx
import trafilatura

from websearch_service.config import Settings, get_settings
from websearch_service.search.normalize import clean_text, normalize_url
from websearch_service.search.types import ParsedUrlResult


CANONICAL_URL_RE = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I)
OG_URL_RE = re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I)
META_REFRESH_RE = re.compile(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^;]+;\s*url=([^"\']+)["\']', re.I)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
MULTI_BLANK_RE = re.compile(r"\n{3,}")
BODY_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.I | re.S)
SCRIPT_STYLE_RE = re.compile(r"<(?:script|style|noscript)[^>]*>.*?</(?:script|style|noscript)>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_llm_text(text: str, max_chars: int) -> str:
    normalized = MULTI_BLANK_RE.sub("\n\n", (text or "").strip())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "\n\n[TRUNCATED]"


def _extract_title(html: str) -> str:
    match = TITLE_RE.search(html or "")
    return clean_text(match.group(1)) if match else ""


def _extract_canonical_url(html: str) -> str:
    for pattern in (CANONICAL_URL_RE, OG_URL_RE):
        match = pattern.search(html or "")
        if match:
            candidate = clean_text(match.group(1))
            if candidate.startswith(("http://", "https://")):
                return candidate
    return ""


def _resolve_google_news_url(original_url: str, fetched_url: str, html: str) -> str:
    original_host = urlparse(original_url).netloc.lower()
    fetched_host = urlparse(fetched_url).netloc.lower()
    if original_host != "news.google.com" and fetched_host != "news.google.com":
        return fetched_url
    for pattern in (CANONICAL_URL_RE, OG_URL_RE, META_REFRESH_RE):
        match = pattern.search(html or "")
        if match:
            candidate = match.group(1).strip()
            if candidate.startswith("http") and "news.google.com" not in urlparse(candidate).netloc.lower():
                return candidate
    return fetched_url


def _is_google_consent_page(final_url: str, html: str) -> bool:
    host = urlparse(final_url).netloc.lower()
    title = _extract_title(html).strip().lower()
    if host == "consent.google.com":
        return True
    if title == "before you continue" or title.startswith("before you continue to google"):
        return True
    body = (html or "").lower()
    return "before you continue to google" in body and "consent.google.com" in final_url.lower()


def _extract_markdown(html: str, final_url: str) -> tuple[str, str]:
    markdown = trafilatura.extract(
        html,
        url=final_url,
        include_links=False,
        include_images=False,
        output_format="markdown",
        favor_recall=True,
        deduplicate=True,
    ) or ""
    text = trafilatura.extract(
        html,
        url=final_url,
        include_links=False,
        include_images=False,
        output_format="txt",
        favor_recall=True,
        deduplicate=True,
    ) or ""
    return markdown, text


def _fallback_text_extract(html: str, max_chars: int) -> str:
    body_match = BODY_RE.search(html or "")
    fragment = body_match.group(1) if body_match else (html or "")
    fragment = SCRIPT_STYLE_RE.sub(" ", fragment)
    text = clean_text(unescape(TAG_RE.sub(" ", fragment)))
    if not text:
        return ""
    return _clean_llm_text(text, max_chars)


def _excerpt_from_text(text: str, *, limit: int = 240) -> str:
    text = clean_text(text)
    if not text:
        return ""
    return text[:limit].rstrip(" ,;:|-")


def _is_supported_content_type(content_type: str) -> bool:
    if not content_type:
        return True
    lowered = content_type.lower()
    return any(token in lowered for token in ("text/html", "application/xhtml+xml", "text/plain"))


def get_url(
    url: str,
    *,
    resolve: bool = True,
    markdown: bool = True,
    include_content: bool = False,
    settings: Settings | None = None,
) -> ParsedUrlResult:
    active_settings = settings or get_settings()
    normalized_url = normalize_url(url)
    parsed = urlparse(normalized_url)
    payload = ParsedUrlResult(
        input_url=url,
        resolved_url=normalized_url if resolve else "",
        final_url=normalized_url if resolve else "",
        normalized_url=normalized_url,
        domain=parsed.netloc,
        path=parsed.path or "/",
        query={key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)},
    )
    if not resolve and not include_content:
        return payload
    transport_headers = {
        "User-Agent": active_settings.user_agent,
        "Accept-Language": active_settings.default_language,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        "DNT": "1",
    }
    last_error: str | None = None
    with httpx.Client(timeout=active_settings.request_timeout_seconds, follow_redirects=resolve, headers=transport_headers) as client:
        for attempt in range(2):
            try:
                response = client.get(normalized_url)
                payload.http_status = response.status_code
                response.raise_for_status()
                payload.content_type = response.headers.get("content-type", "")
                if not _is_supported_content_type(payload.content_type):
                    payload.error = f"unsupported_content_type: {payload.content_type}"
                    return payload
                final_url = str(response.url)
                html = response.text
                resolved = _resolve_google_news_url(url, final_url, html)
                if resolved != final_url:
                    response = client.get(resolved)
                    payload.http_status = response.status_code
                    response.raise_for_status()
                    payload.content_type = response.headers.get("content-type", "")
                    if not _is_supported_content_type(payload.content_type):
                        payload.error = f"unsupported_content_type: {payload.content_type}"
                        return payload
                    final_url = str(response.url)
                    html = response.text
                canonical_url = _extract_canonical_url(html)
                payload.resolved_url = normalize_url(resolved if resolve else normalized_url)
                payload.final_url = normalize_url(canonical_url or final_url) if resolve else normalized_url
                final_parsed = urlparse(payload.final_url or final_url)
                payload.domain = final_parsed.netloc or payload.domain
                payload.path = final_parsed.path or payload.path
                payload.query = {key: value for key, value in parse_qsl(final_parsed.query, keep_blank_values=True)}
                payload.title = _extract_title(html)
                if _is_google_consent_page(final_url, html):
                    payload.fetch_succeeded = False
                    payload.error = "blocked_interstitial"
                    return payload
                if include_content:
                    markdown_content, text_content = _extract_markdown(html, final_url)
                    cleaned_markdown = _clean_llm_text(markdown_content, active_settings.max_document_chars) if markdown and markdown_content else ""
                    cleaned_text = _clean_llm_text(text_content, active_settings.max_document_chars) if text_content else ""
                    if not cleaned_text:
                        cleaned_text = _fallback_text_extract(html, active_settings.max_document_chars)
                    if not cleaned_markdown and cleaned_text:
                        cleaned_markdown = cleaned_text
                        payload.extractor = "fallback_text"
                    else:
                        payload.extractor = "trafilatura"
                    payload.content_markdown = cleaned_markdown
                    payload.content_text = cleaned_text
                    payload.content_excerpt = _excerpt_from_text(cleaned_text or cleaned_markdown)
                payload.fetch_succeeded = True
                payload.error = None
                return payload
            except httpx.HTTPError as exc:
                last_error = f"fetch_error: {exc}"
                if attempt == 0:
                    continue
    payload.error = last_error
    return payload
