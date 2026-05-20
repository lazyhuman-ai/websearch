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


def summarize_payload(case: TestCase, payload: dict[str, object], fetched: dict[str, object] | None) -> dict[str, object]:
    results = payload.get("results", [])
    snippet_issues: list[str] = []
    result_urls: list[str] = []

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

    fetch_ok = False
    fetched_text_length = 0
    fetched_title = ""
    if isinstance(fetched, dict):
        fetched_title = str(fetched.get("title") or "").strip()
        fetched_text = str(fetched.get("text") or "").strip()
        fetched_text_length = len(fetched_text)
        fetch_ok = bool(str(fetched.get("url") or "").strip() and fetched_title and fetched_text)

    return {
        "name": case.name,
        "query": case.query,
        "freshness": case.freshness,
        "result_count": len(results) if isinstance(results, list) else 0,
        "search_ok": bool(result_urls),
        "fetch_ok": fetch_ok,
        "top_result_url": result_urls[0] if result_urls else None,
        "fetched_title": fetched_title or None,
        "fetched_text_length": fetched_text_length,
        "snippet_issues": snippet_issues,
    }


def run_case(case: TestCase, language: str) -> tuple[dict[str, object], dict[str, object] | None]:
    try:
        from websearch_service import web_fetch, web_search

        results = web_search(
            query=case.query,
            count=case.count,
            language=language,
            freshness=case.freshness,  # type: ignore[arg-type]
            providers=list(case.providers) or None,
        )
        payload: dict[str, object] = {
            "query": case.query,
            "count": case.count,
            "language": language,
            "freshness": case.freshness,
            "providers": list(case.providers),
            "results": results,
        }
        fetched: dict[str, object] | None = None
        if results:
            top_url = str(results[0].get("url") or "").strip()
            if top_url:
                fetched = web_fetch(top_url)
                payload["fetched"] = fetched
        summary = summarize_payload(case, payload, fetched)
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
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch smoke test for web_search and web_fetch")
    parser.add_argument("--python-bin", default=sys.executable, help="Python interpreter recorded in the final report")
    parser.add_argument("--language", default="en-US", help="Search language hint, e.g. en-US or zh-CN")
    parser.add_argument("--only", default="", help="Comma-separated test case names to run")
    parser.add_argument("--output", default="", help="Optional path to save full JSON report")
    parser.add_argument("--log-file", default="logs/batch_test_search.log", help="Path to append batch run logs")
    parser.add_argument("--clean-log-file", default="logs/batch_test_search.clean.log", help="Path to append url + cleaned content logs")
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
        summary, payload = run_case(case, args.language)
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
