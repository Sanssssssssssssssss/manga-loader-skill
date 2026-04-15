#!/usr/bin/env python3
"""Merge chapter EPUBs into one EPUB2 anthology ordered by provided plan."""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import sys
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
CONT_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
EPUB_NS = "http://www.idpf.org/2007/ops"

ET.register_namespace("", OPF_NS)
ET.register_namespace("dc", DC_NS)
ET.register_namespace("opf", OPF_NS)


class MergeError(RuntimeError):
    pass


@dataclass
class ChapterPlan:
    chapter_name: str
    order: Optional[float]
    epub_path: str


@dataclass
class MergePlan:
    output_epub_path: str
    title: str
    author: str
    language: str
    description: str
    contributor: str
    chapters: List[ChapterPlan]


@dataclass
class LayoutProfile:
    rendition_layout: str = "pre-paginated"
    rendition_spread: str = "none"
    page_progression_direction: str = "ltr"
    fixed_layout: str = "true"
    book_type: str = "comic"
    primary_writing_mode: str = "horizontal-lr"


@dataclass
class ManifestItemRecord:
    item_id: str
    href: str
    media_type: str
    properties: Optional[str] = None


@dataclass
class SpineItemRecord:
    idref: str
    properties: Optional[str] = None


def _ns(tag: str, ns: str) -> str:
    """Build a namespaced XML tag string."""
    return f"{{{ns}}}{tag}"


def _local(tag: str) -> str:
    """Extract local name from an XML tag."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _read_text(zf: zipfile.ZipFile, name: str) -> str:
    """Read a UTF-8 text entry from a zip, raising MergeError when missing."""
    try:
        return zf.read(name).decode("utf-8")
    except KeyError as exc:
        raise MergeError(f"missing entry in epub: {name}") from exc


def _find_rootfile_path(container_xml: str) -> str:
    """Resolve OPF path from EPUB container.xml."""
    root = ET.fromstring(container_xml)
    rootfile = root.find(f".//{{{CONT_NS}}}rootfile")
    if rootfile is None:
        rootfile = root.find(".//rootfile")
    if rootfile is None:
        raise MergeError("container.xml missing rootfile")
    full_path = rootfile.attrib.get("full-path", "").strip()
    if not full_path:
        raise MergeError("container.xml rootfile missing full-path")
    return full_path


def _norm(path: str) -> str:
    """Normalize to stable POSIX-style relative path."""
    return posixpath.normpath(path.replace("\\", "/"))


def _safe_id(raw: str) -> str:
    """Sanitize id values so merged OPF ids stay XML-safe."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw) or "id"


def _media_type_from_href(href: str) -> Optional[str]:
    """Infer media type from href extension when possible."""
    ext = Path(href).suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".gif":
        return "image/gif"
    if ext == ".webp":
        return "image/webp"
    if ext == ".avif":
        return "image/avif"
    if ext == ".svg":
        return "image/svg+xml"
    if ext in {".xhtml", ".html", ".htm"}:
        return "application/xhtml+xml"
    if ext == ".ncx":
        return "application/x-dtbncx+xml"
    if ext == ".css":
        return "text/css"
    if ext == ".otf":
        return "font/otf"
    if ext == ".ttf":
        return "font/ttf"
    if ext == ".woff":
        return "font/woff"
    if ext == ".woff2":
        return "font/woff2"
    if ext == ".js":
        return "text/javascript"
    return None


def _normalize_media_type(href: str, declared: str) -> str:
    """Normalize invalid/ambiguous media-type declarations by href extension."""
    inferred = _media_type_from_href(href)
    if inferred:
        return inferred
    media_type = (declared or "").strip()
    return media_type or "application/octet-stream"


def _sanitize_xhtml_blob(href: str, blob: bytes) -> bytes:
    """Repair legacy XHTML entries before writing them into the merged EPUB."""
    suffix = Path(href).suffix.lower()
    if suffix not in {".xhtml", ".html", ".htm"}:
        return blob
    if b"epub:" not in blob or b"xmlns:epub" in blob:
        return blob
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return blob
    repaired = re.sub(
        r"(<html\b[^>]*)(>)",
        rf'\1 xmlns:epub="{EPUB_NS}"\2',
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    return repaired.encode("utf-8") if repaired != text else blob


def _ensure_unique_id(base_id: str, used_ids: set[str]) -> str:
    """Make sure OPF manifest ids are unique."""
    candidate = base_id
    seq = 2
    while candidate in used_ids:
        candidate = f"{base_id}_{seq}"
        seq += 1
    used_ids.add(candidate)
    return candidate


def _utc_modified() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_text(root: Optional[ET.Element], xpath: str) -> Optional[str]:
    if root is None:
        return None
    node = root.find(xpath)
    if node is None or node.text is None:
        return None
    text = node.text.strip()
    return text or None


def _extract_layout_profile(metadata: Optional[ET.Element], spine: ET.Element) -> LayoutProfile:
    profile = LayoutProfile()
    if metadata is not None:
        for meta in metadata.findall(f"{{{OPF_NS}}}meta") + metadata.findall("meta"):
            name = (meta.attrib.get("name") or "").strip().lower()
            prop = (meta.attrib.get("property") or "").strip().lower()
            value = (meta.attrib.get("content") or meta.text or "").strip()
            if not value:
                continue
            if name == "fixed-layout":
                profile.fixed_layout = value
            elif name == "book-type":
                profile.book_type = value
            elif name == "primary-writing-mode":
                profile.primary_writing_mode = value
            elif prop == "rendition:layout":
                profile.rendition_layout = value
            elif prop == "rendition:spread":
                profile.rendition_spread = value

    page_direction = spine.attrib.get("page-progression-direction", "").strip()
    if page_direction:
        profile.page_progression_direction = page_direction

    if profile.rendition_layout.lower() != "pre-paginated":
        profile.rendition_layout = "pre-paginated"
    # The merged book is one XHTML per page, so a single-page spread hint is safer.
    profile.rendition_spread = "none"
    if profile.fixed_layout.lower() not in {"true", "false"}:
        profile.fixed_layout = "true"
    if not profile.book_type:
        profile.book_type = "comic"
    if not profile.primary_writing_mode:
        profile.primary_writing_mode = "horizontal-lr"
    if profile.page_progression_direction not in {"ltr", "rtl"}:
        profile.page_progression_direction = "ltr"
    return profile


def _first_existing_href(old_to_new_href: Dict[str, str], keys: List[str]) -> Optional[str]:
    """Return the first mapped href from candidate keys."""
    for key in keys:
        if key in old_to_new_href:
            return old_to_new_href[key]
    return None


def _load_plan(path: str) -> MergePlan:
    # Plan json is produced by the PowerShell pipeline and defines
    # both ordering and metadata for the merged anthology.
    with open(path, "r", encoding="utf-8-sig") as fp:
        raw = json.load(fp)

    required = ["output_epub_path", "title", "author", "language", "description", "chapters"]
    for key in required:
        if key not in raw:
            raise MergeError(f"plan json missing field: {key}")

    chapters = []
    for idx, item in enumerate(raw["chapters"]):
        for key in ["chapter_name", "epub_path"]:
            if key not in item:
                raise MergeError(f"plan chapter[{idx}] missing field: {key}")
        order = item.get("order")
        order_value = float(order) if order is not None else None
        chapters.append(
            ChapterPlan(
                chapter_name=str(item["chapter_name"]),
                order=order_value,
                epub_path=str(item["epub_path"]),
            )
        )

    if not chapters:
        raise MergeError("no chapters provided")

    return MergePlan(
        output_epub_path=str(raw["output_epub_path"]),
        title=str(raw["title"]),
        author=str(raw["author"]),
        language=str(raw["language"]),
        description=str(raw["description"]),
        contributor=str(raw.get("contributor", "mjnai-merge")),
        chapters=chapters,
    )


def _write_container_xml(out: zipfile.ZipFile) -> None:
    """Write EPUB META-INF/container.xml that points to merged content.opf."""
    container = ET.Element("container", attrib={"version": "1.0", "xmlns": CONT_NS})
    rootfiles = ET.SubElement(container, "rootfiles")
    ET.SubElement(
        rootfiles,
        "rootfile",
        attrib={
            "full-path": "content.opf",
            "media-type": "application/oebps-package+xml",
        },
    )
    xml = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(container, encoding="utf-8")
    out.writestr("META-INF/container.xml", xml, compress_type=zipfile.ZIP_DEFLATED)


def _write_toc_ncx(
    out: zipfile.ZipFile,
    uid: str,
    title: str,
    navpoints: List[Tuple[str, str]],
) -> None:
    """Create a flat NCX table of contents from chapter navpoints."""
    ncx = ET.Element("ncx", attrib={"version": "2005-1", "xmlns": NCX_NS})
    head = ET.SubElement(ncx, "head")
    ET.SubElement(head, "meta", attrib={"name": "dtb:uid", "content": uid})
    ET.SubElement(head, "meta", attrib={"name": "dtb:depth", "content": "1"})
    ET.SubElement(head, "meta", attrib={"name": "dtb:totalPageCount", "content": "0"})
    ET.SubElement(head, "meta", attrib={"name": "dtb:maxPageNumber", "content": "0"})

    doc_title = ET.SubElement(ncx, "docTitle")
    ET.SubElement(doc_title, "text").text = title

    nav_map = ET.SubElement(ncx, "navMap")
    for idx, (name, href) in enumerate(navpoints, start=1):
        nav = ET.SubElement(nav_map, "navPoint", attrib={"id": f"book{idx:03d}", "playOrder": str(idx)})
        nav_label = ET.SubElement(nav, "navLabel")
        ET.SubElement(nav_label, "text").text = name
        ET.SubElement(nav, "content", attrib={"src": href})

    xml = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(ncx, encoding="utf-8")
    out.writestr("toc.ncx", xml, compress_type=zipfile.ZIP_DEFLATED)


def _write_nav_xhtml(
    out: zipfile.ZipFile,
    *,
    title: str,
    navpoints: List[Tuple[str, str]],
    page_list_hrefs: List[str],
    first_body_href: Optional[str],
) -> None:
    title_xml = escape(title)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<!DOCTYPE html>',
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">',
        "<head>",
        f"<title>{title_xml}</title>",
        '<meta charset="utf-8"/>',
        "</head>",
        "<body>",
        '<nav epub:type="toc" id="toc">',
        "<ol>",
    ]
    for label, href in navpoints:
        lines.append(f'<li><a href="{escape(href)}">{escape(label)}</a></li>')
    lines.extend(["</ol>", "</nav>", '<nav epub:type="page-list" hidden="hidden">', "<ol>"])
    for index, href in enumerate(page_list_hrefs, start=1):
        lines.append(f'<li><a href="{escape(href)}">{index}</a></li>')
    lines.extend(["</ol>", "</nav>"])
    if first_body_href:
        lines.extend(
            [
                '<nav epub:type="landmarks" hidden="hidden">',
                "<ol>",
                f'<li><a epub:type="bodymatter" href="{escape(first_body_href)}">开始阅读</a></li>',
                "</ol>",
                "</nav>",
            ]
        )
    lines.extend(["</body>", "</html>", ""])
    out.writestr("nav.xhtml", "\n".join(lines).encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)


def _write_content_opf(
    out: zipfile.ZipFile,
    uid: str,
    plan: MergePlan,
    manifest_items: List[ManifestItemRecord],
    spine_items: List[SpineItemRecord],
    cover_image_href: Optional[str],
    layout_profile: LayoutProfile,
) -> None:
    """Write merged OPF metadata, manifest, spine, and optional cover guide."""
    package = ET.Element(
        "package",
        attrib={
            "version": "3.0",
            "xmlns": OPF_NS,
            "unique-identifier": "mjnai-merge-id",
            "prefix": "rendition: http://www.idpf.org/vocab/rendition/#",
        },
    )

    metadata = ET.SubElement(
        package,
        "metadata",
        attrib={
            "xmlns:dc": DC_NS,
            "xmlns:opf": OPF_NS,
        },
    )
    ET.SubElement(metadata, "dc:identifier", attrib={"id": "mjnai-merge-id"}).text = uid
    ET.SubElement(metadata, "dc:title").text = plan.title
    ET.SubElement(
        metadata,
        "dc:creator",
        attrib={"opf:role": "aut", "opf:file-as": plan.author},
    ).text = plan.author
    ET.SubElement(metadata, "dc:language").text = plan.language
    ET.SubElement(metadata, "dc:description").text = plan.description
    ET.SubElement(metadata, "dc:contributor").text = plan.contributor
    ET.SubElement(metadata, "dc:publisher").text = "Manga Loader Skill"
    ET.SubElement(metadata, "meta", attrib={"property": "dcterms:modified"}).text = _utc_modified()
    ET.SubElement(metadata, "meta", attrib={"name": "fixed-layout", "content": layout_profile.fixed_layout})
    ET.SubElement(metadata, "meta", attrib={"name": "book-type", "content": layout_profile.book_type})
    ET.SubElement(
        metadata,
        "meta",
        attrib={"name": "primary-writing-mode", "content": layout_profile.primary_writing_mode},
    )
    ET.SubElement(metadata, "meta", attrib={"property": "rendition:layout"}).text = layout_profile.rendition_layout
    ET.SubElement(metadata, "meta", attrib={"property": "rendition:spread"}).text = layout_profile.rendition_spread

    if cover_image_href:
        ET.SubElement(metadata, "meta", attrib={"name": "cover", "content": "coverimageid"})

    manifest = ET.SubElement(package, "manifest")
    if cover_image_href:
        media = _media_type_from_href(cover_image_href) or "image/jpeg"
        ET.SubElement(
            manifest,
            "item",
            attrib={"id": "coverimageid", "href": cover_image_href, "media-type": media, "properties": "cover-image"},
        )
        ET.SubElement(manifest, "item", attrib={"id": "cover", "href": "cover.xhtml", "media-type": "application/xhtml+xml"})
    ET.SubElement(manifest, "item", attrib={"id": "ncx", "href": "toc.ncx", "media-type": "application/x-dtbncx+xml"})
    ET.SubElement(
        manifest,
        "item",
        attrib={"id": "nav", "href": "nav.xhtml", "media-type": "application/xhtml+xml", "properties": "nav"},
    )

    for item in manifest_items:
        attrib = {"id": item.item_id, "href": item.href, "media-type": item.media_type}
        if item.properties:
            attrib["properties"] = item.properties
        ET.SubElement(manifest, "item", attrib=attrib)

    spine = ET.SubElement(
        package,
        "spine",
        attrib={"toc": "ncx", "page-progression-direction": layout_profile.page_progression_direction},
    )
    for item in spine_items:
        attrib = {"idref": item.idref, "linear": "yes"}
        if item.properties:
            attrib["properties"] = item.properties
        ET.SubElement(spine, "itemref", attrib=attrib)

    if cover_image_href:
        guide = ET.SubElement(package, "guide")
        ET.SubElement(guide, "reference", attrib={"type": "cover", "title": "Cover", "href": "cover.xhtml"})

    xml = b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(package, encoding="utf-8")
    out.writestr("content.opf", xml, compress_type=zipfile.ZIP_DEFLATED)


def _write_cover_xhtml(out: zipfile.ZipFile, cover_href: str) -> None:
    """Write a simple XHTML cover page referencing the selected cover image."""
    html = f"""<?xml version=\"1.0\" encoding=\"utf-8\"?>
<html xmlns=\"http://www.w3.org/1999/xhtml\">
  <head><title>Cover</title></head>
  <body>
    <div style=\"text-align:center;\"><img alt=\"cover\" src=\"{cover_href}\" /></div>
  </body>
</html>
"""
    out.writestr("cover.xhtml", html.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)


def merge(plan: MergePlan) -> None:
    """Merge chapter EPUBs into one fixed-layout EPUB archive based on plan order."""
    out_path = Path(plan.output_epub_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_file = NamedTemporaryFile(prefix="mjnai_merge_", suffix=".epub", delete=False, dir=str(out_path.parent))
    tmp_path = Path(tmp_file.name)
    tmp_file.close()

    manifest_items: List[ManifestItemRecord] = []
    spine_items: List[SpineItemRecord] = []
    navpoints: List[Tuple[str, str]] = []
    page_list_hrefs: List[str] = []
    seen_hrefs = set()
    seen_manifest_hrefs: Dict[str, str] = {}
    used_manifest_ids: set[str] = {"ncx", "nav", "cover", "coverimageid"}

    cover_href: Optional[str] = None
    layout_profile: Optional[LayoutProfile] = None
    uid = f"urn:uuid:{uuid.uuid4()}"

    try:
        with zipfile.ZipFile(tmp_path, "w", allowZip64=True) as out:
            # EPUB requirement: mimetype must be first and uncompressed.
            mime_info = zipfile.ZipInfo("mimetype")
            mime_info.compress_type = zipfile.ZIP_STORED
            out.writestr(mime_info, b"application/epub+zip")
            _write_container_xml(out)

            for chapter_index, chapter in enumerate(plan.chapters, start=1):
                epub_path = Path(chapter.epub_path)
                if not epub_path.is_file():
                    raise MergeError(f"chapter epub not found: {epub_path}")

                with zipfile.ZipFile(epub_path, "r") as src:
                    container_xml = _read_text(src, "META-INF/container.xml")
                    rootfile = _find_rootfile_path(container_xml)
                    opf_xml = _read_text(src, rootfile)

                    opf_root = ET.fromstring(opf_xml)
                    root_dir = posixpath.dirname(rootfile)

                    manifest = opf_root.find(f"{{{OPF_NS}}}manifest")
                    if manifest is None:
                        manifest = opf_root.find("manifest")
                    spine = opf_root.find(f"{{{OPF_NS}}}spine")
                    if spine is None:
                        spine = opf_root.find("spine")
                    metadata = opf_root.find(f"{{{OPF_NS}}}metadata")
                    if metadata is None:
                        metadata = opf_root.find("metadata")

                    if manifest is None or spine is None:
                        raise MergeError(f"invalid opf in {epub_path}: missing manifest/spine")
                    if layout_profile is None:
                        layout_profile = _extract_layout_profile(metadata, spine)

                    # Namespace each source book under "<index>/" to avoid
                    # href/id collisions between different chapter EPUBs.
                    chapter_prefix = f"{chapter_index}/"
                    old_to_new_id: Dict[str, str] = {}
                    old_to_new_href: Dict[str, str] = {}

                    source_cover_id = None
                    if metadata is not None:
                        for meta in metadata.findall(f"{{{OPF_NS}}}meta") + metadata.findall("meta"):
                            if meta.attrib.get("name") == "cover":
                                source_cover_id = meta.attrib.get("content")
                                break

                    for item in manifest:
                        if _local(item.tag) != "item":
                            continue
                        old_id = item.attrib.get("id", "")
                        href = item.attrib.get("href", "")
                        media_type = item.attrib.get("media-type", "application/octet-stream")
                        properties = item.attrib.get("properties", "").split()
                        if not href:
                            continue
                        if "nav" in properties or media_type == "application/x-dtbncx+xml":
                            continue

                        src_name = _norm(posixpath.join(root_dir, href))
                        dst_name = _norm(chapter_prefix + src_name)
                        normalized_media_type = _normalize_media_type(dst_name, media_type)

                        try:
                            blob = src.read(src_name)
                        except KeyError:
                            # Keep merge resilient to occasional bad item refs.
                            continue
                        blob = _sanitize_xhtml_blob(src_name, blob)

                        if dst_name not in seen_hrefs:
                            out.writestr(dst_name, blob, compress_type=zipfile.ZIP_DEFLATED)
                            seen_hrefs.add(dst_name)

                        is_source_cover = bool(source_cover_id) and old_id == source_cover_id
                        if is_source_cover and cover_href is None:
                            # Canonicalize source cover to top-level coverimageid item.
                            cover_href = dst_name
                            seen_manifest_hrefs[dst_name] = "coverimageid"
                            if old_id:
                                old_to_new_id[old_id] = "coverimageid"
                                old_to_new_href[old_id] = dst_name
                            continue

                        if dst_name in seen_manifest_hrefs:
                            new_id = seen_manifest_hrefs[dst_name]
                        else:
                            base_id = f"c{chapter_index}_{_safe_id(old_id or Path(href).stem)}"
                            new_id = _ensure_unique_id(base_id, used_manifest_ids)
                            seen_manifest_hrefs[dst_name] = new_id
                            manifest_items.append(
                                ManifestItemRecord(
                                    item_id=new_id,
                                    href=dst_name,
                                    media_type=normalized_media_type,
                                    properties=" ".join(properties) if properties else None,
                                )
                            )

                        if old_id:
                            old_to_new_id[old_id] = new_id
                            old_to_new_href[old_id] = dst_name

                    first_spine_href: Optional[str] = None
                    for itemref in spine:
                        if _local(itemref.tag) != "itemref":
                            continue
                        old_idref = itemref.attrib.get("idref", "")
                        new_idref = old_to_new_id.get(old_idref)
                        if not new_idref:
                            continue
                        spine_items.append(
                            SpineItemRecord(
                                idref=new_idref,
                                properties=itemref.attrib.get("properties", "").strip() or None,
                            )
                        )
                        page_href = old_to_new_href.get(old_idref)
                        if page_href is not None:
                            page_list_hrefs.append(page_href)
                        if first_spine_href is None:
                            first_spine_href = page_href

                    if first_spine_href is None:
                        raise MergeError(f"cannot resolve first spine item for {epub_path}")

                    # Each chapter contributes one top-level TOC entry.
                    navpoints.append((chapter.chapter_name, first_spine_href))

                    if cover_href is None and source_cover_id:
                        cover_href = old_to_new_href.get(source_cover_id)

            if cover_href:
                _write_cover_xhtml(out, cover_href)

            _write_toc_ncx(out, uid=uid, title=plan.title, navpoints=navpoints)
            _write_nav_xhtml(
                out,
                title=plan.title,
                navpoints=navpoints,
                page_list_hrefs=page_list_hrefs,
                first_body_href=navpoints[0][1] if navpoints else None,
            )
            _write_content_opf(
                out,
                uid=uid,
                plan=plan,
                manifest_items=manifest_items,
                spine_items=spine_items,
                cover_image_href=cover_href,
                layout_profile=layout_profile or LayoutProfile(),
            )
            # Match epubmerge behavior: mark entries as Windows-created to
            # avoid platform-specific permission quirks when extracted.
            for zinfo in out.filelist:
                zinfo.create_system = 0

        # Atomic replace prevents leaving a partial EPUB on failure.
        os.replace(tmp_path, out_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def build_arg_parser() -> argparse.ArgumentParser:
    """Define CLI interface for the merge helper."""
    p = argparse.ArgumentParser(description="Merge ordered chapter EPUBs into one EPUB2 file")
    p.add_argument("--plan", required=True, help="Path to merge plan JSON")
    return p


def main(argv: List[str]) -> int:
    """CLI entrypoint with stable exit codes for pipeline integration."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    def _safe_text(value: object) -> str:
        text = str(value)
        enc = sys.stdout.encoding or "utf-8"
        return text.encode(enc, errors="backslashreplace").decode(enc, errors="replace")

    try:
        plan = _load_plan(args.plan)
        merge(plan)
        print(f"MERGE_OK: {_safe_text(plan.output_epub_path)}")
        return 0
    except MergeError as exc:
        print(f"MERGE_ERROR: {_safe_text(exc)}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"MERGE_ERROR_UNEXPECTED: {_safe_text(exc)}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
