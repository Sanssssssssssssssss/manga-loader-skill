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
from xml.sax.saxutils import escape as xml_escape

from PIL import Image
from epub_checks import audit_epub

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
        "backend": "kcc_postprocess",
        "chapter_name_template": "{series_title} {chapter_label}.epub",
        "merged_name_template": "{title} 合订版.epub",
        "split_name_template": "{title} 第{volume_index:02d}册.epub",
        "split_chapters_per_volume": 40,
        "reading_direction": "ltr",
        "kcc_cmd": "",
        "kcc_profile": "KS",
        "kcc_extra_args": [],
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


def chapter_sort_prefix(name: str) -> int | None:
    match = re.match(r"^\s*(\d+)", name)
    return int(match.group(1)) if match else None


def chapter_display_label(name: str) -> str:
    match = re.match(r"^\s*\d+\s*(.+?)\s*$", name)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return name.strip()


def chapter_output_filename(series_title: str, chapter_dir_name: str) -> str:
    return f"{safe_path_name(series_title)} {safe_path_name(chapter_display_label(chapter_dir_name))}.epub"


def default_merged_filename(title: str) -> str:
    return f"{safe_path_name(title)} 合订版.epub"


def render_name_template(template: str, **values: Any) -> str:
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (int, float)):
            normalized[key] = value
        else:
            normalized[key] = str(value).strip()
    rendered = template.format(**normalized).strip()
    if not rendered.lower().endswith(".epub"):
        rendered = f"{rendered}.epub"
    return safe_path_name(rendered)


def normalize_reading_direction(value: str | None) -> str:
    text = str(value or "ltr").strip().lower()
    return text if text in {"ltr", "rtl", "default"} else "ltr"


def list_epub_files(directory: Path) -> list[Path]:
    return sorted([item for item in directory.glob("*.epub") if item.is_file()], key=lambda path: natural_key(path.name))


def _chapter_display_from_epub(epub_path: Path) -> str:
    return epub_path.stem.strip()


def _chapter_range_payload(chapter_epubs: list[Path]) -> dict[str, Any]:
    if not chapter_epubs:
        return {"start": None, "end": None, "display": None}
    start = _chapter_display_from_epub(chapter_epubs[0])
    end = _chapter_display_from_epub(chapter_epubs[-1])
    return {
        "start": start,
        "end": end,
        "display": start if start == end else f"{start} -> {end}",
    }


def plan_split_volumes(
    chapter_epubs: list[Path],
    *,
    title: str,
    chapters_per_volume: int | None = None,
    max_volume_size_mb: float | None = None,
    volume_name_template: str = "{title} 第{volume_index:02d}册.epub",
) -> dict[str, Any]:
    ordered = sorted([path.resolve() for path in chapter_epubs], key=lambda path: natural_key(path.name))
    if not ordered:
        raise FileNotFoundError("no chapter epubs available for split planning")
    if chapters_per_volume is not None and chapters_per_volume < 1:
        raise ValueError("chapters_per_volume must be >= 1")
    if max_volume_size_mb is not None and max_volume_size_mb <= 0:
        raise ValueError("max_volume_size_mb must be > 0")

    max_size_bytes = int(max_volume_size_mb * 1024 * 1024) if max_volume_size_mb is not None else None
    chapter_limit = chapters_per_volume or len(ordered)
    volumes: list[dict[str, Any]] = []
    current: list[Path] = []
    current_size = 0

    def flush_volume() -> None:
        nonlocal current
        nonlocal current_size
        if not current:
            return
        volume_index = len(volumes) + 1
        output_name = render_name_template(
            volume_name_template,
            title=title,
            series_title=title,
            volume_index=volume_index,
            volume_label=f"第{volume_index:02d}册",
        )
        range_payload = _chapter_range_payload(current)
        volumes.append(
            {
                "volume_id": f"volume-{volume_index:02d}",
                "volume_index": volume_index,
                "name": Path(output_name).stem,
                "output_name": output_name,
                "chapter_count": len(current),
                "chapter_range": range_payload,
                "chapter_stems": [path.stem for path in current],
                "chapter_files": [str(path) for path in current],
                "estimated_size_bytes": current_size,
            }
        )
        current = []
        current_size = 0

    for chapter_epub in ordered:
        chapter_size = chapter_epub.stat().st_size
        exceeds_count = bool(current and len(current) >= chapter_limit)
        exceeds_size = bool(max_size_bytes is not None and current and current_size + chapter_size > max_size_bytes)
        if exceeds_count or exceeds_size:
            flush_volume()
        current.append(chapter_epub)
        current_size += chapter_size
    flush_volume()

    return {
        "series_title": title,
        "strategy": "chapter_count_and_size" if max_size_bytes is not None else "chapter_count",
        "generated_at": utc_now(),
        "source_chapter_count": len(ordered),
        "limits": {
            "chapters_per_volume": chapters_per_volume,
            "max_volume_size_mb": max_volume_size_mb,
            "max_volume_size_bytes": max_size_bytes,
        },
        "volume_count": len(volumes),
        "total_size_bytes": sum(path.stat().st_size for path in ordered),
        "volumes": volumes,
    }


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
    print(f"[RUN] {' '.join(rendered)}", file=sys.stderr)
    kwargs: dict[str, Any] = {"check": check, "text": True}
    if capture_output:
        kwargs["capture_output"] = True
    else:
        kwargs["stdout"] = sys.stderr
        kwargs["stderr"] = sys.stderr
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


def runtime_kcc_root() -> Path:
    return RUNTIME_DIR / "kcc"


def runtime_kcc_source_dir() -> Path:
    return runtime_kcc_root() / "src"


def runtime_kcc_python_dir() -> Path:
    return runtime_kcc_root() / "venv"


def runtime_kcc_python_path() -> Path:
    return runtime_kcc_python_dir() / "bin" / "python3"


def runtime_kcc_wrapper_path() -> Path:
    return RUNTIME_DIR / "bin" / "kcc-c2e"


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


def packaging_backend(settings: dict[str, Any]) -> str:
    return str(settings.get("packaging", {}).get("backend", "kcc_postprocess")).strip().lower()


def resolve_kcc_command(settings: dict[str, Any], *, auto_bootstrap: bool = True) -> Path | None:
    packaging = settings.get("packaging", {})
    explicit = str(packaging.get("kcc_cmd", "") or "").strip()
    if explicit:
        expanded = Path(explicit).expanduser()
        if expanded.exists():
            return expanded.resolve()
        located = shutil.which(explicit)
        if located:
            return Path(located).resolve()
        if auto_bootstrap:
            raise FileNotFoundError(f"kcc command not found: {explicit}")
        return None

    wrapper = runtime_kcc_wrapper_path()
    if wrapper.exists():
        return wrapper.resolve()

    for candidate in ("kcc-c2e", "comic2ebook"):
        located = shutil.which(candidate)
        if located:
            return Path(located).resolve()

    if auto_bootstrap:
        return bootstrap_kcc_runtime(force=False).resolve()
    return None


def bootstrap_kcc_runtime(force: bool = False) -> Path:
    repo_url = "https://github.com/ciromattia/kcc.git"
    repo_tag = "v9.6.2"
    source_dir = runtime_kcc_source_dir()
    venv_dir = runtime_kcc_python_dir()
    wrapper = runtime_kcc_wrapper_path()

    if force:
        for path in (source_dir, venv_dir):
            if path.exists():
                shutil.rmtree(path)
        if wrapper.exists():
            wrapper.unlink()

    if not source_dir.exists():
        run_command(["git", "clone", "--depth", "1", "--branch", repo_tag, repo_url, source_dir], cwd=PROJECT_ROOT, capture_output=False)

    if not runtime_kcc_python_path().exists():
        run_command([sys.executable, "-m", "venv", venv_dir], cwd=PROJECT_ROOT, capture_output=False)
        run_command([runtime_kcc_python_path(), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=PROJECT_ROOT, capture_output=False)
        run_command(
            [
                runtime_kcc_python_path(),
                "-m",
                "pip",
                "install",
                "packaging",
                "requests",
                "natsort",
                "numpy",
                "distro",
                "python-slugify",
                "PyMuPDF",
                "mozjpeg-lossless-optimization",
                "pillow",
                "psutil",
            ],
            cwd=PROJECT_ROOT,
            capture_output=False,
        )

    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'exec "{runtime_kcc_python_path()}" "{source_dir / "kcc-c2e.py"}" "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def bootstrap_runtime(force: bool = False) -> dict[str, Any]:
    ensure_project_layout()
    settings = load_settings()

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

    kcc_wrapper = None
    if packaging_backend(settings) == "kcc_postprocess":
        kcc_wrapper = bootstrap_kcc_runtime(force=force)

    report = {
        "project_root": str(PROJECT_ROOT),
        "runtime_python": str(runtime_py),
        "runtime_downloader": str(downloader),
        "runtime_kcc": str(kcc_wrapper) if kcc_wrapper else None,
        "settings_path": str(SETTINGS_PATH),
        "subscriptions_path": str(SUBSCRIPTIONS_PATH),
        "bootstrapped_at": utc_now(),
    }
    write_json(RUNTIME_DIR / "bootstrap-report.json", report)
    return report


def ensure_runtime(auto_bootstrap: bool = True) -> dict[str, Path]:
    ensure_project_layout()
    settings = load_settings()
    missing: list[str] = []
    if not runtime_python_path().exists():
        missing.append("runtime python")
    if not runtime_downloader_path().exists():
        missing.append("copymanga-headless-rs")
    kcc_command: Path | None = None
    if packaging_backend(settings) == "kcc_postprocess":
        kcc_command = resolve_kcc_command(settings, auto_bootstrap=False)
        if kcc_command is None:
            missing.append("kcc-c2e")
    if missing:
        if auto_bootstrap:
            bootstrap_runtime()
            if packaging_backend(settings) == "kcc_postprocess":
                kcc_command = resolve_kcc_command(settings, auto_bootstrap=False)
        else:
            raise FileNotFoundError(f"runtime missing: {', '.join(missing)}")
    runtime = {
        "python": runtime_python_path(),
        "downloader": runtime_downloader_path(),
    }
    if kcc_command is not None:
        runtime["kcc"] = kcc_command
    return runtime


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
        "volumes": series_dir / "volumes",
        "meta": series_dir / "series.json",
    }
    for key, path in directories.items():
        if key != "meta":
            path.mkdir(parents=True, exist_ok=True)
    return directories


def read_series_meta(title: str) -> dict[str, Any]:
    layout = ensure_library_layout(title)
    return read_json(
        layout["meta"],
        {
            "title": title,
            "author": None,
            "latest_merged_epub": None,
            "chapter_count": 0,
            "volume_count": 0,
            "latest_split_epubs": [],
        },
    )


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
    settings = load_settings()
    packaging = settings.get("packaging", {})
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
        "preferred_merged_name": render_name_template(
            str(packaging.get("merged_name_template", "{title} 合订版.epub")),
            title=str(metadata.get("name") or selected.get("name") or comic_id),
            series_title=str(metadata.get("name") or selected.get("name") or comic_id),
        ),
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


def _unique_output_name(base_name: str, used_output_names: set[str]) -> str:
    output_name = base_name
    suffix = 2
    while output_name in used_output_names:
        output_name = f"{Path(base_name).stem} ({suffix}).epub"
        suffix += 1
    used_output_names.add(output_name)
    return output_name


def _replace_or_append_xml_tag(text: str, pattern: str, replacement: str, *, container_end: str) -> str:
    flags = re.IGNORECASE | re.DOTALL
    if re.search(pattern, text, flags=flags):
        return re.sub(pattern, replacement, text, count=1, flags=flags)
    container_match = re.search(container_end, text, flags=flags)
    if container_match:
        return text[: container_match.start()] + f"{replacement}\n" + text[container_match.start() :]
    return text


def rewrite_epub_display_metadata(
    epub_path: Path,
    *,
    title: str,
    author: str,
    language: str,
    publisher: str,
    description: str,
) -> None:
    title_xml = xml_escape(title)
    author_xml = xml_escape(author or "Unknown")
    language_xml = xml_escape(language or "zh-Hans")
    publisher_xml = xml_escape(publisher or "Manga Loader Skill")
    description_xml = xml_escape(description or "")

    temp_path = epub_path.with_suffix(".tmp.epub")
    with zipfile.ZipFile(epub_path) as source, zipfile.ZipFile(temp_path, "w") as target:
        opf_name = _opf_path_from_container(source)
        opf_dir = Path(opf_name).parent
        ncx_names = [name for name in source.namelist() if name.lower().endswith(".ncx")]
        nav_names: set[str] = set()
        try:
            opf_root = ET.fromstring(source.read(opf_name).decode("utf-8", errors="ignore"))
            for item in opf_root.iter():
                if item.tag.split("}", 1)[-1] != "item":
                    continue
                href = item.attrib.get("href", "").strip()
                properties = item.attrib.get("properties", "").split()
                if href and "nav" in properties:
                    nav_names.add(str((opf_dir / href).as_posix()).lstrip("./"))
        except ET.ParseError:
            pass

        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == opf_name:
                text = data.decode("utf-8", errors="ignore")
                text = _replace_or_append_xml_tag(
                    text,
                    r"<dc:title\b[^>]*>.*?</dc:title>",
                    f"<dc:title>{title_xml}</dc:title>",
                    container_end=r"</metadata>",
                )
                text = _replace_or_append_xml_tag(
                    text,
                    r"<dc:creator\b[^>]*>.*?</dc:creator>",
                    f"<dc:creator>{author_xml}</dc:creator>",
                    container_end=r"</metadata>",
                )
                text = _replace_or_append_xml_tag(
                    text,
                    r"<dc:language\b[^>]*>.*?</dc:language>",
                    f"<dc:language>{language_xml}</dc:language>",
                    container_end=r"</metadata>",
                )
                text = _replace_or_append_xml_tag(
                    text,
                    r"<dc:publisher\b[^>]*>.*?</dc:publisher>",
                    f"<dc:publisher>{publisher_xml}</dc:publisher>",
                    container_end=r"</metadata>",
                )
                if description_xml:
                    text = _replace_or_append_xml_tag(
                        text,
                        r"<dc:description\b[^>]*>.*?</dc:description>",
                        f"<dc:description>{description_xml}</dc:description>",
                        container_end=r"</metadata>",
                    )
                data = text.encode("utf-8")
            elif info.filename in ncx_names:
                text = data.decode("utf-8", errors="ignore")
                text = re.sub(
                    r"<docTitle>\s*<text>.*?</text>\s*</docTitle>",
                    f"<docTitle><text>{title_xml}</text></docTitle>",
                    text,
                    count=1,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                text = re.sub(
                    r"<docAuthor>\s*<text>.*?</text>\s*</docAuthor>",
                    f"<docAuthor><text>{author_xml}</text></docAuthor>",
                    text,
                    count=1,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                data = text.encode("utf-8")
            elif info.filename in nav_names or info.filename.lower().endswith("/nav.xhtml") or info.filename.lower() == "nav.xhtml":
                text = data.decode("utf-8", errors="ignore")
                text = re.sub(
                    r"<title\b[^>]*>.*?</title>",
                    f"<title>{title_xml}</title>",
                    text,
                    count=1,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                data = text.encode("utf-8")

            compression = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            target.writestr(info.filename, data, compress_type=compression)

    temp_path.replace(epub_path)


def package_chapter_epubs_python_fixed(
    group_dir: Path,
    epubs_root: Path,
    series_title: str,
    author: str,
    *,
    chapter_name_template: str,
    language: str,
    reading_direction: str,
    page_background: str,
    jpeg_quality: int,
    skip_existing: bool = True,
) -> list[Path]:
    epubs_root.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    used_output_names: set[str] = set()
    for chapter_dir in chapter_directories(group_dir):
        chapter_label = chapter_display_label(chapter_dir.name)
        sort_prefix = chapter_sort_prefix(chapter_dir.name)
        base_name = render_name_template(
            chapter_name_template,
            series_title=series_title,
            chapter_label=chapter_label,
            chapter_name=chapter_dir.name,
            chapter_index=str(sort_prefix if sort_prefix is not None else chapter_dir.name),
        )
        output_name = _unique_output_name(base_name, used_output_names)
        output_path = epubs_root / output_name
        if skip_existing and output_path.exists():
            produced.append(output_path)
            continue
        chapter_title = f"{series_title} - {chapter_label}"
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
                "--reading-direction",
                normalize_reading_direction(reading_direction),
                "--series-title",
                series_title,
                "--series-index",
                str(sort_prefix) if sort_prefix is not None else "",
                "--description",
                f"Chapter EPUB generated for {series_title} {chapter_label}.",
                "--publisher",
                "Manga Loader Skill",
                "--page-background",
                page_background,
                "--jpeg-quality",
                str(jpeg_quality),
            ],
            capture_output=False,
        )
        produced.append(output_path)
    return produced


def package_chapter_epubs_kcc_postprocess(
    group_dir: Path,
    epubs_root: Path,
    series_title: str,
    author: str,
    *,
    chapter_name_template: str,
    language: str,
    skip_existing: bool = True,
) -> list[Path]:
    settings = load_settings()
    packaging = settings.get("packaging", {})
    runtime = ensure_runtime()
    kcc_command = Path(runtime["kcc"]) if "kcc" in runtime else resolve_kcc_command(settings)
    if kcc_command is None:
        raise FileNotFoundError("kcc-c2e is required for backend kcc_postprocess")

    profile = str(packaging.get("kcc_profile", "KS") or "KS")
    extra_args = [str(item) for item in packaging.get("kcc_extra_args", []) if str(item).strip()]
    epubs_root.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    used_output_names: set[str] = set()

    for chapter_dir in chapter_directories(group_dir):
        chapter_label = chapter_display_label(chapter_dir.name)
        sort_prefix = chapter_sort_prefix(chapter_dir.name)
        base_name = render_name_template(
            chapter_name_template,
            series_title=series_title,
            chapter_label=chapter_label,
            chapter_name=chapter_dir.name,
            chapter_index=str(sort_prefix if sort_prefix is not None else chapter_dir.name),
        )
        output_name = _unique_output_name(base_name, used_output_names)
        output_path = epubs_root / output_name
        if skip_existing and output_path.exists():
            produced.append(output_path)
            continue

        staged_output = epubs_root / f"{chapter_dir.name}.epub"
        if staged_output.exists() and staged_output != output_path:
            staged_output.unlink()

        command = [
            str(kcc_command),
            "-p",
            profile,
            "-f",
            "EPUB",
            "--nokepub",
            "-n",
            "--forcecolor",
            "-o",
            str(epubs_root),
            str(chapter_dir),
            *extra_args,
        ]
        run_command(command, cwd=PROJECT_ROOT, capture_output=False)

        if not staged_output.exists():
            raise FileNotFoundError(f"kcc output missing for chapter: {chapter_dir} -> {staged_output}")

        if output_path.exists():
            output_path.unlink()
        staged_output.replace(output_path)
        rewrite_epub_display_metadata(
            output_path,
            title=f"{series_title} {chapter_label}",
            author=author,
            language=language,
            publisher="Manga Loader Skill",
            description=f"Chapter EPUB generated for {series_title} {chapter_label}.",
        )
        produced.append(output_path)
    return produced


def package_chapter_epubs(
    group_dir: Path,
    epubs_root: Path,
    series_title: str,
    author: str,
    *,
    chapter_name_template: str,
    language: str,
    reading_direction: str,
    page_background: str,
    jpeg_quality: int,
    skip_existing: bool = True,
) -> list[Path]:
    settings = load_settings()
    backend = packaging_backend(settings)
    if backend == "kcc_postprocess":
        return package_chapter_epubs_kcc_postprocess(
            group_dir,
            epubs_root,
            series_title,
            author,
            chapter_name_template=chapter_name_template,
            language=language,
            skip_existing=skip_existing,
        )
    return package_chapter_epubs_python_fixed(
        group_dir,
        epubs_root,
        series_title,
        author,
        chapter_name_template=chapter_name_template,
        language=language,
        reading_direction=reading_direction,
        page_background=page_background,
        jpeg_quality=jpeg_quality,
        skip_existing=skip_existing,
    )


def merge_chapter_epubs_with_postprocess(
    epub_dir: Path,
    output_path: Path,
    title: str,
    author: str,
    *,
    language: str,
    description: str,
    contributor: str,
    explicit_order: list[str] | None = None,
) -> dict[str, Path | None]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path = output_path.parent / f"{output_path.stem}.plan.json"
    order_path = output_path.parent / f"{output_path.stem}.order.json"

    builder_args: list[str | Path] = [
        "--epub-dir",
        epub_dir,
        "--output",
        output_path,
        "--title",
        title,
        "--author",
        author,
        "--language",
        language,
        "--description",
        description,
        "--contributor",
        contributor,
        "--plan",
        plan_path,
    ]
    if explicit_order:
        write_json(order_path, explicit_order)
        builder_args.extend(["--order-file", order_path])
    elif order_path.exists():
        order_path.unlink()

    run_runtime_python(vendor_merge_plan_builder_path(), builder_args, capture_output=False)
    run_runtime_python(vendor_merge_script_path(), ["--plan", plan_path], capture_output=False)
    rewrite_epub_display_metadata(
        output_path,
        title=title,
        author=author,
        language=language,
        publisher="Manga Loader Skill",
        description=description,
    )
    return {"output": output_path, "plan": plan_path, "order": order_path if explicit_order else None}


def merge_from_downloaded_chapters(
    group_dir: Path,
    output_path: Path,
    title: str,
    author: str,
    *,
    language: str,
    reading_direction: str,
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
            "--reading-direction",
            normalize_reading_direction(reading_direction),
            "--description",
            f"Collected edition EPUB for {title}.",
            "--publisher",
            "Manga Loader Skill",
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


def _stage_chapter_epubs(epub_paths: list[Path], target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    for source in epub_paths:
        destination = target_dir / source.name
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        try:
            destination.symlink_to(source.resolve())
        except OSError:
            shutil.copy2(source, destination)
        staged.append(destination)
    return staged


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
    chapter_epubs = sorted(epub_dir.glob("*.epub"), key=lambda path: natural_key(path.name))
    if not chapter_epubs:
        raise FileNotFoundError(f"no chapter epubs found under: {epub_dir}")

    if packaging_backend(settings) == "kcc_postprocess":
        merge_report = merge_chapter_epubs_with_postprocess(
            epub_dir,
            output_path,
            title,
            author,
            language=language,
            description=description or f"Merged from chapter EPUBs for {title}.",
            contributor=contributor,
            explicit_order=[path.stem for path in chapter_epubs],
        )
        return {"plan": merge_report["plan"], "output": output_path}

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
            reading_direction=str(settings.get("packaging", {}).get("reading_direction", "ltr")),
            page_background=str(settings.get("packaging", {}).get("page_background", "#000000")),
            jpeg_quality=int(settings.get("packaging", {}).get("jpeg_quality", 90)),
        )
    return {"plan": plan_path, "output": output_path}


def rebuild_split_merged_from_epubs(
    epub_dir: Path,
    output_dir: Path,
    title: str,
    author: str,
    *,
    language: str = "zh-Hans",
    description: str = "",
    contributor: str = "manga-loader-skill",
    chapters_per_volume: int | None = None,
    max_volume_size_mb: float | None = None,
    volume_name_template: str = "{title} 第{volume_index:02d}册.epub",
) -> dict[str, Any]:
    chapter_epubs = list_epub_files(epub_dir)
    if not chapter_epubs:
        raise FileNotFoundError(f"no chapter epubs found under: {epub_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    plan = plan_split_volumes(
        chapter_epubs,
        title=title,
        chapters_per_volume=chapters_per_volume,
        max_volume_size_mb=max_volume_size_mb,
        volume_name_template=volume_name_template,
    )
    plan_path = output_dir / f"{safe_path_name(title)}.split-plan.json"
    report_path = output_dir / f"{safe_path_name(title)}.split-report.json"
    write_json(plan_path, plan)

    built_volumes: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="manga-loader-split-", dir=str(RUNTIME_DIR)) as temp_dir:
        staging_root = Path(temp_dir)
        for volume in plan["volumes"]:
            volume_index = int(volume["volume_index"])
            source_paths = [Path(item) for item in volume["chapter_files"]]
            staging_dir = staging_root / f"volume_{volume_index:02d}"
            _stage_chapter_epubs(source_paths, staging_dir)
            output_path = output_dir / str(volume["output_name"])
            rebuilt = rebuild_merged_from_epubs(
                staging_dir,
                output_path,
                str(volume["name"]),
                author,
                language=language,
                description=description or f"{title} 分册合订 EPUB，第{volume_index:02d}册。",
                contributor=contributor,
            )
            validation = validate_epub(output_path)
            audit = audit_epub(output_path, require_fixed_layout=True, require_page_images=True)
            built_volumes.append(
                {
                    **volume,
                    "output_epub": str(output_path),
                    "plan": str(rebuilt["plan"]),
                    "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
                    "validation": validation,
                    "audit": audit,
                    "reader_ready": bool(audit.get("reader_ready")),
                }
            )

    report = {
        "series_title": title,
        "author": author,
        "language": language,
        "description": description or f"{title} 分册合订 EPUB。",
        "plan_path": str(plan_path),
        "report_path": str(report_path),
        "source_epub_dir": str(epub_dir),
        "output_dir": str(output_dir),
        "strategy": plan["strategy"],
        "limits": plan["limits"],
        "source_chapter_count": plan["source_chapter_count"],
        "volume_count": len(built_volumes),
        "total_size_bytes": sum(int(item["size_bytes"]) for item in built_volumes),
        "reader_ready": all(bool(item["reader_ready"]) for item in built_volumes),
        "volumes": built_volumes,
        "generated_at": utc_now(),
    }
    write_json(report_path, report)
    return report


def copy_outputs_to_library(
    title: str,
    epubs_root: Path,
    merged_epub: Path,
    merged_name: str,
    author: str,
    *,
    split_epubs: list[Path] | None = None,
) -> dict[str, Any]:
    layout = ensure_library_layout(title)
    existing_meta = read_series_meta(title)
    chapter_targets: list[str] = []
    volume_targets: list[str] = list(existing_meta.get("latest_split_epubs") or [])
    for existing in layout["chapters"].glob("*.epub"):
        existing.unlink()
    for existing in layout["merged"].glob("*.epub"):
        existing.unlink()
    for source in sorted(epubs_root.glob("*.epub"), key=lambda path: natural_key(path.name)):
        destination = layout["chapters"] / source.name
        shutil.copy2(source, destination)
        chapter_targets.append(str(destination))
    merged_target = layout["merged"] / merged_name
    if merged_target.exists():
        merged_target.unlink()
    shutil.copy2(merged_epub, merged_target)
    if split_epubs is not None:
        volume_targets = []
        for existing in layout["volumes"].glob("*.epub"):
            existing.unlink()
        for source in sorted(split_epubs, key=lambda path: natural_key(path.name)):
            destination = layout["volumes"] / source.name
            shutil.copy2(source, destination)
            volume_targets.append(str(destination))
    series_meta = {
        "title": title,
        "author": author,
        "latest_merged_epub": str(merged_target),
        "chapter_count": len(chapter_targets),
        "volume_count": len(volume_targets),
        "latest_split_epubs": volume_targets,
        "updated_at": utc_now(),
    }
    write_json(layout["meta"], series_meta)
    return {
        "series_dir": str(layout["series"]),
        "chapter_count": len(chapter_targets),
        "merged_epub": str(merged_target),
        "volumes_dir": str(layout["volumes"]),
        "volume_count": len(volume_targets),
        "split_epubs": volume_targets,
    }


def copy_split_outputs_to_library(title: str, split_epubs: list[Path], author: str) -> dict[str, Any]:
    layout = ensure_library_layout(title)
    existing_meta = read_series_meta(title)
    volume_targets: list[str] = []
    for existing in layout["volumes"].glob("*.epub"):
        existing.unlink()
    for source in sorted(split_epubs, key=lambda path: natural_key(path.name)):
        destination = layout["volumes"] / source.name
        shutil.copy2(source, destination)
        volume_targets.append(str(destination))
    series_meta = {
        "title": title,
        "author": author,
        "latest_merged_epub": existing_meta.get("latest_merged_epub"),
        "chapter_count": int(existing_meta.get("chapter_count") or 0),
        "volume_count": len(volume_targets),
        "latest_split_epubs": volume_targets,
        "updated_at": utc_now(),
    }
    write_json(layout["meta"], series_meta)
    return {
        "series_dir": str(layout["series"]),
        "volumes_dir": str(layout["volumes"]),
        "volume_count": len(volume_targets),
        "split_epubs": volume_targets,
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
    split_chapters_per_volume: int | None = None,
    split_max_size_mb: float | None = None,
    split_name_template: str | None = None,
) -> dict[str, Any]:
    settings = load_settings()
    packaging = settings.get("packaging", {})
    ensure_runtime()
    job_root.mkdir(parents=True, exist_ok=True)
    remote_chapters = fetch_chapters(comic_id, group)

    downloads_root = job_root / "downloads"
    epubs_root = job_root / "epubs"
    merged_root = job_root / "merged"
    if downloads_root.exists():
        shutil.rmtree(downloads_root)
    epubs_root.mkdir(parents=True, exist_ok=True)
    merged_root.mkdir(parents=True, exist_ok=True)
    for stale_epub in epubs_root.glob("*.epub"):
        stale_epub.unlink()
    for stale_epub in merged_root.glob("*.epub"):
        stale_epub.unlink()

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
        chapter_name_template=str(packaging.get("chapter_name_template", "{series_title} {chapter_label}.epub")),
        language=str(settings.get("language", "zh-Hans")),
        reading_direction=str(packaging.get("reading_direction", "ltr")),
        page_background=str(packaging.get("page_background", "#000000")),
        jpeg_quality=int(packaging.get("jpeg_quality", 90)),
        skip_existing=True,
    )
    merged_file_name = merged_name or render_name_template(
        str(packaging.get("merged_name_template", "{title} 合订版.epub")),
        title=title,
        series_title=title,
    )
    merged_target_path = merged_root / merged_file_name
    backend = packaging_backend(settings)
    if backend == "kcc_postprocess":
        merge_report = merge_chapter_epubs_with_postprocess(
            epubs_root,
            merged_target_path,
            title,
            author,
            language=str(settings.get("language", "zh-Hans")),
            description=f"Collected edition EPUB for {title}.",
            contributor="manga-loader-skill",
            explicit_order=[path.stem for path in chapter_epubs],
        )
        merged_epub = Path(merge_report["output"] or merged_target_path)
    else:
        merged_epub = merge_from_downloaded_chapters(
            group_dir,
            merged_target_path,
            title,
            author,
            language=str(settings.get("language", "zh-Hans")),
            reading_direction=str(packaging.get("reading_direction", "ltr")),
            page_background=str(packaging.get("page_background", "#000000")),
            jpeg_quality=int(packaging.get("jpeg_quality", 90)),
        )
    validation = validate_epub(merged_epub)
    audit = audit_epub(merged_epub, require_fixed_layout=True, require_page_images=True)

    split_report: dict[str, Any] | None = None
    split_epubs: list[Path] = []
    effective_split_chapters = split_chapters_per_volume or int(packaging.get("split_chapters_per_volume", 40) or 40)
    effective_split_template = split_name_template or str(packaging.get("split_name_template", "{title} 第{volume_index:02d}册.epub"))
    if split_chapters_per_volume is not None or split_max_size_mb is not None:
        split_root = job_root / "volumes"
        split_report = rebuild_split_merged_from_epubs(
            epubs_root,
            split_root,
            title,
            author,
            language=str(settings.get("language", "zh-Hans")),
            description=f"{title} 分册合订 EPUB。",
            contributor="manga-loader-skill",
            chapters_per_volume=effective_split_chapters,
            max_volume_size_mb=split_max_size_mb,
            volume_name_template=effective_split_template,
        )
        split_epubs = [Path(item["output_epub"]) for item in split_report["volumes"]]

    library_copy = copy_outputs_to_library(
        title,
        epubs_root,
        merged_epub,
        merged_file_name,
        author,
        split_epubs=split_epubs,
    )

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
        "packaging_backend": backend,
        "chapter_epub_count": len(chapter_epubs),
        "merged_epub": str(merged_epub),
        "library": library_copy,
        "validation": validation,
        "audit": audit,
        "split": split_report,
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
        merged_name=str(record.get("preferred_merged_name") or ""),
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
            "page_progression_direction": None,
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
        spine = opf_root.find("opf:spine", ns)
        if spine is not None:
            report["metadata"]["page_progression_direction"] = spine.attrib.get("page-progression-direction")
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


def epub_page_breakdown(path: Path) -> dict[str, Any]:
    report = {
        "path": str(path),
        "exists": path.exists(),
        "spine_total": 0,
        "reading_pages": 0,
        "cover_pages": 0,
        "nav_pages": 0,
        "image_assets": 0,
        "page_spread_left": 0,
        "page_spread_right": 0,
        "page_progression_direction": None,
    }
    if not path.exists():
        return report

    with zipfile.ZipFile(path) as zf:
        opf_path = _opf_path_from_container(zf)
        opf_root = ET.fromstring(zf.read(opf_path).decode("utf-8", errors="ignore"))
        opf_dir = Path(opf_path).parent
        manifest = next((node for node in opf_root if _local_xml_name(node.tag) == "manifest"), None)
        spine = next((node for node in opf_root if _local_xml_name(node.tag) == "spine"), None)
        manifest_map: dict[str, tuple[str, set[str]]] = {}

        for item in manifest or []:
            if _local_xml_name(item.tag) != "item":
                continue
            item_id = item.attrib.get("id", "").strip()
            href = item.attrib.get("href", "").strip()
            if not item_id or not href:
                continue
            manifest_map[item_id] = (str((opf_dir / href).as_posix()).lstrip("./"), set(item.attrib.get("properties", "").split()))

        report["image_assets"] = len(
            [name for name in zf.namelist() if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")) and not name.startswith("META-INF/")]
        )

        if spine is None:
            return report

        report["page_progression_direction"] = spine.attrib.get("page-progression-direction")
        for itemref in spine:
            if _local_xml_name(itemref.tag) != "itemref":
                continue
            idref = itemref.attrib.get("idref", "").strip()
            manifest_item = manifest_map.get(idref)
            if manifest_item is None:
                continue
            href, properties = manifest_item
            name = Path(href).name.lower()
            report["spine_total"] += 1
            itemref_props = set(itemref.attrib.get("properties", "").split())
            if "page-spread-left" in itemref_props:
                report["page_spread_left"] += 1
            if "page-spread-right" in itemref_props:
                report["page_spread_right"] += 1
            if "nav" in properties or name == "nav.xhtml":
                report["nav_pages"] += 1
            elif name == "cover.xhtml":
                report["cover_pages"] += 1
            elif href.lower().endswith((".xhtml", ".html", ".htm")):
                report["reading_pages"] += 1

    report["non_spine_image_assets"] = report["image_assets"] - report["reading_pages"]
    report["spine_minus_reading_pages"] = report["spine_total"] - report["reading_pages"]
    return report


def compare_page_counts(
    chapter_epub_dir: Path,
    *,
    merged_path: Path | None = None,
    volumes_dir: Path | None = None,
) -> dict[str, Any]:
    chapter_epubs = list_epub_files(chapter_epub_dir)
    if not chapter_epubs:
        raise FileNotFoundError(f"no chapter epubs found under: {chapter_epub_dir}")

    chapter_reports = [epub_page_breakdown(path) for path in chapter_epubs]
    chapter_totals = {
        "chapter_count": len(chapter_reports),
        "spine_total": sum(int(item["spine_total"]) for item in chapter_reports),
        "reading_pages": sum(int(item["reading_pages"]) for item in chapter_reports),
        "cover_pages": sum(int(item["cover_pages"]) for item in chapter_reports),
        "nav_pages": sum(int(item["nav_pages"]) for item in chapter_reports),
        "image_assets": sum(int(item["image_assets"]) for item in chapter_reports),
    }

    report: dict[str, Any] = {
        "chapter_epub_dir": str(chapter_epub_dir),
        "chapter_totals": chapter_totals,
    }

    if merged_path is not None:
        merged = epub_page_breakdown(merged_path)
        report["merged"] = {
            **merged,
            "delta_vs_source_reading_pages": int(merged["reading_pages"]) - chapter_totals["reading_pages"],
            "delta_vs_source_spine_total": int(merged["spine_total"]) - chapter_totals["reading_pages"],
        }

    if volumes_dir is not None:
        volume_reports = [epub_page_breakdown(path) for path in list_epub_files(volumes_dir)]
        report["volumes"] = {
            "volume_count": len(volume_reports),
            "items": volume_reports,
            "reading_pages_total": sum(int(item["reading_pages"]) for item in volume_reports),
            "spine_total": sum(int(item["spine_total"]) for item in volume_reports),
            "cover_pages_total": sum(int(item["cover_pages"]) for item in volume_reports),
            "delta_vs_source_reading_pages": sum(int(item["reading_pages"]) for item in volume_reports) - chapter_totals["reading_pages"],
            "delta_vs_source_spine_total": sum(int(item["spine_total"]) for item in volume_reports) - chapter_totals["reading_pages"],
        }

    return report


def _local_xml_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _opf_navigation_paths(opf_path: Path) -> tuple[Path | None, list[Path]]:
    opf_root = ET.fromstring(opf_path.read_text(encoding="utf-8", errors="ignore"))
    manifest = next((node for node in opf_root if _local_xml_name(node.tag) == "manifest"), None)
    spine = next((node for node in opf_root if _local_xml_name(node.tag) == "spine"), None)
    if manifest is None:
        raise ValueError(f"manifest missing in opf: {opf_path}")

    manifest_hrefs: dict[str, Path] = {}
    nav_path: Path | None = None
    for item in manifest:
        if _local_xml_name(item.tag) != "item":
            continue
        item_id = item.attrib.get("id", "").strip()
        href = item.attrib.get("href", "").strip()
        if not item_id or not href:
            continue
        resolved = (opf_path.parent / href).resolve()
        manifest_hrefs[item_id] = resolved
        properties = item.attrib.get("properties", "").split()
        if "nav" in properties:
            nav_path = resolved
        elif nav_path is None and Path(href).name.lower() == "nav.xhtml":
            nav_path = resolved

    page_paths: list[Path] = []
    if spine is not None:
        for itemref in spine:
            if _local_xml_name(itemref.tag) != "itemref":
                continue
            idref = itemref.attrib.get("idref", "").strip()
            resolved = manifest_hrefs.get(idref)
            if resolved and resolved.suffix.lower() in {".xhtml", ".html", ".htm"}:
                page_paths.append(resolved)

    if not page_paths:
        page_paths = sorted(
            [item for item in opf_path.parent.rglob("*.xhtml") if item.is_file() and item.name.lower() != "nav.xhtml"],
            key=lambda item: natural_key(str(item.relative_to(opf_path.parent))),
        )
    return nav_path, page_paths


def _viewport_for_page(page_path: Path) -> tuple[int, int]:
    text = page_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'<meta name="viewport" content="width=(\d+), height=(\d+)"', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    raw_image = _find_embedded_image(page_path)
    if raw_image and raw_image.exists():
        with Image.open(raw_image) as image:
            return image.width, image.height
    return 1600, 2400


def _find_embedded_image(page_path: Path) -> Path | None:
    text = page_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', text, flags=re.IGNORECASE)
    if not match:
        return None
    return (page_path.parent / match.group(1)).resolve()


def preview_epub(path: Path, output_dir: Path, pages: list[int] | None = None) -> dict[str, Any]:
    path = path.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    extract_dir = output_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)

    browser = shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chromium-browser")
    if not browser:
        raise FileNotFoundError("chromium not found; cannot render epub preview screenshots")

    with zipfile.ZipFile(path) as zf:
        zf.extractall(extract_dir)
        opf_rel = _opf_path_from_container(zf)

    opf_path = extract_dir / opf_rel
    nav_path, page_paths = _opf_navigation_paths(opf_path)
    if not page_paths:
        raise FileNotFoundError(f"no page xhtml files found in epub: {path}")

    if pages:
        selected_pages = [index for index in pages if 0 <= index < len(page_paths)]
    else:
        selected_pages = sorted({0, 1 if len(page_paths) > 1 else 0, len(page_paths) - 1})

    screenshots_dir = output_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    nav_shot = screenshots_dir / "nav.png"
    if nav_path and nav_path.exists():
        run_command(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--allow-file-access-from-files",
                "--hide-scrollbars",
                "--window-size=1400,2200",
                f"--screenshot={nav_shot}",
                nav_path.as_uri(),
            ],
            cwd=PROJECT_ROOT,
            capture_output=False,
        )

    page_reports: list[dict[str, Any]] = []
    for page_index in selected_pages:
        page_path = page_paths[page_index]
        width, height = _viewport_for_page(page_path)
        screenshot_path = screenshots_dir / f"{page_path.stem}.png"
        run_command(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--allow-file-access-from-files",
                "--hide-scrollbars",
                f"--window-size={width},{height}",
                f"--screenshot={screenshot_path}",
                page_path.as_uri(),
            ],
            cwd=PROJECT_ROOT,
            capture_output=False,
        )
        raw_image = _find_embedded_image(page_path)
        page_reports.append(
            {
                "page_index": page_index,
                "page_xhtml": str(page_path),
                "raw_image": str(raw_image) if raw_image else None,
                "viewport": {"width": width, "height": height},
                "screenshot": str(screenshot_path),
            }
        )

    report = {
        "epub": str(path),
        "output_dir": str(output_dir),
        "extract_dir": str(extract_dir),
        "opf_path": str(opf_path),
        "nav_path": str(nav_path) if nav_path and nav_path.exists() else None,
        "nav_screenshot": str(nav_shot) if nav_shot.exists() else None,
        "page_count": len(page_paths),
        "selected_pages": selected_pages,
        "validation": validate_epub(path),
        "pages": page_reports,
    }
    write_json(output_dir / "preview-report.json", report)
    return report


def latest_run_report_path() -> Path | None:
    candidates = [path for path in RUNS_DIR.rglob("report.json") if path.is_file()]
    candidates.extend(path for path in RUNS_DIR.rglob("*.split-report.json") if path.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def latest_library_merged_epubs() -> list[Path]:
    candidates = [path.resolve() for path in LIBRARY_DIR.glob("*/merged/*.epub") if path.is_file()]
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _latest_epub_targets_from_report(report_path: Path | None) -> tuple[list[Path], dict[str, Any]]:
    if report_path is None or not report_path.exists():
        return [], {}
    payload = read_json(report_path, {})
    candidates: list[str] = []
    if payload.get("merged_epub"):
        candidates.append(str(payload.get("merged_epub")))
    library_merged = (payload.get("library") or {}).get("merged_epub")
    if library_merged:
        candidates.append(str(library_merged))
    for item in payload.get("volumes") or []:
        output_epub = item.get("output_epub")
        if output_epub:
            candidates.append(str(output_epub))

    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate:
            path = Path(candidate).expanduser().resolve()
            key = str(path)
            if key not in seen:
                seen.add(key)
                resolved.append(path)
    return resolved, payload


def _doctor_audit_entry(path: Path, source: str) -> dict[str, Any]:
    validation = validate_epub(path)
    audit = audit_epub(path, require_fixed_layout=True, require_page_images=True)
    status = "fail" if (not validation["valid"] or audit["errors"]) else "warn" if audit["warnings"] else "ok"
    return {
        "path": str(path),
        "source": source,
        "status": status,
        "reader_ready": bool(audit.get("reader_ready")),
        "validation": validation,
        "audit": audit,
    }


def doctor_report(
    check_network: bool = False,
    query: str = "葬送的芙莉莲",
    *,
    audit_paths: list[Path] | None = None,
    audit_library: bool = False,
    audit_latest: bool = True,
) -> dict[str, Any]:
    ensure_project_layout()
    settings = load_settings()
    subscriptions = load_subscriptions()
    packaging = settings.get("packaging", {})
    backend = packaging_backend(settings)
    supported_backends = {"kcc_postprocess", "python_fixed"}
    latest_report = latest_run_report_path()
    latest_epub_targets, latest_report_payload = _latest_epub_targets_from_report(latest_report)
    kcc_command = resolve_kcc_command(settings, auto_bootstrap=False) if backend == "kcc_postprocess" else None

    hard_failures: list[str] = []
    warnings: list[str] = []
    audits: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add_target(path: Path | None, source: str) -> None:
        if path is None:
            return
        resolved = path.expanduser().resolve()
        key = str(resolved)
        if key in seen_paths:
            return
        seen_paths.add(key)
        audits.append(_doctor_audit_entry(resolved, source))

    report = {
        "project_root": str(PROJECT_ROOT),
        "settings_path": str(SETTINGS_PATH),
        "subscriptions_path": str(SUBSCRIPTIONS_PATH),
        "subscriptions_count": len(subscriptions),
        "library_dir": str(LIBRARY_DIR),
        "runs_dir": str(RUNS_DIR),
        "packaging": {
            "backend": backend,
            "backend_supported": backend in supported_backends,
            "chapter_name_template": str(packaging.get("chapter_name_template", "{series_title} {chapter_label}.epub")),
            "merged_name_template": str(packaging.get("merged_name_template", "{title} 合订版.epub")),
            "split_name_template": str(packaging.get("split_name_template", "{title} 第{volume_index:02d}册.epub")),
            "split_chapters_per_volume": int(packaging.get("split_chapters_per_volume", 40) or 40),
            "reading_direction": str(packaging.get("reading_direction", "ltr")),
            "kcc_profile": str(packaging.get("kcc_profile", "KS")),
            "kcc_cmd_configured": str(packaging.get("kcc_cmd", "") or ""),
            "kcc_cmd_resolved": str(kcc_command) if kcc_command else None,
        },
        "vendor": {
            "downloader_binary": str(vendor_downloader_binary_path()),
            "downloader_binary_exists": vendor_downloader_binary_path().exists(),
            "downloader_source": str(vendor_downloader_source_dir()),
            "downloader_source_exists": vendor_downloader_source_dir().exists(),
            "merge_plan_builder": str(vendor_merge_plan_builder_path()),
            "merge_plan_builder_exists": vendor_merge_plan_builder_path().exists(),
            "merge_script": str(vendor_merge_script_path()),
            "merge_script_exists": vendor_merge_script_path().exists(),
        },
        "runtime": {
            "python": str(runtime_python_path()),
            "python_exists": runtime_python_path().exists(),
            "downloader": str(runtime_downloader_path()),
            "downloader_exists": runtime_downloader_path().exists(),
            "kcc": str(kcc_command) if kcc_command else None,
            "kcc_exists": bool(kcc_command and kcc_command.exists()),
        },
        "latest_job_root": str(latest_report.parent) if latest_report else None,
        "latest_report_path": str(latest_report) if latest_report else None,
        "latest_report_summary": {
            "merged_epub": latest_report_payload.get("merged_epub"),
            "chapter_epub_count": latest_report_payload.get("chapter_epub_count"),
            "packaging_backend": latest_report_payload.get("packaging_backend"),
            "completed_at": latest_report_payload.get("completed_at"),
            "volume_count": latest_report_payload.get("volume_count"),
        }
        if latest_report_payload
        else None,
        "latest_merged_epub": str(latest_epub_targets[0]) if latest_epub_targets else None,
        "latest_epub_targets": [str(path) for path in latest_epub_targets],
    }

    if backend not in supported_backends:
        _append_unique(hard_failures, f"unsupported_packaging_backend:{backend}")
    if not runtime_python_path().exists():
        _append_unique(hard_failures, "runtime_python_missing")
    if not runtime_downloader_path().exists():
        _append_unique(hard_failures, "runtime_downloader_missing")
    if backend == "kcc_postprocess" and kcc_command is None:
        _append_unique(hard_failures, "kcc_command_missing")
    if not vendor_merge_plan_builder_path().exists():
        _append_unique(hard_failures, "merge_plan_builder_missing")
    if not vendor_merge_script_path().exists():
        _append_unique(hard_failures, "merge_script_missing")
    if not subscriptions:
        _append_unique(warnings, "subscriptions_empty")

    for candidate in audit_paths or []:
        add_target(candidate, "explicit")
    if audit_latest:
        for candidate in latest_epub_targets:
            add_target(candidate, "latest")
    if audit_library:
        for candidate in latest_library_merged_epubs():
            add_target(candidate, "library")
    if not audits:
        _append_unique(warnings, "no_audit_targets_found")

    for entry in audits:
        if entry["status"] == "fail":
            _append_unique(hard_failures, f"epub_audit_failed:{Path(entry['path']).name}")
        for warning in entry["audit"]["warnings"]:
            _append_unique(warnings, f"{warning}:{Path(entry['path']).name}")

    latest_audit = next((entry for entry in audits if entry["source"] == "latest"), audits[0] if audits else None)

    if check_network:
        try:
            resolved = resolve_query(query)
            report["network_probe"] = {
                "query": query,
                "selected": resolved["selected"],
                "candidate_count": len(resolved["candidates"]),
            }
        except Exception as exc:  # noqa: BLE001
            report["network_probe"] = {"query": query, "error": f"{type(exc).__name__}: {exc}"}
            _append_unique(warnings, "network_probe_failed")

    status = "fail" if hard_failures else "warn" if warnings else "ok"
    report["hard_failures"] = hard_failures
    report["warnings"] = warnings
    report["status"] = status
    report["reader_ready"] = all(bool(entry["reader_ready"]) for entry in audits) if audits else False
    report["audits"] = audits
    report["audit_count"] = len(audits)
    report["latest_status"] = latest_audit["status"] if latest_audit else "warn" if warnings else status
    report["latest_audit"] = latest_audit

    if latest_audit:
        report["epub_metadata"] = latest_audit["audit"]["metadata"]
        report["manifest_summary"] = latest_audit["audit"]["manifest"]
        report["spine_summary"] = latest_audit["audit"]["spine"]
        report["pages_summary"] = latest_audit["audit"]["pages"]
    else:
        report["epub_metadata"] = None
        report["manifest_summary"] = None
        report["spine_summary"] = None
        report["pages_summary"] = None

    write_json(RUNTIME_DIR / "doctor-report.json", report)
    return report
