from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEARCH_SCRIPT = ROOT / "scripts" / "search_web.py"


@dataclass(frozen=True)
class TestCase:
    name: str
    query: str
    category: str = "auto"
    site: str = ""
    max_results: int = 5
    resolve_urls: bool = True
    include_url_content: bool = True
    read: bool = False


TEST_CASES = [
    TestCase(name="general_distributed_systems", query="distributed systems consistency model overview", category="general"),
    TestCase(name="news_ai_infrastructure", query="latest AI infrastructure news", category="news"),
    TestCase(name="reference_ada_lovelace", query="who is Ada Lovelace", category="reference"),
    TestCase(name="academic_speculative_decoding", query="speculative decoding paper", category="academic"),
    TestCase(name="code_asyncio_semaphore", query="python asyncio semaphore example github", category="code"),
]


def build_command(case: TestCase, python_bin: str, engine_config: str, raw_log_file: Path, clean_log_file: Path) -> list[str]:
    cmd = [
        python_bin,
        str(SEARCH_SCRIPT),
        case.query,
        "--category",
        case.category,
        "--max-results",
        str(case.max_results),
    ]
    if case.site:
        cmd.extend(["--site", case.site])
    if engine_config:
        cmd.extend(["--engine-config", engine_config])
    cmd.append("--resolve-urls" if case.resolve_urls else "--no-resolve-urls")
    cmd.append("--include-url-content" if case.include_url_content else "--no-include-url-content")
    if case.read:
        cmd.append("--read")
    cmd.extend(["--log-file", str(raw_log_file), "--clean-log-file", str(clean_log_file)])
    return cmd


def summarize_payload(case: TestCase, payload: dict[str, object]) -> dict[str, object]:
    results = payload.get("results", [])
    failures = payload.get("engine_failures", {})
    documents = payload.get("documents", [])
    parsed_url_count = 0
    content_count = 0
    snippet_issues: list[str] = []

    if isinstance(results, list):
        for index, item in enumerate(results):
            if not isinstance(item, dict):
                continue
            parsed = item.get("parsed_url")
            if isinstance(parsed, dict):
                parsed_url_count += 1
                if parsed.get("content_markdown") or parsed.get("content_text"):
                    content_count += 1
            snippet = str(item.get("snippet") or "").strip()
            if not snippet:
                snippet_issues.append(f"result[{index}] empty_snippet")
            elif len(snippet) < 15:
                snippet_issues.append(f"result[{index}] short_snippet={snippet!r}")

    success_documents = 0
    if isinstance(documents, list):
        for item in documents:
            if isinstance(item, dict) and item.get("success"):
                success_documents += 1

    return {
        "name": case.name,
        "query": case.query,
        "category": case.category,
        "site": case.site or None,
        "used_engines": payload.get("used_engines", []),
        "result_count": len(results) if isinstance(results, list) else 0,
        "parsed_url_count": parsed_url_count,
        "content_count": content_count,
        "document_success_count": success_documents,
        "failure_count": len(failures) if isinstance(failures, dict) else 0,
        "snippet_issues": snippet_issues,
    }


def run_case(
    case: TestCase,
    python_bin: str,
    engine_config: str,
    timeout: int,
    raw_log_file: Path,
    clean_log_file: Path,
) -> tuple[dict[str, object], dict[str, object] | None]:
    cmd = build_command(case, python_bin, engine_config, raw_log_file, clean_log_file)
    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            {
                "name": case.name,
                "ok": False,
                "duration_seconds": round(time.monotonic() - started_at, 3),
                "error": f"timeout_after_{timeout}s",
                "command": cmd,
            },
            None,
        )

    duration = round(time.monotonic() - started_at, 3)
    if completed.returncode != 0:
        return (
            {
                "name": case.name,
                "ok": False,
                "duration_seconds": duration,
                "error": "nonzero_exit",
                "returncode": completed.returncode,
                "stderr": completed.stderr.strip(),
                "command": cmd,
            },
            None,
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return (
            {
                "name": case.name,
                "ok": False,
                "duration_seconds": duration,
                "error": "invalid_json",
                "stdout": completed.stdout[:4000],
                "stderr": completed.stderr.strip(),
                "command": cmd,
            },
            None,
        )

    summary = summarize_payload(case, payload)
    summary["ok"] = True
    summary["duration_seconds"] = duration
    return summary, payload


def append_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message)
        if not message.endswith("\n"):
            handle.write("\n")


def build_clean_log(case: TestCase, payload: dict[str, object]) -> str:
    lines = [f"case: {case.name}", f"query: {case.query}", f"category: {case.category}", ""]
    results = payload.get("results")
    if isinstance(results, list):
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            parsed = item.get("parsed_url")
            if not isinstance(parsed, dict):
                continue
            url = str(parsed.get("final_url") or parsed.get("resolved_url") or item.get("url") or "").strip()
            content = str(parsed.get("content_text") or parsed.get("content_markdown") or "").strip()
            if not url and not content:
                continue
            lines.extend([f"[result {index}]", f"url: {url}", "content:", content or "<empty>", ""])
    documents = payload.get("documents")
    if isinstance(documents, list):
        for index, item in enumerate(documents, start=1):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            content = str(item.get("content_text") or item.get("content_markdown") or "").strip()
            if not url and not content:
                continue
            lines.extend([f"[document {index}]", f"url: {url}", "content:", content or "<empty>", ""])
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch smoke test for multi-engine websearch")
    parser.add_argument("--python-bin", default=sys.executable, help="Python interpreter used to run scripts/search_web.py")
    parser.add_argument("--engine-config", default="", help="Optional YAML path for engine group configuration")
    parser.add_argument("--timeout", type=int, default=45, help="Per-query timeout in seconds")
    parser.add_argument("--only", default="", help="Comma-separated test case names to run")
    parser.add_argument("--output", default="", help="Optional path to save full JSON report")
    parser.add_argument("--log-file", default="logs/batch_test_search.log", help="Path to append batch run logs")
    parser.add_argument("--clean-log-file", default="logs/batch_test_search.clean.log", help="Path to append url + cleaned content logs")
    parser.add_argument("--case-log-dir", default="logs/search_web_cases", help="Directory for per-case raw and clean logs written by scripts/search_web.py")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print final JSON report")
    args = parser.parse_args()

    selected = {item.strip() for item in args.only.split(",") if item.strip()}
    cases = [case for case in TEST_CASES if not selected or case.name in selected]
    if not cases:
        print("No test cases selected.", file=sys.stderr)
        return 1

    log_path = Path(args.log_file)
    clean_log_path = Path(args.clean_log_file)
    case_log_dir = Path(args.case_log_dir)
    append_log(
        log_path,
        f"\n=== batch_test_search started_at={datetime.now().isoformat()} case_count={len(cases)} python_bin={args.python_bin} engine_config={args.engine_config or '<default>'} ===",
    )
    append_log(
        clean_log_path,
        f"\n=== batch_test_search started_at={datetime.now().isoformat()} case_count={len(cases)} python_bin={args.python_bin} engine_config={args.engine_config or '<default>'} ===",
    )

    report: dict[str, object] = {
        "python_bin": args.python_bin,
        "engine_config": args.engine_config or None,
        "log_file": str(log_path),
        "clean_log_file": str(clean_log_path),
        "case_log_dir": str(case_log_dir),
        "case_count": len(cases),
        "cases": [],
    }
    full_payloads: dict[str, object] = {}

    for case in cases:
        append_log(log_path, f"\n--- case={case.name} query={case.query!r} category={case.category} site={case.site or '-'} ---")
        raw_case_log = case_log_dir / f"{case.name}.log"
        clean_case_log = case_log_dir / f"{case.name}.clean.log"
        summary, payload = run_case(case, args.python_bin, args.engine_config, args.timeout, raw_case_log, clean_case_log)
        line = f"[{case.name}] ok={summary.get('ok')} results={summary.get('result_count', 0)} failures={summary.get('failure_count', 0)} duration={summary.get('duration_seconds')}s"
        print(line)
        append_log(log_path, line)
        append_log(log_path, json.dumps(summary, ensure_ascii=False, indent=2))
        report["cases"].append(summary)
        if payload is not None:
            full_payloads[case.name] = payload
            append_log(log_path, json.dumps(payload, ensure_ascii=False, indent=2))
            append_log(clean_log_path, build_clean_log(case, payload))
            append_log(clean_log_path, "")

    report["payloads"] = full_payloads
    serialized = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
    append_log(log_path, serialized)
    append_log(log_path, f"=== batch_test_search finished_at={datetime.now().isoformat()} ===")
    append_log(clean_log_path, f"=== batch_test_search finished_at={datetime.now().isoformat()} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
