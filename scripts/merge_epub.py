#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import re
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageColor, ImageOps

IMAGE_EXTENSIONS = (".webp", ".jpg", ".jpeg", ".png", ".avif")


def natural_key(text: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def chapter_dirs(input_root: Path) -> list[Path]:
    return sorted([path for path in input_root.iterdir() if path.is_dir()], key=lambda path: natural_key(path.name))


def chapter_images(chapter_dir: Path) -> list[Path]:
    return sorted(
        [path for path in chapter_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS],
        key=lambda path: natural_key(path.name),
    )


def modified_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def page_dimensions(images: list[Path]) -> tuple[int, int]:
    width = 0
    height = 0
    for image_path in images:
        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image)
            width = max(width, image.width)
            height = max(height, image.height)
    if width <= 0 or height <= 0:
        raise ValueError("unable to determine merged page dimensions")
    return width, height


def rendered_image_bytes(image_path: Path, canvas_size: tuple[int, int], background: str, jpeg_quality: int) -> bytes:
    background_rgb = ImageColor.getrgb(background)
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")
        canvas = Image.new("RGB", canvas_size, background_rgb)
        offset_x = (canvas_size[0] - image.width) // 2
        offset_y = (canvas_size[1] - image.height) // 2
        canvas.paste(image, (offset_x, offset_y))
        buffer = io.BytesIO()
        canvas.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
        return buffer.getvalue()


def nav_document(title: str, chapter_info: list[dict[str, object]], page_count: int, language: str) -> str:
    safe_title = escape(title)
    safe_language = escape(language)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE html>",
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{safe_language}" lang="{safe_language}">',
        "<head>",
        f"  <title>{safe_title}</title>",
        "</head>",
        "<body>",
        '  <nav epub:type="toc">',
        "    <ol>",
    ]
    for chapter in chapter_info:
        lines.append(
            f'      <li><a href="page{int(chapter["start_page"]):04d}.xhtml">{escape(str(chapter["name"]))}</a></li>'
        )
    lines.extend([
        "    </ol>",
        "  </nav>",
        '  <nav epub:type="page-list" hidden="hidden">',
        "    <ol>",
    ])
    for index in range(page_count):
        lines.append(f'      <li><a href="page{index:04d}.xhtml">{index + 1}</a></li>')
    lines.extend(["    </ol>", "  </nav>", "</body>", "</html>"])
    return "\n".join(lines)


def page_document(title: str, index: int, width: int, height: int, language: str) -> str:
    safe_title = escape(title)
    safe_language = escape(language)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{safe_language}" lang="{safe_language}">
<head>
  <title>{safe_title} - 第{index + 1}页</title>
  <meta name="viewport" content="width={width}, height={height}"/>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      width: {width}px;
      height: {height}px;
      overflow: hidden;
      background: #000;
    }}
    body {{
      position: relative;
    }}
    img {{
      display: block;
      width: {width}px;
      height: {height}px;
      object-fit: contain;
      object-position: center center;
    }}
  </style>
</head>
<body>
  <img src="images/{index:04d}.jpg" alt="第{index + 1}页"/>
</body>
</html>"""


def create_merged_epub(
    input_dir: Path,
    output_path: Path,
    title: str,
    *,
    author: str,
    language: str,
    background: str,
    jpeg_quality: int,
) -> bool:
    input_dir = Path(input_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_images: list[Path] = []
    chapter_info: list[dict[str, object]] = []
    current_page = 0
    for chapter_dir in chapter_dirs(input_dir):
        images = chapter_images(chapter_dir)
        if not images:
            continue
        chapter_info.append({"name": chapter_dir.name, "start_page": current_page, "page_count": len(images)})
        all_images.extend(images)
        current_page += len(images)

    if not all_images:
        print(f"no chapter images found under {input_dir}", file=sys.stderr)
        return False

    page_width, page_height = page_dimensions(all_images)
    safe_title = escape(title)
    safe_author = escape(author or "Unknown")
    safe_language = escape(language or "zh-Hans")
    book_id = f"urn:uuid:{uuid.uuid4()}"

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as epub:
        epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""",
        )

        opf_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<package version="3.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" '
            'prefix="rendition: http://www.idpf.org/vocab/rendition/#">',
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
            f'    <dc:identifier id="bookid">{book_id}</dc:identifier>',
            f"    <dc:title>{safe_title}</dc:title>",
            f'    <dc:creator id="creator">{safe_author}</dc:creator>',
            f'    <meta refines="#creator" property="file-as">{safe_author}</meta>',
            '    <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>',
            f"    <dc:language>{safe_language}</dc:language>",
            f'    <meta property="dcterms:modified">{modified_timestamp()}</meta>',
            '    <meta property="rendition:layout">pre-paginated</meta>',
            '    <meta property="rendition:spread">none</meta>',
            "  </metadata>",
            "  <manifest>",
            '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        ]
        for index, _ in enumerate(all_images):
            image_properties = ' properties="cover-image"' if index == 0 else ""
            opf_lines.append(
                f'    <item id="img{index}" href="images/{index:04d}.jpg" media-type="image/jpeg"{image_properties}/>'
            )
            opf_lines.append(
                f'    <item id="page{index:04d}" href="page{index:04d}.xhtml" media-type="application/xhtml+xml"/>'
            )
        opf_lines.extend(["  </manifest>", '  <spine page-progression-direction="rtl">'])
        for index, _ in enumerate(all_images):
            opf_lines.append(f'    <itemref idref="page{index:04d}"/>')
        opf_lines.extend(["  </spine>", "</package>"])
        epub.writestr("OEBPS/content.opf", "\n".join(opf_lines))

        epub.writestr("OEBPS/nav.xhtml", nav_document(title, chapter_info, len(all_images), language))

        for index, image_path in enumerate(all_images):
            epub.writestr(
                f"OEBPS/images/{index:04d}.jpg",
                rendered_image_bytes(image_path, (page_width, page_height), background, jpeg_quality),
            )
            epub.writestr(f"OEBPS/page{index:04d}.xhtml", page_document(title, index, page_width, page_height, language))
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a fixed-layout merged EPUB from chapter image folders")
    parser.add_argument("chapter_root")
    parser.add_argument("output_file")
    parser.add_argument("title")
    parser.add_argument("--author", default="Unknown")
    parser.add_argument("--language", default="zh-Hans")
    parser.add_argument("--page-background", default="#000000")
    parser.add_argument("--jpeg-quality", type=int, default=90)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    return 0 if create_merged_epub(
        Path(args.chapter_root).resolve(),
        Path(args.output_file).resolve(),
        args.title,
        author=args.author,
        language=args.language,
        background=args.page_background,
        jpeg_quality=args.jpeg_quality,
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
