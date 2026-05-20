from __future__ import annotations

import re
import json
from dataclasses import asdict, dataclass, field
from html import unescape
from urllib.parse import parse_qsl, quote, urlparse

import httpx
import trafilatura

from websearch_service.config import Settings, get_settings
from websearch_service.types import ParsedUrlResult
from websearch_service.utils import clean_text, normalize_url


CANONICAL_URL_RE = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', re.I)
OG_URL_RE = re.compile(r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']', re.I)
META_REFRESH_RE = re.compile(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^;]+;\s*url=([^"\']+)["\']', re.I)
GOOGLE_NEWS_ATTR_RE = re.compile(
    r'data-n-a-id="(?P<id>[^"]+)"[^>]+data-n-a-ts="(?P<ts>[^"]+)"[^>]+data-n-a-sg="(?P<sg>[^"]+)"',
    re.I | re.S,
)
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
MULTI_BLANK_RE = re.compile(r"\n{3,}")
BODY_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.I | re.S)
SCRIPT_STYLE_RE = re.compile(r"<(?:script|style|noscript)[^>]*>.*?</(?:script|style|noscript)>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class FetchMetadata:
    author: str | None = None
    published_at: str | None = None
    domain: str = ""
    http_status: int | None = None
    extractor: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FetchResult:
    url: str
    title: str
    text: str
    excerpt: str
    metadata: FetchMetadata = field(default_factory=FetchMetadata)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["metadata"] = self.metadata.to_dict()
        return payload


def web_fetch(url: str) -> dict[str, object]:
    return fetch_url(url).to_dict()


def fetch_url(url: str, *, settings: Settings | None = None) -> FetchResult:
    parsed = get_url(
        url,
        resolve=True,
        markdown=False,
        include_content=True,
        settings=settings,
    )
    text = parsed.content_text or parsed.content_markdown
    excerpt = parsed.content_excerpt or clean_text(text)[:240].rstrip(" ,;:|-")
    return FetchResult(
        url=parsed.final_url or parsed.resolved_url or parsed.normalized_url or parsed.input_url,
        title=parsed.title,
        text=text,
        excerpt=excerpt,
        metadata=FetchMetadata(
            author=None,
            published_at=None,
            domain=parsed.domain,
            http_status=parsed.http_status,
            extractor=parsed.extractor,
            error=parsed.error,
        ),
    )


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
    decoded_google_news_url = _decode_google_news_url(normalized_url, settings=active_settings)
    if decoded_google_news_url:
        normalized_url = normalize_url(decoded_google_news_url)
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
                resolved = _resolve_google_news_url(url, final_url, html, client=client, settings=active_settings)
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


def _resolve_google_news_url(
    original_url: str,
    fetched_url: str,
    html: str,
    *,
    client: httpx.Client | None = None,
    settings: Settings | None = None,
) -> str:
    original_host = urlparse(original_url).netloc.lower()
    fetched_host = urlparse(fetched_url).netloc.lower()
    if original_host != "news.google.com" and fetched_host != "news.google.com":
        return fetched_url
    decoded = _decode_google_news_from_html(fetched_url, html, client=client, settings=settings)
    if decoded:
        return decoded
    for pattern in (CANONICAL_URL_RE, OG_URL_RE, META_REFRESH_RE):
        match = pattern.search(html or "")
        if match:
            candidate = match.group(1).strip()
            if candidate.startswith("http") and "news.google.com" not in urlparse(candidate).netloc.lower():
                return candidate
    return fetched_url


def _decode_google_news_url(url: str, *, settings: Settings | None = None) -> str:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "news.google.com":
        return ""
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2 or path_parts[-2] not in {"articles", "read"}:
        return ""
    article_id = path_parts[-1]
    active_settings = settings or get_settings()
    headers = {
        "User-Agent": active_settings.user_agent,
        "Accept-Language": active_settings.default_language,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(timeout=active_settings.request_timeout_seconds, follow_redirects=True, headers=headers) as client:
        for prefix in ("articles", "rss/articles"):
            try:
                response = client.get(f"https://news.google.com/{prefix}/{article_id}")
                response.raise_for_status()
            except httpx.HTTPError:
                continue
            decoded = _decode_google_news_from_html(str(response.url), response.text, client=client, settings=active_settings)
            if decoded:
                return decoded
    return ""


def _decode_google_news_from_html(
    fetched_url: str,
    html: str,
    *,
    client: httpx.Client | None,
    settings: Settings | None,
) -> str:
    match = GOOGLE_NEWS_ATTR_RE.search(html or "")
    if not match:
        return ""
    active_settings = settings or get_settings()
    article_id = match.group("id")
    timestamp = match.group("ts")
    signature = match.group("sg")
    payload = [
        "Fbv4je",
        (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
            f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{article_id}",{timestamp},"{signature}"]'
        ),
    ]
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": active_settings.user_agent,
        "Accept-Language": active_settings.default_language,
        "Referer": fetched_url,
    }
    owns_client = client is None
    active_client = client or httpx.Client(timeout=active_settings.request_timeout_seconds, follow_redirects=True, headers=headers)
    try:
        response = active_client.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers=headers,
            data=f"f.req={quote(json.dumps([[payload]], separators=(',', ':')))}",
        )
        response.raise_for_status()
        chunks = response.text.split("\n\n")
        if len(chunks) < 2:
            return ""
        parsed = json.loads(chunks[1])[:-2]
        decoded_payload = json.loads(parsed[0][2])
        decoded_url = decoded_payload[1] if isinstance(decoded_payload, list) and len(decoded_payload) > 1 else ""
        return decoded_url if isinstance(decoded_url, str) and decoded_url.startswith(("http://", "https://")) else ""
    except (httpx.HTTPError, json.JSONDecodeError, IndexError, TypeError):
        return ""
    finally:
        if owns_client:
            active_client.close()


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
