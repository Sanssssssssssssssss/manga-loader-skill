#!/usr/bin/env python3
from __future__ import annotations

import argparse

from epub_checks import audit_epub, print_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit EPUB reader compatibility and fixed-layout semantics")
    parser.add_argument("--path", required=True, help="Path to epub file")
    parser.add_argument("--require-fixed-layout", action="store_true")
    parser.add_argument("--require-page-images", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = audit_epub(
        args.path,
        require_fixed_layout=args.require_fixed_layout,
        require_page_images=args.require_page_images,
    )
    print_json(report)
    return 0 if report["reader_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
