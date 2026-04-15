#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))

from manga_common import plan_split_volumes, render_name_template  # noqa: E402


def _make_epubs(root: Path, count: int, *, size_step: int = 128) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for index in range(1, count + 1):
        path = root / f"Series 第{index:02d}话.epub"
        path.write_bytes(b"x" * (size_step * index))
        created.append(path)
    return created


class SplitFeatureTest(unittest.TestCase):
    def test_render_name_template_keeps_numeric_formatting(self) -> None:
        rendered = render_name_template("{title} 第{volume_index:02d}册.epub", title="葬送的芙莉蓮", volume_index=3)
        self.assertEqual(rendered, "葬送的芙莉蓮 第03册.epub")

    def test_plan_split_volumes_by_chapter_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            chapter_epubs = _make_epubs(Path(temp_dir), 5)
            plan = plan_split_volumes(
                chapter_epubs,
                title="葬送的芙莉蓮",
                chapters_per_volume=2,
                volume_name_template="{title} 第{volume_index:02d}册.epub",
            )
            self.assertEqual(plan["volume_count"], 3)
            self.assertEqual(plan["volumes"][0]["chapter_count"], 2)
            self.assertEqual(plan["volumes"][1]["chapter_count"], 2)
            self.assertEqual(plan["volumes"][2]["chapter_count"], 1)
            self.assertEqual(plan["volumes"][0]["output_name"], "葬送的芙莉蓮 第01册.epub")

    def test_plan_split_volumes_respects_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            chapter_epubs = _make_epubs(Path(temp_dir), 4, size_step=1024 * 1024)
            plan = plan_split_volumes(
                chapter_epubs,
                title="葬送的芙莉蓮",
                chapters_per_volume=10,
                max_volume_size_mb=2.5,
                volume_name_template="{title} 第{volume_index:02d}册.epub",
            )
            chapter_counts = [item["chapter_count"] for item in plan["volumes"]]
            self.assertEqual(chapter_counts, [1, 1, 1, 1])


if __name__ == "__main__":
    unittest.main()
