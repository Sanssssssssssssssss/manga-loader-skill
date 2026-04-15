#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from epub_checks import audit_epub  # noqa: E402


def _build_test_epub(
    path: Path,
    *,
    fixed_layout: bool,
    include_viewport: bool = True,
    include_images: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    opf_meta = [
        '<dc:identifier id="bookid">urn:uuid:test-book</dc:identifier>',
        "<dc:title>Test Book</dc:title>",
        "<dc:creator>Tester</dc:creator>",
        "<dc:language>zh-Hans</dc:language>",
        "<dc:publisher>Manga Loader Skill</dc:publisher>",
    ]
    if fixed_layout:
        opf_meta.extend(
            [
                '<meta property="dcterms:modified">2026-04-14T23:00:00Z</meta>',
                '<meta name="fixed-layout" content="true"/>',
                '<meta name="book-type" content="comic"/>',
                '<meta name="primary-writing-mode" content="horizontal-lr"/>',
                '<meta property="rendition:layout">pre-paginated</meta>',
                '<meta property="rendition:spread">none</meta>',
            ]
        )

    viewport = '<meta name="viewport" content="width=1200, height=1800"/>' if include_viewport else ""
    image_tag = '<img src="Images/page.webp" width="1200" height="1800"/>' if include_images else "<div>no image</div>"
    nav_item = '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'

    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    {' '.join(opf_meta)}
  </metadata>
  <manifest>
    {nav_item}
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover-image" href="Images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="page1" href="Text/page1.xhtml" media-type="application/xhtml+xml"/>
    <item id="img1" href="Images/page.webp" media-type="image/webp"/>
  </manifest>
  <spine page-progression-direction="ltr">
    <itemref idref="page1" properties="page-spread-left"/>
  </spine>
</package>
"""
    nav = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>Test Book</title><meta charset="utf-8"/></head>
  <body>
    <nav epub:type="toc"><ol><li><a href="Text/page1.xhtml">Start</a></li></ol></nav>
  </body>
</html>
"""
    page = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Page 1</title>{viewport}</head>
  <body>{image_tag}</body>
</html>
"""
    cover = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title></head><body><img src="Images/cover.jpg"/></body></html>
"""
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("content.opf", opf)
        zf.writestr("nav.xhtml", nav)
        zf.writestr("cover.xhtml", cover)
        zf.writestr("Text/page1.xhtml", page)
        zf.writestr("Images/page.webp", b"RIFFxxxxWEBPVP8 ")
        zf.writestr("Images/cover.jpg", b"\xff\xd8\xff\xd9")
    return path


class EpubRegressionTest(unittest.TestCase):
    def test_fixed_layout_book_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = _build_test_epub(Path(temp_dir) / "ok.epub", fixed_layout=True)
            report = audit_epub(epub_path, require_fixed_layout=True, require_page_images=True)
            self.assertTrue(report["reader_ready"], report)

    def test_missing_fixed_layout_fields_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = _build_test_epub(Path(temp_dir) / "bad-fixed.epub", fixed_layout=False)
            report = audit_epub(epub_path, require_fixed_layout=True, require_page_images=True)
            self.assertIn("rendition_layout_missing", report["errors"])
            self.assertFalse(report["reader_ready"])

    def test_missing_viewport_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = _build_test_epub(Path(temp_dir) / "bad-viewport.epub", fixed_layout=True, include_viewport=False)
            report = audit_epub(epub_path, require_fixed_layout=True, require_page_images=True)
            self.assertIn("viewport_missing", report["errors"])

    def test_missing_page_image_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = _build_test_epub(Path(temp_dir) / "bad-image.epub", fixed_layout=True, include_images=False)
            report = audit_epub(epub_path, require_fixed_layout=True, require_page_images=True)
            self.assertIn("page_image_missing", report["errors"])


if __name__ == "__main__":
    unittest.main()
