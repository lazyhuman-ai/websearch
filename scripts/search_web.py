from __future__ import annotations

import argparse
import json
import sys
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
        enabled_engines=[item.strip() for item in (args.engines or "").split(",") if item.strip()],
        site=args.site or None,
    )
    response = client.search(request)
    payload = response.to_dict()
    if args.read:
        payload["documents"] = [item.to_dict() for item in client.read_results(response.results, limit=args.max_results)]
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Python-native multi-engine metasearch client")
    parser.add_argument("query", help="Search prompt or query")
    parser.add_argument("--category", default="auto", choices=["auto", "general", "news", "reference", "academic", "code"])
    parser.add_argument("--language", default="en-US", help="Search language hint, e.g. en-US or zh-CN")
    parser.add_argument("--page", type=int, default=1, help="Result page to request")
    parser.add_argument("--time-range", default="any", choices=["any", "day", "week", "month", "year"])
    parser.add_argument("--max-results", type=int, default=5, help="Maximum number of search results")
    parser.add_argument("--engines", default="", help="Comma-separated engine override list")
    parser.add_argument("--site", default="", help="Optional site restriction, e.g. docs.python.org")
    parser.add_argument("--read", action="store_true", help="Read and extract the top matching pages")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    payload = build_payload(args)
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
