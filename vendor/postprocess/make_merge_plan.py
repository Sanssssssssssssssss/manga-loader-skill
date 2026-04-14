#!/usr/bin/env python3
"""Build merge-plan JSON for merge_epub_by_order.py from a directory of EPUBs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable


def natural_key(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def load_order_file(path: Path) -> list[str]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON order file must be an array of chapter names")
        return [str(item).strip() for item in data if str(item).strip()]

    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def iter_epubs(epub_dir: Path) -> list[Path]:
    return sorted((path for path in epub_dir.glob("*.epub") if path.is_file()), key=lambda p: natural_key(p.stem))


def order_epubs(epubs: list[Path], explicit_order: Iterable[str] | None) -> list[Path]:
    if not explicit_order:
        return epubs

    by_stem = {path.stem: path for path in epubs}
    ordered: list[Path] = []
    seen: set[str] = set()

    for name in explicit_order:
        if name in by_stem:
            ordered.append(by_stem[name])
            seen.add(name)

    leftovers = [path for path in epubs if path.stem not in seen]
    ordered.extend(leftovers)
    return ordered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create merge-plan JSON from a directory of chapter EPUBs")
    parser.add_argument("--epub-dir", required=True, help="Directory containing chapter EPUBs")
    parser.add_argument("--output", required=True, help="Final merged EPUB path")
    parser.add_argument("--title", required=True, help="Merged anthology title")
    parser.add_argument("--author", default="Unknown", help="Merged anthology author")
    parser.add_argument("--language", default="zh", help="Language metadata")
    parser.add_argument("--description", default="", help="Description metadata")
    parser.add_argument("--contributor", default="manga-epub-packager-lite", help="Contributor metadata")
    parser.add_argument("--order-file", help="Optional plain-text or JSON order file")
    parser.add_argument("--plan", required=True, help="Output plan JSON path")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    epub_dir = Path(args.epub_dir).resolve()
    plan_path = Path(args.plan).resolve()
    output_path = Path(args.output).resolve()

    if not epub_dir.is_dir():
        raise SystemExit(f"EPUB directory not found: {epub_dir}")

    epubs = iter_epubs(epub_dir)
    if not epubs:
        raise SystemExit(f"No EPUB files found in: {epub_dir}")

    explicit_order = None
    if args.order_file:
        explicit_order = load_order_file(Path(args.order_file).resolve())

    ordered_epubs = order_epubs(epubs, explicit_order)

    description = args.description or f"Merged from {len(ordered_epubs)} chapter EPUB(s)."
    chapters = []
    for index, path in enumerate(ordered_epubs, start=1):
        chapters.append(
            {
                "chapter_name": path.stem,
                "order": index,
                "epub_path": str(path),
            }
        )

    plan = {
        "output_epub_path": str(output_path),
        "title": args.title,
        "author": args.author,
        "language": args.language,
        "description": description,
        "contributor": args.contributor,
        "chapters": chapters,
    }

    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(plan_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
