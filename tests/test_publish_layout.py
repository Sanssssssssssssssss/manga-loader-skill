#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from manga_common import publish_outputs_to_mangabooks  # noqa: E402


def _make_epubs(root: Path, names: list[str]) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for name in names:
        path = root / name
        path.write_bytes(name.encode("utf-8"))
        created.append(path)
    return created


class PublishLayoutTest(unittest.TestCase):
    def test_publish_outputs_to_mangabooks_copies_expected_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            chapter_epubs = _make_epubs(
                temp_root / "chapters",
                ["彼方的阿斯特拉 第01话.epub", "彼方的阿斯特拉 第02话.epub"],
            )
            merged_epub = _make_epubs(temp_root / "merged", ["彼方的阿斯特拉 合订版.epub"])[0]

            report = publish_outputs_to_mangabooks(
                "彼方的阿斯特拉",
                chapter_epubs,
                merged_epub,
                settings={"publish": {"mangabooks_root": str(temp_root / "lib")}},
            )

            self.assertIsNotNone(report)
            self.assertTrue((temp_root / "lib" / "彼方的阿斯特拉" / "分章" / "0001 第01话.epub").exists())
            self.assertTrue((temp_root / "lib" / "彼方的阿斯特拉" / "分章" / "0002 第02话.epub").exists())
            self.assertTrue((temp_root / "lib" / "彼方的阿斯特拉" / "合订本" / "完整版.epub").exists())
            self.assertIsNone(report["archive_dir"])

    def test_publish_outputs_to_mangabooks_archives_previous_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            settings = {"publish": {"mangabooks_root": str(temp_root / "lib"), "archive_previous": True}}
            chapter_epubs = _make_epubs(temp_root / "chapters-a", ["神乐钵 第01话.epub"])
            merged_epub = _make_epubs(temp_root / "merged-a", ["神乐钵 合订版.epub"])[0]
            publish_outputs_to_mangabooks("神乐钵", chapter_epubs, merged_epub, settings=settings)

            replacement_chapters = _make_epubs(temp_root / "chapters-b", ["神乐钵 第02话.epub"])
            replacement_merged = _make_epubs(temp_root / "merged-b", ["神乐钵 合订版.epub"])[0]
            report = publish_outputs_to_mangabooks("神乐钵", replacement_chapters, replacement_merged, settings=settings)

            self.assertIsNotNone(report)
            history_root = temp_root / "lib" / "神乐钵" / "历史备份"
            history_dirs = list(history_root.glob("sync_before_update_*"))
            self.assertEqual(len(history_dirs), 1)
            self.assertTrue((history_dirs[0] / "分章" / "0001 第01话.epub").exists())
            self.assertTrue((history_dirs[0] / "合订本" / "完整版.epub").exists())
            self.assertTrue((temp_root / "lib" / "神乐钵" / "分章" / "0001 第02话.epub").exists())


if __name__ == "__main__":
    unittest.main()
