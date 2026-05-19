from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.search import SearchClient, SearchRequest


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    client = SearchClient()
    request = SearchRequest(
        query=args.query,
        category=args.category,
        language=args.language,
        page=args.page,
        time_range=args.time_range,
        max_results=args.max_results,
        max_engine_requests=args.max_engine_requests,
        enabled_engines=[item.strip() for item in (args.engines or "").split(",") if item.strip()],
        site=args.site or None,
        resolve_urls=args.resolve_urls,
        include_url_content=args.include_url_content,
        engine_config_path=args.engine_config or None,
    )
    response = client.search(request)
    payload = response.to_dict()
    if args.read:
        payload["documents"] = [item.to_dict() for item in client.read_results(response.results, limit=args.max_results)]
    return payload


def append_log(log_path: Path, content: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(content)
        if not content.endswith("\n"):
            handle.write("\n")


def build_clean_log(payload: dict[str, object]) -> str:
    lines: list[str] = []
    results = payload.get("results")
    if isinstance(results, list):
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            parsed = item.get("parsed_url")
            url = str(item.get("url") or "").strip()
            content = ""
            if isinstance(parsed, dict):
                url = str(parsed.get("final_url") or parsed.get("resolved_url") or item.get("url") or "").strip()
                content = str(parsed.get("content_text") or parsed.get("content_markdown") or "").strip()
            if not content:
                title = str(item.get("title") or "").strip()
                snippet = str(item.get("snippet") or "").strip()
                content = "\n".join(part for part in [title, snippet] if part)
            if not url and not content:
                continue
            lines.append(f"[result {index}]")
            lines.append(f"url: {url}")
            lines.append("content:")
            lines.append(content or "<empty>")
            lines.append("")
    documents = payload.get("documents")
    if isinstance(documents, list):
        for index, item in enumerate(documents, start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            content = str(item.get("content_text") or item.get("content_markdown") or "").strip()
            if not url and not content:
                continue
            lines.append(f"[document {index}]")
            lines.append(f"url: {url}")
            lines.append("content:")
            lines.append(content or "<empty>")
            lines.append("")
    return "\n".join(lines).strip()


def persist_logs(args: argparse.Namespace, payload: dict[str, object]) -> None:
    timestamp = datetime.now().isoformat()
    raw_log_path = Path(args.log_file)
    clean_log_path = Path(args.clean_log_file)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)
    append_log(raw_log_path, f"\n=== search_web started_at={timestamp} query={args.query!r} category={args.category} ===")
    append_log(raw_log_path, serialized)
    clean_log = build_clean_log(payload)
    append_log(clean_log_path, f"\n=== search_web started_at={timestamp} query={args.query!r} category={args.category} ===")
    append_log(clean_log_path, clean_log or "<empty>")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Python-native multi-engine metasearch client")
    parser.add_argument("query", help="Search prompt or query")
    parser.add_argument("--category", default="auto", choices=["auto", "general", "news", "reference", "academic", "code"])
    parser.add_argument("--language", default="en-US", help="Search language hint, e.g. en-US or zh-CN")
    parser.add_argument("--page", type=int, default=1, help="Result page to request")
    parser.add_argument("--time-range", default="any", choices=["any", "day", "week", "month", "year"])
    parser.add_argument("--max-results", type=int, default=5, help="Per-engine result count requested for each upstream search request")
    parser.add_argument("--max-engine-requests", type=int, default=1, help="Maximum number of paginated requests sent to each engine")
    parser.add_argument("--engines", default="", help="Comma-separated engine override list")
    parser.add_argument("--site", default="", help="Optional site restriction, e.g. docs.python.org")
    parser.add_argument("--engine-config", default="", help="Optional YAML path for engine group configuration")
    parser.add_argument("--resolve-urls", action=argparse.BooleanOptionalAction, default=True, help="Resolve and normalize returned result URLs")
    parser.add_argument("--include-url-content", action=argparse.BooleanOptionalAction, default=True, help="Include LLM-friendly page content in resolved URL metadata")
    parser.add_argument("--read", action="store_true", help="Read and extract the top matching pages")
    parser.add_argument("--log-file", default="logs/search_web.log", help="Path to append raw JSON logs")
    parser.add_argument("--clean-log-file", default="logs/search_web.clean.log", help="Path to append url + cleaned content logs")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    payload = build_payload(args)
    persist_logs(args, payload)
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
