#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
from typing import Any

from epub_checks import audit_epub


def _run_once(path: str, require_fixed_layout: bool, require_page_images: bool) -> dict[str, Any]:
    return audit_epub(
        path,
        require_fixed_layout=require_fixed_layout,
        require_page_images=require_page_images,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repeated EPUB audits under concurrent load")
    parser.add_argument("--path", action="append", required=True, help="EPUB path, repeatable")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--require-fixed-layout", action="store_true")
    parser.add_argument("--require-page-images", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paths = [str(Path(path).resolve()) for path in args.path]
    jobs: list[str] = []
    for _ in range(args.repeat):
        jobs.extend(paths)

    results: dict[str, list[dict[str, Any]]] = {path: [] for path in paths}
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                _run_once,
                path,
                args.require_fixed_layout,
                args.require_page_images,
            )
            for path in jobs
        ]
        for future in concurrent.futures.as_completed(futures):
            report = future.result()
            results[str(Path(report["path"]).resolve())].append(report)

    summary: dict[str, Any] = {
        "repeat": args.repeat,
        "workers": args.workers,
        "require_fixed_layout": args.require_fixed_layout,
        "require_page_images": args.require_page_images,
        "paths": {},
    }
    exit_code = 0
    for path in paths:
        reports = results[path]
        passed = sum(1 for item in reports if item["reader_ready"])
        failed = len(reports) - passed
        unique_errors = sorted({error for item in reports for error in item["errors"]})
        summary["paths"][path] = {
            "runs": len(reports),
            "passed": passed,
            "failed": failed,
            "unique_errors": unique_errors,
            "max_duration_sec": max((item["duration_sec"] for item in reports), default=0.0),
            "min_duration_sec": min((item["duration_sec"] for item in reports), default=0.0),
        }
        if failed:
            exit_code = 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
