#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from manga_common import (
    SUBSCRIPTIONS_PATH,
    bootstrap_runtime,
    create_subscription,
    doctor_report,
    ensure_project_layout,
    execute_pipeline,
    fetch_comic_metadata,
    get_subscription_record,
    library_series_dir,
    load_subscriptions,
    rebuild_merged_from_epubs,
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
    report = doctor_report(check_network=args.check_network, query=args.network_query)
    print_json(report)
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

    job_name = args.job_name or safe_slug(f"{title}_{utc_now()[:19]}")
    job_root = ensure_project_layout()["runs"] / job_name
    report = execute_pipeline(
        comic_id=comic_id,
        title=title,
        author=author,
        group=args.group,
        job_root=job_root,
        chapter_limit=args.chapter_limit,
        merged_name=args.merged_name,
    )

    response: dict[str, object] = {"job_name": job_name, "report": report}
    if args.subscribe:
        response["subscription"] = create_subscription(title, comic_id, args.group)["subscription"]
    print_json(response)
    return 0 if report["validation"]["valid"] else 1


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
    }
    print_json(report)
    return 0 if report["validation"]["valid"] else 1


def command_validate_epub(args: argparse.Namespace) -> int:
    report = validate_epub(Path(args.path).resolve())
    print_json(report)
    return 0 if report["valid"] else 1


def command_show_series(args: argparse.Namespace) -> int:
    series_dir = library_series_dir(args.title)
    payload = {
        "series_dir": str(series_dir),
        "exists": series_dir.exists(),
        "chapters_dir": str(series_dir / "chapters"),
        "merged_dir": str(series_dir / "merged"),
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
    download.add_argument("--merged-name", default="omnibus.epub")
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
    rebuild.set_defaults(func=command_rebuild_merged)

    validate = subparsers.add_parser("validate-epub", help="Validate EPUB structure")
    validate.add_argument("--path", required=True)
    validate.set_defaults(func=command_validate_epub)

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
