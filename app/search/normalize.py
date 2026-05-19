from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKER_PREFIXES = ("utm_",)
TRACKER_KEYS = {
    "ved",
    "ei",
    "gclid",
    "fbclid",
    "msclkid",
    "ref",
    "ref_src",
    "src",
    "spm",
    "igshid",
}
UNWRAP_KEYS = ("uddg", "u", "url", "target", "dest", "destination", "redir", "redirect")
MULTI_SPACE_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def clean_text(text: str) -> str:
    return MULTI_SPACE_RE.sub(" ", unescape(text or "")).strip()


def unwrap_redirect_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in UNWRAP_KEYS:
        target = query.get(key)
        if target and target.startswith(("http://", "https://")):
            return target
    return url


def strip_tracking_params(url: str) -> str:
    parsed = urlparse(url)
    filtered = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key in TRACKER_KEYS or key.startswith(TRACKER_PREFIXES):
            continue
        filtered.append((key, value))
    cleaned_path = parsed.path or "/"
    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            cleaned_path,
            "",
            urlencode(filtered, doseq=True),
            "",
        )
    )


def normalize_url(url: str, strip_trackers: bool = True) -> str:
    unwrapped = unwrap_redirect_url(url.strip())
    cleaned = strip_tracking_params(unwrapped) if strip_trackers else unwrapped
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def title_signature(title: str) -> str:
    normalized = NON_WORD_RE.sub(" ", clean_text(title).lower()).strip()
    return " ".join(token for token in normalized.split() if token)


def canonical_result_key(url: str, title: str) -> tuple[str, str]:
    normalized_url = normalize_url(url)
    parsed = urlparse(normalized_url)
    host = parsed.netloc
    return normalized_url, f"{host}|{title_signature(title)}"


def looks_low_quality(title: str, url: str) -> bool:
    normalized_title = clean_text(title).lower()
    parsed = urlparse(url)
    if len(normalized_title) < 3:
        return True
    if normalized_title in {"cache", "redirect", "javascript required"}:
        return True
    if parsed.netloc.lower() in {"github.com", "www.github.com"} and parsed.path.strip("/") == "":
        return True
    if parsed.netloc.lower() in {"www.google.com", "google.com", "www.bing.com", "bing.com"} and parsed.path.strip("/") in {"", "search"}:
        return True
    if normalized_title in {
        "github change is constant github keeps you ahead",
        "github · change is constant. github keeps you ahead.",
    }:
        return True
    return "/redirect" in url.lower()
