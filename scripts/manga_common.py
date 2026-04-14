#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
LIBRARY_DIR = PROJECT_ROOT / "library"
RUNS_DIR = PROJECT_ROOT / "runs"
STATE_DIR = PROJECT_ROOT / "state"
VENDOR_DIR = PROJECT_ROOT / "vendor"
RUNTIME_DIR = PROJECT_ROOT / ".runtime"

SETTINGS_PATH = CONFIG_DIR / "settings.json"
SETTINGS_EXAMPLE_PATH = CONFIG_DIR / "settings.example.json"
SUBSCRIPTIONS_PATH = STATE_DIR / "subscriptions.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "source": "copymanga",
    "default_group": "default",
    "language": "zh-Hans",
    "downloader": {
        "api_domain": "api.2025copy.com",
        "download_format": "webp",
        "api_retries": 5,
        "retry_base_sec": 1.0,
        "retry_jitter_sec": 0.5,
        "risk_wait_sec": 60.0,
        "chapter_concurrency": 1,
        "image_concurrency": 2,
        "chapter_interval_sec": 0.0,
        "image_interval_sec": 0.0,
    },
    "packaging": {
        "merged_name": "omnibus.epub",
        "jpeg_quality": 90,
        "page_background": "#000000",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "_", cleaned) or "manga"


def safe_path_name(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\\\|?*\0]', "_", text).strip().strip(".")
    return cleaned or safe_slug(text)


def natural_key(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def ensure_project_layout() -> dict[str, Path]:
    directories = {
        "project_root": PROJECT_ROOT,
        "config": CONFIG_DIR,
        "library": LIBRARY_DIR,
        "runs": RUNS_DIR,
        "state": STATE_DIR,
        "vendor": VENDOR_DIR,
        "runtime": RUNTIME_DIR,
        "runtime_bin": RUNTIME_DIR / "bin",
        "runtime_python": RUNTIME_DIR / "python-venv",
    }
    for key, path in directories.items():
        if key != "project_root":
            path.mkdir(parents=True, exist_ok=True)
    if not SUBSCRIPTIONS_PATH.exists():
        write_json(SUBSCRIPTIONS_PATH, {"subscriptions": []})
    ensure_settings_file()
    return directories


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def run_command(
    cmd: list[str | Path],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    rendered = [str(part) for part in cmd]
    print(f"[RUN] {' '.join(rendered)}")
    kwargs: dict[str, Any] = {"check": check, "text": True, "capture_output": capture_output}
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if env is not None:
        kwargs["env"] = env
    return subprocess.run(rendered, **kwargs)


def cli_number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def ensure_settings_file() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_EXAMPLE_PATH.exists():
        write_json(SETTINGS_EXAMPLE_PATH, DEFAULT_SETTINGS)
    if not SETTINGS_PATH.exists():
        shutil.copy2(SETTINGS_EXAMPLE_PATH, SETTINGS_PATH)
    return SETTINGS_PATH


def load_settings() -> dict[str, Any]:
    ensure_settings_file()
    return deep_merge(DEFAULT_SETTINGS, read_json(SETTINGS_PATH, {}))


def vendor_downloader_binary_path() -> Path:
    return VENDOR_DIR / "bin" / "copymanga-headless-rs"


def vendor_downloader_source_dir() -> Path:
    return VENDOR_DIR / "copymanga-headless-rs-src"


def vendor_merge_plan_builder_path() -> Path:
    return VENDOR_DIR / "postprocess" / "make_merge_plan.py"


def vendor_merge_script_path() -> Path:
    return VENDOR_DIR / "postprocess" / "merge_epub_by_order.py"


def project_simple_epub_script() -> Path:
    return PROJECT_ROOT / "scripts" / "simple_epub.py"


def project_merge_epub_script() -> Path:
    return PROJECT_ROOT / "scripts" / "merge_epub.py"


def runtime_python_dir() -> Path:
    return RUNTIME_DIR / "python-venv"


def runtime_python_path() -> Path:
    return runtime_python_dir() / "bin" / "python3"


def runtime_downloader_path() -> Path:
    return RUNTIME_DIR / "bin" / "copymanga-headless-rs"


def build_downloader_from_source(target_path: Path) -> None:
    source_dir = vendor_downloader_source_dir()
    manifest = source_dir / "Cargo.toml"
    cargo = shutil.which("cargo")
    if not manifest.exists():
        raise FileNotFoundError(f"missing downloader source: {manifest}")
    if not cargo:
        raise FileNotFoundError("cargo not found and no prebuilt downloader binary available")
    run_command([cargo, "build", "--release"], cwd=source_dir, capture_output=False)
    built = source_dir / "target" / "release" / "copymanga-headless-rs"
    if not built.exists():
        raise FileNotFoundError(f"built downloader missing: {built}")
    shutil.copy2(built, target_path)
    target_path.chmod(0o755)


def bootstrap_runtime(force: bool = False) -> dict[str, Any]:
    ensure_project_layout()

    runtime_bin = RUNTIME_DIR / "bin"
    runtime_bin.mkdir(parents=True, exist_ok=True)

    runtime_py_dir = runtime_python_dir()
    runtime_py = runtime_python_path()
    if force and runtime_py_dir.exists():
        shutil.rmtree(runtime_py_dir)
    if not runtime_py.exists():
        run_command([sys.executable, "-m", "venv", runtime_py_dir], cwd=PROJECT_ROOT, capture_output=False)
        run_command([runtime_py, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=PROJECT_ROOT, capture_output=False)
        run_command([runtime_py, "-m", "pip", "install", "-r", PROJECT_ROOT / "requirements.txt"], cwd=PROJECT_ROOT, capture_output=False)

    downloader = runtime_downloader_path()
    if force and downloader.exists():
        downloader.unlink()
    if not downloader.exists():
        prebuilt = vendor_downloader_binary_path()
        if prebuilt.exists():
            shutil.copy2(prebuilt, downloader)
            downloader.chmod(0o755)
        else:
            build_downloader_from_source(downloader)

    report = {
        "project_root": str(PROJECT_ROOT),
        "runtime_python": str(runtime_py),
        "runtime_downloader": str(downloader),
        "settings_path": str(SETTINGS_PATH),
        "subscriptions_path": str(SUBSCRIPTIONS_PATH),
        "bootstrapped_at": utc_now(),
    }
    write_json(RUNTIME_DIR / "bootstrap-report.json", report)
    return report


def ensure_runtime(auto_bootstrap: bool = True) -> dict[str, Path]:
    ensure_project_layout()
    missing: list[str] = []
    if not runtime_python_path().exists():
        missing.append("runtime python")
    if not runtime_downloader_path().exists():
        missing.append("copymanga-headless-rs")
    if missing:
        if auto_bootstrap:
            bootstrap_runtime()
        else:
            raise FileNotFoundError(f"runtime missing: {', '.join(missing)}")
    return {
        "python": runtime_python_path(),
        "downloader": runtime_downloader_path(),
    }


def downloader_base_command(settings: dict[str, Any]) -> list[str]:
    runtime = ensure_runtime()
    downloader = settings["downloader"]
    return [
        str(runtime["downloader"]),
        "--state-dir",
        str(RUNTIME_DIR / "copymanga-state"),
        "--api-domain",
        str(downloader["api_domain"]),
        "--download-format",
        str(downloader["download_format"]),
        "--api-retries",
        cli_number(downloader["api_retries"]),
        "--retry-base-sec",
        cli_number(downloader["retry_base_sec"]),
        "--retry-jitter-sec",
        cli_number(downloader["retry_jitter_sec"]),
        "--risk-wait-sec",
        cli_number(downloader["risk_wait_sec"]),
        "--chapter-concurrency",
        cli_number(downloader["chapter_concurrency"]),
        "--image-concurrency",
        cli_number(downloader["image_concurrency"]),
        "--chapter-interval-sec",
        cli_number(downloader["chapter_interval_sec"]),
        "--image-interval-sec",
        cli_number(downloader["image_interval_sec"]),
    ]


def search_catalog(query: str) -> list[dict[str, Any]]:
    settings = load_settings()
    result = run_command(downloader_base_command(settings) + ["search", query, "--json"], cwd=PROJECT_ROOT)
    return json.loads(result.stdout)


def fetch_comic_metadata(comic_id: str) -> dict[str, Any]:
    settings = load_settings()
    result = run_command(downloader_base_command(settings) + ["comic", comic_id, "--json"], cwd=PROJECT_ROOT)
    return json.loads(result.stdout)


def fetch_chapters(comic_id: str, group: str) -> list[dict[str, Any]]:
    settings = load_settings()
    result = run_command(downloader_base_command(settings) + ["chapters", comic_id, "--group", group, "--json"], cwd=PROJECT_ROOT)
    return json.loads(result.stdout)


def normalize_match_key(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def resolve_query(query: str) -> dict[str, Any]:
    candidates = search_catalog(query)
    if not candidates:
        raise ValueError(f"no manga found for query: {query}")
    query_key = normalize_match_key(query)
    exact = next((item for item in candidates if normalize_match_key(str(item.get("name", ""))) == query_key), None)
    selected = exact or candidates[0]
    return {"selected": selected, "candidates": candidates[:10]}


def select_group(metadata: dict[str, Any], group_path_word: str) -> dict[str, Any]:
    groups = metadata.get("groups") or []
    for group in groups:
        if str(group.get("path_word")) == group_path_word:
            return group
    available = ", ".join(str(group.get("path_word")) for group in groups)
    raise ValueError(f"group not found: {group_path_word}. available: {available}")


def library_series_dir(title: str) -> Path:
    ensure_project_layout()
    return LIBRARY_DIR / safe_path_name(title)


def ensure_library_layout(title: str) -> dict[str, Path]:
    series_dir = library_series_dir(title)
    directories = {
        "series": series_dir,
        "chapters": series_dir / "chapters",
        "merged": series_dir / "merged",
        "meta": series_dir / "series.json",
    }
    for key, path in directories.items():
        if key != "meta":
            path.mkdir(parents=True, exist_ok=True)
    return directories


def load_subscriptions() -> list[dict[str, Any]]:
    ensure_project_layout()
    payload = read_json(SUBSCRIPTIONS_PATH, {"subscriptions": []})
    return list(payload.get("subscriptions", []))


def save_subscriptions(subscriptions: list[dict[str, Any]]) -> Path:
    return write_json(SUBSCRIPTIONS_PATH, {"subscriptions": subscriptions})


def subscription_identity(comic_id: str, group: str) -> str:
    return f"{comic_id}:{group}"


def upsert_subscription_record(record: dict[str, Any]) -> dict[str, Any]:
    subscriptions = load_subscriptions()
    identity = str(record["subscription_id"])
    updated = False
    for index, existing in enumerate(subscriptions):
        if str(existing.get("subscription_id")) == identity:
            subscriptions[index] = record
            updated = True
            break
    if not updated:
        subscriptions.append(record)
    save_subscriptions(subscriptions)
    return record


def get_subscription_record(identity_or_title: str) -> dict[str, Any]:
    needle = normalize_match_key(identity_or_title)
    for record in load_subscriptions():
        if normalize_match_key(str(record.get("subscription_id", ""))) == needle:
            return record
        if normalize_match_key(str(record.get("title", ""))) == needle:
            return record
    raise ValueError(f"subscription not found: {identity_or_title}")


def create_subscription(query: str | None, comic_id: str | None, group: str) -> dict[str, Any]:
    if comic_id:
        metadata = fetch_comic_metadata(comic_id)
        selected = {"name": metadata.get("name"), "path_word": comic_id}
        candidates: list[dict[str, Any]] = []
    elif query:
        resolved = resolve_query(query)
        selected = resolved["selected"]
        candidates = resolved["candidates"]
        comic_id = str(selected["path_word"])
        metadata = fetch_comic_metadata(comic_id)
    else:
        raise ValueError("query or comic_id is required")

    authors = metadata.get("author") or []
    author_text = ", ".join(str(item) for item in authors if item) if isinstance(authors, list) else str(authors or "Unknown")
    chosen_group = select_group(metadata, group)
    chapters = fetch_chapters(comic_id, group)
    record = {
        "subscription_id": subscription_identity(comic_id, group),
        "comic_id": comic_id,
        "title": str(metadata.get("name") or selected.get("name") or comic_id),
        "author": author_text or "Unknown",
        "group": group,
        "group_name": str(chosen_group.get("name") or group),
        "source": "copymanga",
        "query": query,
        "enabled": True,
        "last_known_chapter_count": len(chapters),
        "last_checked_at": utc_now(),
        "last_synced_at": None,
        "latest_job_root": None,
        "latest_merged_epub": None,
        "created_at": utc_now(),
    }
    upsert_subscription_record(record)
    return {"subscription": record, "selected": selected, "candidates": candidates}


def chapter_directories(group_dir: Path) -> list[Path]:
    return sorted([item for item in group_dir.iterdir() if item.is_dir()], key=lambda path: natural_key(path.name))


def locate_downloaded_group_dir(downloads_root: Path) -> Path:
    candidates: list[Path] = []
    for first_level in downloads_root.iterdir():
        if not first_level.is_dir():
            continue
        for second_level in first_level.iterdir():
            if second_level.is_dir() and any(item.is_dir() for item in second_level.iterdir()):
                candidates.append(second_level)
    if not candidates:
        raise FileNotFoundError(f"unable to locate downloaded manga group under: {downloads_root}")
    return sorted(candidates, key=lambda path: natural_key(path.as_posix()))[0]


def run_runtime_python(script_path: Path, args: list[str | Path], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    runtime = ensure_runtime()
    return run_command([runtime["python"], script_path, *args], cwd=PROJECT_ROOT, capture_output=capture_output)


def package_chapter_epubs(
    group_dir: Path,
    epubs_root: Path,
    series_title: str,
    author: str,
    *,
    language: str,
    page_background: str,
    jpeg_quality: int,
    skip_existing: bool = True,
) -> list[Path]:
    epubs_root.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    for chapter_dir in chapter_directories(group_dir):
        output_path = epubs_root / f"{chapter_dir.name}.epub"
        if skip_existing and output_path.exists():
            produced.append(output_path)
            continue
        chapter_title = f"{series_title} - {chapter_dir.name}"
        run_runtime_python(
            project_simple_epub_script(),
            [
                chapter_dir,
                output_path,
                chapter_title,
                "--author",
                author,
                "--language",
                language,
                "--page-background",
                page_background,
                "--jpeg-quality",
                str(jpeg_quality),
            ],
            capture_output=False,
        )
        produced.append(output_path)
    return produced


def merge_from_downloaded_chapters(
    group_dir: Path,
    output_path: Path,
    title: str,
    author: str,
    *,
    language: str,
    page_background: str,
    jpeg_quality: int,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_runtime_python(
        project_merge_epub_script(),
        [
            group_dir,
            output_path,
            title,
            "--author",
            author,
            "--language",
            language,
            "--page-background",
            page_background,
            "--jpeg-quality",
            str(jpeg_quality),
        ],
        capture_output=False,
    )
    return output_path


def extract_images_from_epub(epub_path: Path, target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(epub_path) as zf:
        image_members = [
            name
            for name in zf.namelist()
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")) and not name.startswith("META-INF/")
        ]
        if not image_members:
            raise FileNotFoundError(f"no page images found in epub: {epub_path}")
        for index, member in enumerate(sorted(image_members, key=lambda name: natural_key(Path(name).name)), start=1):
            suffix = Path(member).suffix.lower() or ".jpg"
            output_path = target_dir / f"{index:04d}{suffix}"
            output_path.write_bytes(zf.read(member))
            extracted.append(output_path)
    return extracted


def rebuild_merged_from_epubs(
    epub_dir: Path,
    output_path: Path,
    title: str,
    author: str,
    *,
    language: str = "zh-Hans",
    description: str = "",
    contributor: str = "manga-loader-skill",
) -> dict[str, Any]:
    plan_path = output_path.parent / f"{output_path.stem}.plan.json"
    settings = load_settings()
    packaging = settings.get("packaging", {})
    chapter_epubs = sorted(epub_dir.glob("*.epub"), key=lambda path: natural_key(path.name))
    if not chapter_epubs:
        raise FileNotFoundError(f"no chapter epubs found under: {epub_dir}")

    plan_payload: dict[str, Any] = {
        "title": title,
        "author": author or "Unknown",
        "language": language,
        "description": description or f"Merged from chapter EPUBs for {title}.",
        "contributor": contributor,
        "source_epubs": [str(path) for path in chapter_epubs],
        "output": str(output_path),
        "rebuilt_at": utc_now(),
    }

    with tempfile.TemporaryDirectory(prefix="manga-loader-rebuild-", dir=str(RUNTIME_DIR)) as temp_dir:
        temp_root = Path(temp_dir)
        extracted_summary: list[dict[str, Any]] = []
        for index, chapter_epub in enumerate(chapter_epubs, start=1):
            chapter_dir = temp_root / f"{index:04d} {chapter_epub.stem}"
            extracted = extract_images_from_epub(chapter_epub, chapter_dir)
            extracted_summary.append(
                {
                    "chapter_epub": str(chapter_epub),
                    "chapter_dir": str(chapter_dir),
                    "image_count": len(extracted),
                }
            )

        plan_payload["chapters"] = extracted_summary
        write_json(plan_path, plan_payload)
        merge_from_downloaded_chapters(
            temp_root,
            output_path,
            title,
            author,
            language=language,
            page_background=str(packaging.get("page_background", "#000000")),
            jpeg_quality=int(packaging.get("jpeg_quality", 90)),
        )
    return {"plan": plan_path, "output": output_path}


def copy_outputs_to_library(title: str, epubs_root: Path, merged_epub: Path, merged_name: str, author: str) -> dict[str, Any]:
    layout = ensure_library_layout(title)
    chapter_targets: list[str] = []
    for source in sorted(epubs_root.glob("*.epub"), key=lambda path: natural_key(path.name)):
        destination = layout["chapters"] / source.name
        shutil.copy2(source, destination)
        chapter_targets.append(str(destination))
    merged_target = layout["merged"] / merged_name
    shutil.copy2(merged_epub, merged_target)
    series_meta = {
        "title": title,
        "author": author,
        "latest_merged_epub": str(merged_target),
        "chapter_count": len(chapter_targets),
        "updated_at": utc_now(),
    }
    write_json(layout["meta"], series_meta)
    return {
        "series_dir": str(layout["series"]),
        "chapter_count": len(chapter_targets),
        "merged_epub": str(merged_target),
    }


def execute_pipeline(
    *,
    comic_id: str,
    title: str,
    author: str,
    group: str,
    job_root: Path,
    chapter_limit: int | None = None,
    merged_name: str | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    packaging = settings.get("packaging", {})
    ensure_runtime()
    job_root.mkdir(parents=True, exist_ok=True)
    remote_chapters = fetch_chapters(comic_id, group)

    downloads_root = job_root / "downloads"
    epubs_root = job_root / "epubs"
    merged_root = job_root / "merged"
    merged_root.mkdir(parents=True, exist_ok=True)

    download_cmd = downloader_base_command(settings) + [
        "download-group",
        comic_id,
        "--group",
        group,
        "--output-root",
        downloads_root,
        "--skip-existing",
    ]
    if chapter_limit is not None:
        download_cmd.extend(["--limit", str(chapter_limit)])
    run_command(download_cmd, cwd=PROJECT_ROOT, capture_output=False)

    group_dir = locate_downloaded_group_dir(downloads_root)
    chapter_epubs = package_chapter_epubs(
        group_dir,
        epubs_root,
        title,
        author,
        language=str(settings.get("language", "zh-Hans")),
        page_background=str(packaging.get("page_background", "#000000")),
        jpeg_quality=int(packaging.get("jpeg_quality", 90)),
        skip_existing=True,
    )
    merged_file_name = merged_name or str(packaging.get("merged_name", "omnibus.epub"))
    merged_epub = merge_from_downloaded_chapters(
        group_dir,
        merged_root / merged_file_name,
        title,
        author,
        language=str(settings.get("language", "zh-Hans")),
        page_background=str(packaging.get("page_background", "#000000")),
        jpeg_quality=int(packaging.get("jpeg_quality", 90)),
    )
    validation = validate_epub(merged_epub)
    library_copy = copy_outputs_to_library(title, epubs_root, merged_epub, merged_file_name, author)

    report = {
        "comic_id": comic_id,
        "title": title,
        "author": author,
        "group": group,
        "remote_chapter_count": len(remote_chapters),
        "requested_chapter_limit": chapter_limit,
        "job_root": str(job_root),
        "downloads_root": str(downloads_root),
        "group_dir": str(group_dir),
        "epubs_root": str(epubs_root),
        "chapter_epub_count": len(chapter_epubs),
        "merged_epub": str(merged_epub),
        "library": library_copy,
        "validation": validation,
        "completed_at": utc_now(),
    }
    write_json(job_root / "report.json", report)
    return report


def subscription_job_root(record: dict[str, Any]) -> Path:
    return RUNS_DIR / "subscriptions" / safe_slug(str(record["subscription_id"]))


def sync_subscription(record: dict[str, Any], chapter_limit: int | None = None) -> dict[str, Any]:
    report = execute_pipeline(
        comic_id=str(record["comic_id"]),
        title=str(record["title"]),
        author=str(record["author"]),
        group=str(record["group"]),
        job_root=subscription_job_root(record),
        chapter_limit=chapter_limit,
        merged_name="omnibus.epub",
    )
    refreshed = dict(record)
    refreshed["last_checked_at"] = utc_now()
    refreshed["last_synced_at"] = utc_now()
    refreshed["latest_job_root"] = report["job_root"]
    refreshed["latest_merged_epub"] = report["library"]["merged_epub"]
    refreshed["last_known_chapter_count"] = int(report["remote_chapter_count"])
    refreshed["last_downloaded_chapter_epub_count"] = int(report["chapter_epub_count"])
    upsert_subscription_record(refreshed)
    report["subscription"] = refreshed
    return report


def _opf_path_from_container(zf: zipfile.ZipFile) -> str:
    root = ET.fromstring(zf.read("META-INF/container.xml"))
    rootfile = root.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
    if rootfile is None:
        raise ValueError("container.xml missing rootfile")
    path = rootfile.attrib.get("full-path", "").strip()
    if not path:
        raise ValueError("container.xml rootfile missing full-path")
    return path


def validate_epub(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "xml_errors": [],
        "missing_spine_refs": [],
        "missing_manifest_hrefs": [],
        "opf_path": None,
        "xhtml_count": 0,
        "metadata": {
            "title": None,
            "creators": [],
            "language": None,
            "rendition_layout": None,
            "rendition_spread": None,
        },
        "valid": False,
    }
    if not path.exists():
        return report

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        report["entry_count"] = len(names)
        opf_path = _opf_path_from_container(zf)
        report["opf_path"] = opf_path
        opf_text = zf.read(opf_path).decode("utf-8", errors="ignore")
        opf_root = ET.fromstring(opf_text)
        ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
        metadata = opf_root.find("opf:metadata", ns)
        if metadata is not None:
            title_node = metadata.find("dc:title", ns)
            language_node = metadata.find("dc:language", ns)
            creator_nodes = metadata.findall("dc:creator", ns)
            report["metadata"]["title"] = title_node.text if title_node is not None else None
            report["metadata"]["language"] = language_node.text if language_node is not None else None
            report["metadata"]["creators"] = [node.text for node in creator_nodes if node.text]
            for meta_node in metadata.findall("opf:meta", ns):
                prop = meta_node.attrib.get("property")
                if prop == "rendition:layout":
                    report["metadata"]["rendition_layout"] = meta_node.text
                if prop == "rendition:spread":
                    report["metadata"]["rendition_spread"] = meta_node.text
        manifest_ids = re.findall(r'<item id="([^"]+)" href="([^"]+)"', opf_text)
        spine_ids = re.findall(r'<itemref idref="([^"]+)"', opf_text)
        manifest_id_set = {item_id for item_id, _ in manifest_ids}
        report["missing_spine_refs"] = [item_id for item_id in spine_ids if item_id not in manifest_id_set]
        opf_dir = Path(opf_path).parent.as_posix()
        for _, href in manifest_ids:
            member = str((Path(opf_dir) / href).as_posix()).lstrip("./")
            if member not in names:
                report["missing_manifest_hrefs"].append(member)

        for member in sorted(name for name in names if name.lower().endswith((".xhtml", ".html", ".opf", ".ncx", ".xml"))):
            try:
                ET.fromstring(zf.read(member))
            except Exception as exc:  # noqa: BLE001
                report["xml_errors"].append({"member": member, "error": f"{type(exc).__name__}: {exc}"})
            if member.lower().endswith((".xhtml", ".html")):
                report["xhtml_count"] += 1

    report["valid"] = not report["xml_errors"] and not report["missing_spine_refs"] and not report["missing_manifest_hrefs"]
    return report


def doctor_report(check_network: bool = False, query: str = "葬送的芙莉莲") -> dict[str, Any]:
    ensure_project_layout()
    subscriptions = load_subscriptions()
    report = {
        "project_root": str(PROJECT_ROOT),
        "settings_path": str(SETTINGS_PATH),
        "subscriptions_path": str(SUBSCRIPTIONS_PATH),
        "subscriptions_count": len(subscriptions),
        "library_dir": str(LIBRARY_DIR),
        "runs_dir": str(RUNS_DIR),
        "vendor": {
            "downloader_binary": str(vendor_downloader_binary_path()),
            "downloader_binary_exists": vendor_downloader_binary_path().exists(),
            "downloader_source": str(vendor_downloader_source_dir()),
            "downloader_source_exists": vendor_downloader_source_dir().exists(),
            "merge_plan_builder": str(vendor_merge_plan_builder_path()),
            "merge_script": str(vendor_merge_script_path()),
        },
        "runtime": {
            "python": str(runtime_python_path()),
            "python_exists": runtime_python_path().exists(),
            "downloader": str(runtime_downloader_path()),
            "downloader_exists": runtime_downloader_path().exists(),
        },
    }
    if check_network:
        resolved = resolve_query(query)
        report["network_probe"] = {
            "query": query,
            "selected": resolved["selected"],
            "candidate_count": len(resolved["candidates"]),
        }
    return report
