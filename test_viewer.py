"""
viewer.py のユニットテスト

標準ライブラリの unittest だけを使います。
実行方法:
    python test_viewer.py
    python -m unittest test_viewer          # 同じ
    python -m unittest test_viewer -v       # 詳細表示
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

# viewer.py はトップレベルで config.toml を読み込む。
# config.toml がプロジェクトルートにあれば問題なく import できる。
import viewer


class TestTagPattern(unittest.TestCase):
    """TAG_PATTERN の正規表現テスト"""

    def test_single_tag(self):
        tags = viewer.TAG_PATTERN.findall("メモです #idea")
        self.assertEqual(tags, ["idea"])

    def test_multiple_tags(self):
        tags = viewer.TAG_PATTERN.findall("調査中 #todo #ref")
        self.assertEqual(tags, ["todo", "ref"])

    def test_no_tags(self):
        tags = viewer.TAG_PATTERN.findall("タグなしのテキスト")
        self.assertEqual(tags, [])

    def test_favorite_tag(self):
        tags = viewer.TAG_PATTERN.findall("重要メモ #favorite")
        self.assertIn("favorite", tags)

    def test_japanese_tag(self):
        tags = viewer.TAG_PATTERN.findall("メモ #日本語 #アイデア")
        self.assertEqual(tags, ["日本語", "アイデア"])


class TestImagePattern(unittest.TestCase):
    """IMAGE_PATTERN の正規表現テスト"""

    def test_matches_assets_image(self):
        content = "スクリーンショット  \n![](../assets/20240101_120000_abc.webp)"
        filenames = viewer.IMAGE_PATTERN.findall(content)
        self.assertEqual(filenames, ["20240101_120000_abc.webp"])

    def test_no_match_for_external_url(self):
        content = "![alt](https://example.com/image.png)"
        filenames = viewer.IMAGE_PATTERN.findall(content)
        self.assertEqual(filenames, [])

    def test_multiple_images(self):
        content = (
            "![](../assets/img1.webp)\n"
            "テキスト\n"
            "![](../assets/img2.webp)"
        )
        filenames = viewer.IMAGE_PATTERN.findall(content)
        self.assertEqual(filenames, ["img1.webp", "img2.webp"])


class TestParseFragment(unittest.TestCase):
    """parse_fragment のテスト。tempfile で一時ファイルを作る"""

    def _write_temp_md(self, content: str, stem: str = "20240315_093000") -> Path:
        """テスト用の一時 .md ファイルを作る"""
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / f"{stem}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def test_id_is_stem(self):
        path = self._write_temp_md("テスト", stem="20240315_093000")
        frag = viewer.parse_fragment(path)
        self.assertEqual(frag.id, "20240315_093000")

    def test_created_at_parsed_from_filename(self):
        path = self._write_temp_md("テスト", stem="20240315_093000")
        frag = viewer.parse_fragment(path)
        self.assertEqual(frag.created_at, datetime(2024, 3, 15, 9, 30, 0))

    def test_content_stripped(self):
        path = self._write_temp_md("  前後に空白  \n\n", stem="20240315_093000")
        frag = viewer.parse_fragment(path)
        self.assertEqual(frag.content, "前後に空白")

    def test_tags_extracted(self):
        path = self._write_temp_md("アイデアメモ #idea #todo", stem="20240315_093000")
        frag = viewer.parse_fragment(path)
        self.assertIn("idea", frag.tags)
        self.assertIn("todo", frag.tags)

    def test_invalid_stem_falls_back_to_mtime(self):
        """ファイル名が日時形式でない場合は mtime を使う"""
        path = self._write_temp_md("内容", stem="random_name")
        frag = viewer.parse_fragment(path)
        # mtime ベースなので現在日時に近い（型が datetime であることだけ確認）
        self.assertIsInstance(frag.created_at, datetime)


class TestUpdateFragment(unittest.TestCase):
    """update_fragment のテスト。_source_dir をモックして一時ディレクトリを使う"""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def _make_file(self, stem: str, content: str) -> Path:
        path = self.tmp_dir / f"{stem}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def test_content_overwritten(self):
        self._make_file("20240315_093000", "元の内容")
        with patch.object(viewer, "_source_dir", return_value=self.tmp_dir):
            body = viewer.FragmentUpdate(content="更新後の内容")
            frag = viewer.update_fragment("20240315_093000", body)
        self.assertEqual(frag.content, "更新後の内容")

    def test_tags_refreshed_after_update(self):
        self._make_file("20240315_093000", "元の内容")
        with patch.object(viewer, "_source_dir", return_value=self.tmp_dir):
            body = viewer.FragmentUpdate(content="更新後 #newtag")
            frag = viewer.update_fragment("20240315_093000", body)
        self.assertIn("newtag", frag.tags)

    def test_not_found_raises_404(self):
        with patch.object(viewer, "_source_dir", return_value=self.tmp_dir):
            body = viewer.FragmentUpdate(content="内容")
            with self.assertRaises(HTTPException) as ctx:
                viewer.update_fragment("nonexistent", body)
        self.assertEqual(ctx.exception.status_code, 404)


class TestSourceDir(unittest.TestCase):
    """_source_dir のルーティングテスト"""

    def test_inbox(self):
        self.assertEqual(viewer._source_dir("inbox"), viewer.INBOX_DIR)

    def test_archive(self):
        self.assertEqual(viewer._source_dir("archive"), viewer.ARCHIVE_DIR)


if __name__ == "__main__":
    unittest.main()
