#!/usr/bin/env python3
from __future__ import annotations

import json
import posixpath
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
CONT_NS = "urn:oasis:names:tc:opendocument:xmlns:container"


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _norm(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/")).lstrip("./")


def _read_text(zf: zipfile.ZipFile, name: str) -> str:
    return zf.read(name).decode("utf-8", errors="ignore")


def _opf_path_from_container(zf: zipfile.ZipFile) -> str:
    root = ET.fromstring(zf.read("META-INF/container.xml"))
    rootfile = root.find(f".//{{{CONT_NS}}}rootfile")
    if rootfile is None:
        raise ValueError("container.xml missing rootfile")
    full_path = rootfile.attrib.get("full-path", "").strip()
    if not full_path:
        raise ValueError("container.xml rootfile missing full-path")
    return full_path


def _first_text(parent: ET.Element | None, tag: str) -> str | None:
    if parent is None:
        return None
    for child in parent:
        if _local(child.tag) == tag and child.text:
            text = child.text.strip()
            if text:
                return text
    return None


def _metadata_summary(metadata: ET.Element | None) -> dict[str, Any]:
    summary = {
        "title": None,
        "creators": [],
        "language": None,
        "publisher": None,
        "description": None,
        "fixed_layout": None,
        "book_type": None,
        "primary_writing_mode": None,
        "rendition_layout": None,
        "rendition_spread": None,
        "dcterms_modified": None,
    }
    if metadata is None:
        return summary

    summary["title"] = _first_text(metadata, "title")
    summary["language"] = _first_text(metadata, "language")
    summary["publisher"] = _first_text(metadata, "publisher")
    summary["description"] = _first_text(metadata, "description")

    creators: list[str] = []
    for child in metadata:
        if _local(child.tag) == "creator" and child.text and child.text.strip():
            creators.append(child.text.strip())
    summary["creators"] = creators

    for meta in metadata:
        if _local(meta.tag) != "meta":
            continue
        name = (meta.attrib.get("name") or "").strip().lower()
        prop = (meta.attrib.get("property") or "").strip().lower()
        value = (meta.attrib.get("content") or meta.text or "").strip() or None
        if name == "fixed-layout":
            summary["fixed_layout"] = value
        elif name == "book-type":
            summary["book_type"] = value
        elif name == "primary-writing-mode":
            summary["primary_writing_mode"] = value
        elif prop == "rendition:layout":
            summary["rendition_layout"] = value
        elif prop == "rendition:spread":
            summary["rendition_spread"] = value
        elif prop == "dcterms:modified":
            summary["dcterms_modified"] = value
    return summary


def audit_epub(
    path: str | Path,
    *,
    require_fixed_layout: bool = False,
    require_page_images: bool = False,
) -> dict[str, Any]:
    started = time.time()
    epub_path = Path(path).resolve()
    report: dict[str, Any] = {
        "path": str(epub_path),
        "exists": epub_path.exists(),
        "errors": [],
        "warnings": [],
        "metadata": {},
        "manifest": {
            "items": 0,
            "nav_hrefs": [],
            "cover_image_hrefs": [],
            "missing_hrefs": [],
        },
        "spine": {
            "count": 0,
            "page_progression_direction": None,
            "missing_idrefs": [],
            "page_spread_left": 0,
            "page_spread_right": 0,
        },
        "pages": {
            "count": 0,
            "with_viewport": 0,
            "with_images": 0,
            "sample": [],
        },
        "toc": {
            "ncx_entries": 0,
            "nav_entries": 0,
        },
        "reader_ready": False,
        "duration_sec": 0.0,
    }
    if not epub_path.exists():
        report["errors"].append("epub_not_found")
        return report

    try:
        with zipfile.ZipFile(epub_path) as zf:
            names = set(zf.namelist())
            report["entry_count"] = len(names)
            opf_path = _opf_path_from_container(zf)
            report["opf_path"] = opf_path
            opf_xml = _read_text(zf, opf_path)
            opf_root = ET.fromstring(opf_xml)
            report["package_version"] = opf_root.attrib.get("version")
            report["package_prefix"] = opf_root.attrib.get("prefix")

            manifest = next((node for node in opf_root if _local(node.tag) == "manifest"), None)
            spine = next((node for node in opf_root if _local(node.tag) == "spine"), None)
            metadata = next((node for node in opf_root if _local(node.tag) == "metadata"), None)
            if manifest is None:
                report["errors"].append("manifest_missing")
            if spine is None:
                report["errors"].append("spine_missing")

            report["metadata"] = _metadata_summary(metadata)
            opf_dir = Path(opf_path).parent

            manifest_by_id: dict[str, dict[str, Any]] = {}
            if manifest is not None:
                for item in manifest:
                    if _local(item.tag) != "item":
                        continue
                    item_id = item.attrib.get("id", "").strip()
                    href = item.attrib.get("href", "").strip()
                    media_type = item.attrib.get("media-type", "").strip()
                    properties = item.attrib.get("properties", "").split()
                    if not item_id or not href:
                        continue
                    member = _norm(str((opf_dir / href).as_posix()))
                    manifest_by_id[item_id] = {
                        "href": member,
                        "media_type": media_type,
                        "properties": properties,
                    }
                    report["manifest"]["items"] += 1
                    if "nav" in properties:
                        report["manifest"]["nav_hrefs"].append(member)
                    if "cover-image" in properties:
                        report["manifest"]["cover_image_hrefs"].append(member)
                    if member not in names:
                        report["manifest"]["missing_hrefs"].append(member)

            page_hrefs: list[str] = []
            if spine is not None:
                report["spine"]["page_progression_direction"] = spine.attrib.get("page-progression-direction")
                for itemref in spine:
                    if _local(itemref.tag) != "itemref":
                        continue
                    idref = itemref.attrib.get("idref", "").strip()
                    if not idref:
                        continue
                    manifest_item = manifest_by_id.get(idref)
                    if manifest_item is None:
                        report["spine"]["missing_idrefs"].append(idref)
                        continue
                    href = str(manifest_item["href"])
                    page_hrefs.append(href)
                    props = itemref.attrib.get("properties", "").split()
                    if "page-spread-left" in props:
                        report["spine"]["page_spread_left"] += 1
                    if "page-spread-right" in props:
                        report["spine"]["page_spread_right"] += 1
                report["spine"]["count"] = len(page_hrefs)

            sample_pages: list[dict[str, Any]] = []
            for index, href in enumerate(page_hrefs):
                if not href.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                if Path(href).name.lower() == "cover.xhtml":
                    continue
                text = _read_text(zf, href)
                has_viewport = bool(re.search(r'<meta[^>]+name=["\']viewport["\']', text, flags=re.IGNORECASE))
                image_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', text, flags=re.IGNORECASE)
                has_image = image_match is not None
                if has_viewport:
                    report["pages"]["with_viewport"] += 1
                if has_image:
                    report["pages"]["with_images"] += 1
                if index < 5:
                    sample_pages.append(
                        {
                            "href": href,
                            "has_viewport": has_viewport,
                            "has_image": has_image,
                        }
                    )
            report["pages"]["count"] = len(
                [
                    href
                    for href in page_hrefs
                    if href.lower().endswith((".xhtml", ".html", ".htm")) and Path(href).name.lower() != "cover.xhtml"
                ]
            )
            report["pages"]["sample"] = sample_pages

            if "toc.ncx" in names:
                ncx_text = _read_text(zf, "toc.ncx")
                report["toc"]["ncx_entries"] = len(re.findall(r"<navPoint\b", ncx_text, flags=re.IGNORECASE))
            nav_entries = 0
            for nav_href in report["manifest"]["nav_hrefs"]:
                if nav_href in names:
                    nav_text = _read_text(zf, nav_href)
                    nav_entries += len(re.findall(r"<a\b", nav_text, flags=re.IGNORECASE))
            report["toc"]["nav_entries"] = nav_entries
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(f"audit_exception:{type(exc).__name__}:{exc}")

    metadata = report["metadata"]
    if require_fixed_layout:
        if report.get("package_version") != "3.0":
            report["errors"].append("package_not_epub3")
        if metadata.get("rendition_layout") != "pre-paginated":
            report["errors"].append("rendition_layout_missing")
        if not metadata.get("rendition_spread"):
            report["errors"].append("rendition_spread_missing")
        if report["spine"]["page_progression_direction"] not in {"ltr", "rtl"}:
            report["errors"].append("page_progression_direction_missing")
        if not report["manifest"]["nav_hrefs"]:
            report["errors"].append("nav_document_missing")
        if metadata.get("fixed_layout") != "true":
            report["warnings"].append("fixed_layout_meta_missing")
        if metadata.get("book_type") != "comic":
            report["warnings"].append("book_type_missing")
        if not metadata.get("primary_writing_mode"):
            report["warnings"].append("primary_writing_mode_missing")
    if require_page_images:
        if report["pages"]["count"] == 0:
            report["errors"].append("no_spine_pages")
        if report["pages"]["with_images"] != report["pages"]["count"]:
            report["errors"].append("page_image_missing")
        if report["pages"]["with_viewport"] != report["pages"]["count"]:
            report["errors"].append("viewport_missing")
    if report["manifest"]["missing_hrefs"]:
        report["errors"].append("manifest_href_missing")
    if report["spine"]["missing_idrefs"]:
        report["errors"].append("spine_idref_missing")
    if not metadata.get("title"):
        report["errors"].append("title_missing")
    if not metadata.get("creators"):
        report["errors"].append("creator_missing")
    if not metadata.get("language"):
        report["errors"].append("language_missing")

    report["reader_ready"] = not report["errors"]
    report["duration_sec"] = round(time.time() - started, 4)
    return report


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
