#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from epub_checks import audit_epub
from manga_common import (
    SUBSCRIPTIONS_PATH,
    bootstrap_runtime,
    compare_page_counts,
    copy_outputs_to_library,
    copy_split_outputs_to_library,
    create_subscription,
    doctor_report,
    ensure_project_layout,
    execute_pipeline,
    fetch_comic_metadata,
    get_subscription_record,
    library_series_dir,
    list_epub_files,
    load_settings,
    load_subscriptions,
    plan_split_volumes,
    preview_epub,
    rebuild_merged_from_epubs,
    rebuild_split_merged_from_epubs,
    resolve_query,
    safe_slug,
    save_subscriptions,
    search_catalog,
    sync_subscription,
    utc_now,
    validate_epub,
)


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_bootstrap(args: argparse.Namespace) -> int:
    report = bootstrap_runtime(force=args.force)
    print_json(report)
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    report = doctor_report(
        check_network=args.check_network,
        query=args.network_query,
        audit_paths=[Path(item).resolve() for item in args.audit_path],
        audit_library=args.audit_library,
        audit_latest=not args.skip_latest_audit,
    )
    print_json(report)
    if report["status"] == "fail":
        return 1
    if args.strict and report["status"] != "ok":
        return 1
    return 0


def command_search(args: argparse.Namespace) -> int:
    results = search_catalog(args.query)
    print_json({"query": args.query, "results": results[: args.limit]})
    return 0


def command_subscribe(args: argparse.Namespace) -> int:
    result = create_subscription(args.query, args.comic_id, args.group)
    subscription = result["subscription"]
    response: dict[str, object] = {
        "subscription": subscription,
        "selected": result["selected"],
        "candidates": result["candidates"],
    }
    if args.run_now:
        response["run"] = sync_subscription(subscription, chapter_limit=args.chapter_limit)
    print_json(response)
    return 0


def command_subscriptions_list(args: argparse.Namespace) -> int:
    subscriptions = load_subscriptions()
    if not args.include_disabled:
        subscriptions = [item for item in subscriptions if item.get("enabled", True)]
    print_json({"subscriptions_path": str(SUBSCRIPTIONS_PATH), "subscriptions": subscriptions})
    return 0


def command_subscriptions_run(args: argparse.Namespace) -> int:
    if args.all:
        targets = [record for record in load_subscriptions() if record.get("enabled", True)]
    else:
        targets = [get_subscription_record(args.subscription)]
    reports = [sync_subscription(record, chapter_limit=args.chapter_limit) for record in targets]
    print_json({"ran": len(reports), "reports": reports})
    return 0


def command_download_full(args: argparse.Namespace) -> int:
    if args.comic_id:
        metadata = fetch_comic_metadata(args.comic_id)
        comic_id = args.comic_id
        title = args.title or str(metadata.get("name") or comic_id)
        authors = metadata.get("author") or []
    else:
        resolved = resolve_query(args.query)
        comic_id = str(resolved["selected"]["path_word"])
        metadata = fetch_comic_metadata(comic_id)
        title = args.title or str(metadata.get("name") or resolved["selected"]["name"] or comic_id)
        authors = metadata.get("author") or []

    if isinstance(authors, list):
        author = args.author or ", ".join(str(item) for item in authors if item) or "Unknown"
    else:
        author = args.author or str(authors or "Unknown")

    job_name = args.job_name or safe_slug(f"{title}_{comic_id}_{args.group}")
    job_root = ensure_project_layout()["runs"] / job_name
    report = execute_pipeline(
        comic_id=comic_id,
        title=title,
        author=author,
        group=args.group,
        job_root=job_root,
        chapter_limit=args.chapter_limit,
        merged_name=args.merged_name,
        split_chapters_per_volume=args.split_chapters_per_volume,
        split_max_size_mb=args.split_max_size_mb,
        split_name_template=args.split_name_template,
    )

    response: dict[str, object] = {"job_name": job_name, "report": report}
    if args.subscribe:
        response["subscription"] = create_subscription(title, comic_id, args.group)["subscription"]
    print_json(response)
    split_ok = True
    if report.get("split"):
        split_ok = bool(report["split"]["reader_ready"])
    return 0 if report["validation"]["valid"] and bool(report["audit"]["reader_ready"]) and split_ok else 1


def command_rebuild_merged(args: argparse.Namespace) -> int:
    output_path = Path(args.output).resolve()
    result = rebuild_merged_from_epubs(
        Path(args.chapter_epub_dir).resolve(),
        output_path,
        args.title,
        args.author,
        language=args.language,
        description=args.description,
        contributor=args.contributor,
    )
    report = {
        "output": str(result["output"]),
        "plan": str(result["plan"]),
        "validation": validate_epub(output_path),
        "audit": audit_epub(output_path, require_fixed_layout=True, require_page_images=True),
    }
    if not args.no_publish_library:
        report["library"] = copy_outputs_to_library(
            args.title,
            Path(args.chapter_epub_dir).resolve(),
            output_path,
            output_path.name,
            args.author,
            split_epubs=None,
        )
    print_json(report)
    return 0 if report["validation"]["valid"] and report["audit"]["reader_ready"] else 1


def command_rebuild_split(args: argparse.Namespace) -> int:
    settings = load_settings()
    packaging = settings.get("packaging", {})
    report = rebuild_split_merged_from_epubs(
        Path(args.chapter_epub_dir).resolve(),
        Path(args.output_dir).resolve(),
        args.title,
        args.author,
        language=args.language,
        description=args.description,
        contributor=args.contributor,
        chapters_per_volume=args.chapters_per_volume or int(packaging.get("split_chapters_per_volume", 40) or 40),
        max_volume_size_mb=args.max_size_mb,
        volume_name_template=args.volume_name_template or str(
            packaging.get("split_name_template", "{title} 第{volume_index:02d}册.epub")
        ),
    )
    if not args.no_publish_library:
        report["library"] = copy_split_outputs_to_library(
            args.title,
            [Path(item["output_epub"]).resolve() for item in report["volumes"]],
            args.author,
        )
    print_json(report)
    return 0 if report["reader_ready"] else 1


def command_plan_volumes(args: argparse.Namespace) -> int:
    settings = load_settings()
    packaging = settings.get("packaging", {})
    chapter_epubs = list_epub_files(Path(args.chapter_epub_dir).resolve())
    plan = plan_split_volumes(
        chapter_epubs,
        title=args.title,
        chapters_per_volume=args.chapters_per_volume or int(packaging.get("split_chapters_per_volume", 40) or 40),
        max_volume_size_mb=args.max_size_mb,
        volume_name_template=args.volume_name_template or str(
            packaging.get("split_name_template", "{title} 第{volume_index:02d}册.epub")
        ),
    )
    payload: dict[str, object] = {"plan": plan}
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["output"] = str(output_path)
    print_json(payload)
    return 0


def command_compare_pages(args: argparse.Namespace) -> int:
    report = compare_page_counts(
        Path(args.chapter_epub_dir).resolve(),
        merged_path=Path(args.merged).resolve() if args.merged else None,
        volumes_dir=Path(args.volumes_dir).resolve() if args.volumes_dir else None,
    )
    print_json(report)
    return 0


def command_validate_epub(args: argparse.Namespace) -> int:
    report = validate_epub(Path(args.path).resolve())
    print_json(report)
    return 0 if report["valid"] else 1


def command_preview_epub(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).resolve() if args.output_dir else Path(args.path).resolve().with_suffix(".preview")
    pages = [int(item) for item in args.pages.split(",") if item.strip()] if args.pages else None
    report = preview_epub(Path(args.path).resolve(), output_dir, pages)
    print_json(report)
    return 0


def command_show_series(args: argparse.Namespace) -> int:
    series_dir = library_series_dir(args.title)
    payload = {
        "series_dir": str(series_dir),
        "exists": series_dir.exists(),
        "chapters_dir": str(series_dir / "chapters"),
        "merged_dir": str(series_dir / "merged"),
        "volumes_dir": str(series_dir / "volumes"),
    }
    print_json(payload)
    return 0


def command_disable_subscription(args: argparse.Namespace) -> int:
    subscriptions = load_subscriptions()
    needle = get_subscription_record(args.subscription)["subscription_id"]
    for record in subscriptions:
        if record.get("subscription_id") == needle:
            record["enabled"] = False
            record["disabled_at"] = utc_now()
            save_subscriptions(subscriptions)
            print_json({"disabled": needle})
            return 0
    raise SystemExit(f"subscription not found: {args.subscription}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="General manga subscription, download, EPUB packaging, and omnibus skill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap", help="Create local runtime and install project dependencies")
    bootstrap.add_argument("--force", action="store_true")
    bootstrap.set_defaults(func=command_bootstrap)

    doctor = subparsers.add_parser("doctor", help="Inspect runtime, vendor assets, and optional network availability")
    doctor.add_argument("--check-network", action="store_true")
    doctor.add_argument("--network-query", default="葬送的芙莉莲")
    doctor.add_argument("--audit-path", action="append", default=[], help="Audit one or more EPUB files")
    doctor.add_argument("--audit-library", action="store_true", help="Audit all merged EPUBs under library")
    doctor.add_argument("--skip-latest-audit", action="store_true", help="Skip automatic audit of the latest job output")
    doctor.add_argument("--strict", action="store_true", help="Treat warnings as non-zero exit")
    doctor.set_defaults(func=command_doctor)

    search = subparsers.add_parser("search", help="Search manga from the built-in source adapter")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(func=command_search)

    subscribe = subparsers.add_parser("subscribe", help="Create or update a local subscription")
    group = subscribe.add_mutually_exclusive_group(required=True)
    group.add_argument("--query")
    group.add_argument("--comic-id")
    subscribe.add_argument("--group", default="default")
    subscribe.add_argument("--run-now", action="store_true")
    subscribe.add_argument("--chapter-limit", type=int)
    subscribe.set_defaults(func=command_subscribe)

    subscriptions = subparsers.add_parser("subscriptions", help="List or run local subscriptions")
    subscriptions_sub = subscriptions.add_subparsers(dest="subscriptions_command", required=True)

    subscriptions_list = subscriptions_sub.add_parser("list", help="List local subscriptions")
    subscriptions_list.add_argument("--include-disabled", action="store_true")
    subscriptions_list.set_defaults(func=command_subscriptions_list)

    subscriptions_run = subscriptions_sub.add_parser("run", help="Run one or more subscriptions")
    subscriptions_run_group = subscriptions_run.add_mutually_exclusive_group(required=True)
    subscriptions_run_group.add_argument("--subscription")
    subscriptions_run_group.add_argument("--all", action="store_true")
    subscriptions_run.add_argument("--chapter-limit", type=int)
    subscriptions_run.set_defaults(func=command_subscriptions_run)

    subscriptions_disable = subscriptions_sub.add_parser("disable", help="Disable a local subscription")
    subscriptions_disable.add_argument("--subscription", required=True)
    subscriptions_disable.set_defaults(func=command_disable_subscription)

    download = subparsers.add_parser("download-full", help="Download a manga and produce chapter EPUBs plus an omnibus")
    download_group = download.add_mutually_exclusive_group(required=True)
    download_group.add_argument("--query")
    download_group.add_argument("--comic-id")
    download.add_argument("--title")
    download.add_argument("--author")
    download.add_argument("--group", default="default")
    download.add_argument("--chapter-limit", type=int)
    download.add_argument("--job-name")
    download.add_argument("--merged-name")
    download.add_argument("--split-chapters-per-volume", type=int)
    download.add_argument("--split-max-size-mb", type=float)
    download.add_argument("--split-name-template")
    download.add_argument("--subscribe", action="store_true")
    download.set_defaults(func=command_download_full)

    rebuild = subparsers.add_parser("rebuild-merged", help="Rebuild a merged EPUB from existing chapter EPUBs")
    rebuild.add_argument("--chapter-epub-dir", required=True)
    rebuild.add_argument("--output", required=True)
    rebuild.add_argument("--title", required=True)
    rebuild.add_argument("--author", default="Unknown")
    rebuild.add_argument("--language", default="zh-Hans")
    rebuild.add_argument("--description", default="")
    rebuild.add_argument("--contributor", default="manga-loader-skill")
    rebuild.add_argument("--no-publish-library", action="store_true")
    rebuild.set_defaults(func=command_rebuild_merged)

    rebuild_split = subparsers.add_parser("rebuild-split", help="Rebuild split omnibus EPUBs from existing chapter EPUBs")
    rebuild_split.add_argument("--chapter-epub-dir", required=True)
    rebuild_split.add_argument("--output-dir", required=True)
    rebuild_split.add_argument("--title", required=True)
    rebuild_split.add_argument("--author", default="Unknown")
    rebuild_split.add_argument("--language", default="zh-Hans")
    rebuild_split.add_argument("--description", default="")
    rebuild_split.add_argument("--contributor", default="manga-loader-skill")
    rebuild_split.add_argument("--chapters-per-volume", type=int)
    rebuild_split.add_argument("--max-size-mb", type=float)
    rebuild_split.add_argument("--volume-name-template")
    rebuild_split.add_argument("--no-publish-library", action="store_true")
    rebuild_split.set_defaults(func=command_rebuild_split)

    plan_volumes = subparsers.add_parser("plan-volumes", help="Generate a split-volume plan from existing chapter EPUBs")
    plan_volumes.add_argument("--chapter-epub-dir", required=True)
    plan_volumes.add_argument("--title", required=True)
    plan_volumes.add_argument("--chapters-per-volume", type=int)
    plan_volumes.add_argument("--max-size-mb", type=float)
    plan_volumes.add_argument("--volume-name-template")
    plan_volumes.add_argument("--output")
    plan_volumes.set_defaults(func=command_plan_volumes)

    compare_pages = subparsers.add_parser("compare-pages", help="Compare source chapter page counts against merged or split EPUB outputs")
    compare_pages.add_argument("--chapter-epub-dir", required=True)
    compare_pages.add_argument("--merged")
    compare_pages.add_argument("--volumes-dir")
    compare_pages.set_defaults(func=command_compare_pages)

    validate = subparsers.add_parser("validate-epub", help="Validate EPUB structure")
    validate.add_argument("--path", required=True)
    validate.set_defaults(func=command_validate_epub)

    preview = subparsers.add_parser("preview-epub", help="Extract and render epub preview screenshots for debugging")
    preview.add_argument("--path", required=True)
    preview.add_argument("--output-dir")
    preview.add_argument("--pages", help="Comma-separated zero-based page indices, for example: 0,1,39")
    preview.set_defaults(func=command_preview_epub)

    show = subparsers.add_parser("show-series", help="Show the local library directory for a manga title")
    show.add_argument("--title", required=True)
    show.set_defaults(func=command_show_series)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
