from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.logging_utils import build_file_logger, log_json, log_section


@dataclass(frozen=True)
class TestCase:
    name: str
    query: str
    freshness: str = "any"
    count: int = 0
    providers: tuple[str, ...] = ()


TEST_CASES = [
    TestCase(name="general_distributed_systems", query="distributed systems consistency model overview"),
    TestCase(name="news_ai_infrastructure", query="latest AI infrastructure news", freshness="week"),
    TestCase(name="reference_ada_lovelace", query="who is Ada Lovelace"),
    TestCase(name="academic_speculative_decoding", query="speculative decoding paper"),
    TestCase(name="code_asyncio_semaphore", query="python asyncio semaphore example github"),
]


def fetch_result_items(results: object, web_fetch: object, *, limit: int = 0) -> list[dict[str, object]]:
    if not isinstance(results, list):
        return []
    fetched_items: list[dict[str, object]] = []
    selected = results if limit <= 0 else results[:limit]
    for index, item in enumerate(selected, start=1):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        try:
            fetched = web_fetch(url)  # type: ignore[operator]
        except Exception as exc:
            fetched = {
                "url": url,
                "title": str(item.get("title") or ""),
                "text": "",
                "excerpt": "",
                "metadata": {"domain": str(item.get("domain") or ""), "error": str(exc)},
            }
        fetched_items.append(
            {
                "rank": item.get("rank", index),
                "source_title": item.get("title", ""),
                "source_url": url,
                "source_engine": item.get("engine", ""),
                "fetch": fetched,
            }
        )
    return fetched_items


def summarize_payload(case: TestCase, payload: dict[str, object]) -> dict[str, object]:
    results = payload.get("results", [])
    fetched_results = payload.get("fetched_results", [])
    snippet_issues: list[str] = []
    result_urls: list[str] = []
    fetch_total = 0
    fetch_success_count = 0
    fetch_failure_count = 0
    fetched_text_lengths: list[int] = []

    if isinstance(results, list):
        for index, item in enumerate(results):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if url:
                result_urls.append(url)
            snippet = str(item.get("snippet") or "").strip()
            if not snippet:
                snippet_issues.append(f"result[{index}] empty_snippet")
            elif len(snippet) < 15:
                snippet_issues.append(f"result[{index}] short_snippet={snippet!r}")

    if isinstance(fetched_results, list):
        for item in fetched_results:
            if not isinstance(item, dict):
                continue
            fetched = item.get("fetch")
            if not isinstance(fetched, dict):
                continue
            fetch_total += 1
            fetched_text = str(fetched.get("text") or "").strip()
            fetched_title = str(fetched.get("title") or "").strip()
            metadata = fetched.get("metadata") if isinstance(fetched.get("metadata"), dict) else {}
            has_error = bool(metadata.get("error")) if isinstance(metadata, dict) else False
            if fetched_title and fetched_text and not has_error:
                fetch_success_count += 1
            else:
                fetch_failure_count += 1
            fetched_text_lengths.append(len(fetched_text))
    fetched = payload.get("fetched")
    if not fetch_total and isinstance(fetched, dict):
        fetch_total = 1
        fetched_text = str(fetched.get("text") or "").strip()
        fetched_title = str(fetched.get("title") or "").strip()
        fetch_success_count = 1 if fetched_title and fetched_text else 0
        fetch_failure_count = 0 if fetch_success_count else 1
        fetched_text_lengths.append(len(fetched_text))

    return {
        "name": case.name,
        "query": case.query,
        "freshness": case.freshness,
        "result_count": len(results) if isinstance(results, list) else 0,
        "search_ok": bool(result_urls),
        "fetch_ok": fetch_success_count > 0,
        "fetch_total": fetch_total,
        "fetch_success_count": fetch_success_count,
        "fetch_failure_count": fetch_failure_count,
        "top_result_url": result_urls[0] if result_urls else None,
        "fetched_text_lengths": fetched_text_lengths,
        "snippet_issues": snippet_issues,
    }


def run_case(case: TestCase, language: str, *, fetch_limit: int) -> tuple[dict[str, object], dict[str, object] | None]:
    try:
        from websearch_service import web_fetch, web_search_payload

        payload = web_search_payload(
            query=case.query,
            count=case.count,
            language=language,
            freshness=case.freshness,  # type: ignore[arg-type]
            providers=list(case.providers) or None,
        )
        results = payload.get("results", [])
        if isinstance(results, list) and results:
            fetched_results = fetch_result_items(results, web_fetch, limit=fetch_limit)
            payload["fetched_results"] = fetched_results
            if fetched_results:
                payload["fetched"] = fetched_results[0]["fetch"]
        summary = summarize_payload(case, payload)
        summary["ok"] = bool(summary["search_ok"] and summary["fetch_ok"])
        return summary, payload
    except ModuleNotFoundError as exc:
        missing = exc.name or "required dependency"
        return (
            {
                "name": case.name,
                "ok": False,
                "query": case.query,
                "freshness": case.freshness,
                "error": f"missing_dependency:{missing}",
            },
            None,
        )
    except Exception as exc:
        return (
            {
                "name": case.name,
                "ok": False,
                "query": case.query,
                "freshness": case.freshness,
                "error": str(exc),
            },
            None,
        )


def build_clean_log(case: TestCase, payload: dict[str, object]) -> str:
    lines = [f"case: {case.name}", f"query: {case.query}", f"freshness: {case.freshness}", ""]
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
            lines.extend([f"[result {index}]", f"url: {url}", "content:", content or "<empty>", ""])
    fetched = payload.get("fetched")
    if isinstance(fetched, dict):
        url = str(fetched.get("url") or "").strip()
        content = str(fetched.get("text") or "").strip()
        if url or content:
            lines.extend(["[fetched]", f"url: {url}", "content:", content or "<empty>", ""])
    fetched_results = payload.get("fetched_results")
    if isinstance(fetched_results, list):
        for item in fetched_results:
            if not isinstance(item, dict):
                continue
            fetched_item = item.get("fetch")
            if not isinstance(fetched_item, dict):
                continue
            url = str(fetched_item.get("url") or item.get("source_url") or "").strip()
            content = str(fetched_item.get("text") or fetched_item.get("excerpt") or "").strip()
            title = str(fetched_item.get("title") or item.get("source_title") or "").strip()
            lines.extend([f"[fetched result {item.get('rank', '')}]", f"url: {url}", "content:", content or title or "<empty>", ""])
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch smoke test for web_search and web_fetch")
    parser.add_argument("--python-bin", default=sys.executable, help="Python interpreter recorded in the final report")
    parser.add_argument("--language", default="en-US", help="Search language hint, e.g. en-US or zh-CN")
    parser.add_argument("--only", default="", help="Comma-separated test case names to run")
    parser.add_argument("--output", default="", help="Optional path to save full JSON report")
    parser.add_argument("--log-file", default="logs/batch_test_search.log", help="Path to append batch run logs")
    parser.add_argument("--clean-log-file", default="logs/batch_test_search.clean.log", help="Path to append url + cleaned content logs")
    parser.add_argument("--fetch-limit", type=int, default=0, help="Maximum search results to fetch per case. Use 0 for all returned results.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print final JSON report")
    args = parser.parse_args()

    selected = {item.strip() for item in args.only.split(",") if item.strip()}
    cases = [case for case in TEST_CASES if not selected or case.name in selected]
    if not cases:
        print("No test cases selected.", file=sys.stderr)
        return 1

    log_path = Path(args.log_file)
    clean_log_path = Path(args.clean_log_file)
    raw_logger = build_file_logger("batch_test_search_raw", log_path)
    clean_logger = build_file_logger("batch_test_search_clean", clean_log_path)
    started_at = datetime.now().isoformat()
    log_section(raw_logger, f"batch_test_search started_at={started_at} case_count={len(cases)} language={args.language}")
    log_section(clean_logger, f"batch_test_search started_at={started_at} case_count={len(cases)} language={args.language}")

    report: dict[str, object] = {
        "python_bin": args.python_bin,
        "language": args.language,
        "log_file": str(log_path),
        "clean_log_file": str(clean_log_path),
        "case_count": len(cases),
        "cases": [],
    }
    full_payloads: dict[str, object] = {}

    for case in cases:
        log_section(raw_logger, f"case={case.name} query={case.query!r}")
        summary, payload = run_case(case, args.language, fetch_limit=max(0, args.fetch_limit))
        line = f"[{case.name}] ok={summary.get('ok')} results={summary.get('result_count', 0)} search_ok={summary.get('search_ok')} fetch_ok={summary.get('fetch_ok')}"
        print(line)
        raw_logger.info(line)
        log_json(raw_logger, summary)
        report["cases"].append(summary)
        if payload is not None:
            full_payloads[case.name] = payload
            log_json(raw_logger, payload)
            clean_logger.info(build_clean_log(case, payload))
            clean_logger.info("")

    report["payloads"] = full_payloads
    serialized = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
    log_json(raw_logger, report, pretty=args.pretty)
    finished_at = datetime.now().isoformat()
    log_section(raw_logger, f"batch_test_search finished_at={finished_at}")
    log_section(clean_logger, f"batch_test_search finished_at={finished_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
