from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.logging_utils import build_file_logger, log_json, log_section


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    try:
        from websearch_service import web_fetch, web_search_payload
    except ModuleNotFoundError as exc:
        missing = exc.name or "required dependency"
        raise RuntimeError(
            f"Missing dependency: {missing}. Install project dependencies with `pip install -r requirements.txt` "
            "or use the Python interpreter from the configured virtual environment."
        ) from exc

    providers = [item.strip() for item in (args.providers or "").split(",") if item.strip()]
    payload = web_search_payload(
        query=args.query,
        count=args.count,
        language=args.language,
        freshness=args.freshness,
        providers=providers or None,
    )
    results = payload.get("results", [])
    if args.fetch_url:
        payload["fetched"] = web_fetch(args.fetch_url)
    elif args.fetch_top and results:
        top_item = results[0] if isinstance(results, list) and results else {}
        top_url = str(top_item.get("url") or "").strip() if isinstance(top_item, dict) else ""
        if top_url:
            payload["fetched"] = web_fetch(top_url)
    return payload


def build_clean_log(payload: dict[str, object]) -> str:
    lines: list[str] = []
    results = payload.get("results")
    if isinstance(results, list):
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
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
    fetched = payload.get("fetched")
    if isinstance(fetched, dict):
        url = str(fetched.get("url") or "").strip()
        content = str(fetched.get("text") or "").strip()
        if url or content:
            lines.append("[fetched]")
            lines.append(f"url: {url}")
            lines.append("content:")
            lines.append(content or "<empty>")
            lines.append("")
    return "\n".join(lines).strip()


def persist_logs(args: argparse.Namespace, payload: dict[str, object]) -> None:
    timestamp = datetime.now().isoformat()
    raw_logger = build_file_logger("search_web_raw", Path(args.log_file))
    clean_logger = build_file_logger("search_web_clean", Path(args.clean_log_file))
    log_section(raw_logger, f"search_web started_at={timestamp} query={args.query!r}")
    log_json(raw_logger, payload, pretty=args.pretty)
    clean_log = build_clean_log(payload)
    log_section(clean_logger, f"search_web started_at={timestamp} query={args.query!r}")
    clean_logger.info(clean_log or "<empty>")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the lightweight web search and fetch wrappers")
    parser.add_argument("query", help="Search prompt or query")
    parser.add_argument("--language", default="en-US", help="Search language hint, e.g. en-US or zh-CN")
    parser.add_argument("--freshness", default="any", choices=["any", "day", "week", "month", "year"])
    parser.add_argument("--count", type=int, default=0, help="Per-engine fetch count. Use 0 to return the full aggregated ranked list.")
    parser.add_argument("--providers", default="", help="Comma-separated provider override list")
    parser.add_argument("--fetch-url", default="", help="Optional URL to fetch after search")
    parser.add_argument("--fetch-top", action="store_true", help="Fetch the top search result after search")
    parser.add_argument("--log-file", default="logs/search_web.log", help="Path to append raw JSON logs")
    parser.add_argument("--clean-log-file", default="logs/search_web.clean.log", help="Path to append url + cleaned content logs")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    try:
        payload = build_payload(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    persist_logs(args, payload)
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
