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



class TestFolders(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(viewer, "ACTIVE_DIR", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_create_and_persist_order(self):
        for name in ("音楽", "開発"):
            viewer.create_folder(viewer.FolderCreate(name=name))
            self.assertTrue((self.root / name).is_dir())
        viewer.reorder_folders(viewer.FolderOrder(names=["音楽", "開発"]))
        self.assertEqual([f.name for f in viewer.get_folders()], ["音楽", "開発"])
        (self.root / "追加").mkdir()
        self.assertEqual([f.name for f in viewer.get_folders()], ["音楽", "開発", "追加"])

    def test_invalid_names_and_duplicate(self):
        for name in ("", " ", "..", "../outside", "a/b", "a\\b", ".hidden"):
            with self.subTest(name=name), self.assertRaises(HTTPException):
                viewer.create_folder(viewer.FolderCreate(name=name))
        viewer.create_folder(viewer.FolderCreate(name="音楽"))
        with self.assertRaises(HTTPException) as ctx:
            viewer.create_folder(viewer.FolderCreate(name="音楽"))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_incomplete_order_rejected(self):
        (self.root / "音楽").mkdir()
        with self.assertRaises(HTTPException):
            viewer.reorder_folders(viewer.FolderOrder(names=[]))

    def test_folder_selection_and_update(self):
        for name in ("音楽", "開発"):
            (self.root / name).mkdir()
            (self.root / name / "same.md").write_text(name + " #test")
        self.assertEqual(viewer.get_fragments("notes", "音楽")[0].content, "音楽 #test")
        viewer.update_fragment("same", viewer.FragmentUpdate(content="変更"), "notes", "音楽")
        self.assertEqual((self.root / "開発/same.md").read_text(), "開発 #test")
        self.assertEqual(viewer.get_tags("notes", "開発"), ["test"])

    def test_symlinks_and_escape_rejected(self):
        (self.root / "link").symlink_to(self.root.parent, target_is_directory=True)
        self.assertEqual(viewer.get_folders(), [])
        for folder in ("link", "../outside"):
            with self.assertRaises(HTTPException):
                viewer.get_fragments("notes", folder)


    def test_deleted_folder_order_and_corrupt_order(self):
        for name in ("a", "b"):
            (self.root / name).mkdir()
        viewer.reorder_folders(viewer.FolderOrder(names=["b", "a"]))
        (self.root / "b").rmdir()
        self.assertEqual([f.name for f in viewer.get_folders()], ["a"])
        (self.root / ".folder-order.json").write_text("invalid")
        with self.assertRaises(HTTPException) as ctx:
            viewer.get_folders()
        self.assertEqual(ctx.exception.status_code, 500)

    def test_duplicate_order_does_not_replace_saved_order(self):
        for name in ("a", "b"):
            (self.root / name).mkdir()
        viewer.reorder_folders(viewer.FolderOrder(names=["b", "a"]))
        with self.assertRaises(HTTPException):
            viewer.reorder_folders(viewer.FolderOrder(names=["a", "a"]))
        self.assertEqual([f.name for f in viewer.get_folders()], ["b", "a"])

    def test_fragment_symlink_is_not_read_or_updated(self):
        (self.root / "folder").mkdir()
        (self.root / "outside.md").write_text("original")
        (self.root / "folder/link.md").symlink_to(self.root / "outside.md")
        self.assertEqual(viewer.get_fragments("notes", "folder"), [])
        with self.assertRaises(HTTPException):
            viewer.update_fragment("link", viewer.FragmentUpdate(content="changed"), "notes", "folder")
        self.assertEqual((self.root / "outside.md").read_text(), "original")

    def test_delete_targets_selected_folder_and_rejects_trash_collision(self):
        for name in ("a", "b"):
            (self.root / name).mkdir()
            (self.root / name / "same.md").write_text(name)
        trash = self.root / "trash"
        with patch.object(viewer, "TRASH_DIR", trash):
            viewer.delete_fragment("same", "notes", "a")
            self.assertEqual((trash / "same.md").read_text(), "a")
            with self.assertRaises(HTTPException) as ctx:
                viewer.delete_fragment("same", "notes", "b")
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertEqual((self.root / "b/same.md").read_text(), "b")



class TestPosting(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "音楽").mkdir()
        self.patcher = patch.object(viewer, "ACTIVE_DIR", self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_post_selected_folder_and_unique_names(self):
        body = viewer.FragmentCreate(content="メモ #音楽")
        first = viewer.create_fragment(body, "notes", "音楽")
        second = viewer.create_fragment(body, "notes", "音楽")
        self.assertNotEqual(first.fragment.id, second.fragment.id)
        self.assertEqual(len(list((self.root / "音楽").glob("*.md"))), 2)
        self.assertEqual(first.fragment.tags, ["音楽"])

    def test_reject_empty_missing_folder_and_archive(self):
        for content, source, folder in [(" ", "notes", "音楽"), ("text", "notes", ""),
                                        ("text", "notes", "missing"), ("text", "archive", "")]:
            with self.subTest(source=source, folder=folder), self.assertRaises(HTTPException):
                viewer.create_fragment(viewer.FragmentCreate(content=content), source, folder)

    def test_metadata_and_relative_images(self):
        meta = {"title": "タイトル", "sitename": "サイト", "description": "説明"}
        with patch.object(viewer.capture, "_fetch_metadata", return_value=meta) as fetch:
            result = viewer.create_fragment(viewer.FragmentCreate(content="https://example.com"), "notes", "音楽")
        self.assertIn("title: タイトル", result.fragment.content)
        raw = (self.root / "音楽" / (result.fragment.id + ".md")).read_text()
        self.assertIn("title: タイトル  \n", raw)
        fetch.assert_called_once()

    def test_metadata_failure_preserves_post_and_reports_warning(self):
        with patch.object(viewer.capture, "_fetch_metadata", side_effect=RuntimeError("unavailable")):
            result = viewer.create_fragment(viewer.FragmentCreate(content="https://example.com"), "notes", "音楽")
        self.assertIn("https://example.com", result.fragment.content)
        self.assertTrue(result.warnings)

    def test_existing_metadata_not_refetched(self):
        with patch.object(viewer.capture, "_fetch_metadata") as fetch:
            viewer.create_fragment(viewer.FragmentCreate(content="https://example.com\ntitle: existing"), "notes", "音楽")
        fetch.assert_not_called()


    def test_image_path_is_relative_to_selected_folder(self):
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "image.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
        with patch.object(viewer, "ASSETS_DIR", assets):
            result = viewer.create_fragment(viewer.FragmentCreate(content="![](/assets/image.svg)  \n"), "notes", "音楽")
        raw = (self.root / "音楽" / (result.fragment.id + ".md")).read_text()
        self.assertEqual(raw, "![](../assets/image.svg)  \n")

    def test_upload_svg_and_reject_unsupported_or_oversize(self):
        import asyncio
        from starlette.requests import Request
        def request(data):
            async def receive():
                return {"type": "http.request", "body": data, "more_body": False}
            return Request({"type": "http", "method": "POST", "path": "/api/images", "headers": []}, receive)
        assets = self.root / "assets"
        with patch.object(viewer, "ASSETS_DIR", assets):
            response = asyncio.run(viewer.upload_image(request(b'<svg xmlns="http://www.w3.org/2000/svg"/>'), "test.svg"))
            self.assertIn("/assets/", response.markdown)
            self.assertEqual(len(list(assets.glob("*.svg"))), 1)
            for filename, data in [("text.txt", b"hello"), ("empty.png", b"")]:
                with self.assertRaises(HTTPException):
                    asyncio.run(viewer.upload_image(request(data), filename))
            with patch.object(viewer, "_IMAGE_MAX_BYTES", 2), self.assertRaises(HTTPException) as ctx:
                asyncio.run(viewer.upload_image(request(b"123"), "test.png"))
            self.assertEqual(ctx.exception.status_code, 413)

    def test_upload_raster_converts_to_webp(self):
        import asyncio
        import base64
        from starlette.requests import Request
        data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aOuoAAAAASUVORK5CYII=")
        async def receive():
            return {"type": "http.request", "body": data, "more_body": False}
        request = Request({"type": "http", "method": "POST", "path": "/api/images", "headers": []}, receive)
        assets = self.root / "assets"
        with patch.object(viewer, "ASSETS_DIR", assets):
            response = asyncio.run(viewer.upload_image(request, "image.png"))
        self.assertIn(".webp)", response.markdown)
        self.assertEqual(len(list(assets.glob("*.webp"))), 1)



class TestNavigation(unittest.TestCase):
    def test_inbox_is_orderable_alongside_normal_folders(self):
        with tempfile.TemporaryDirectory() as root, patch.object(viewer, "ACTIVE_DIR", Path(root)):
            (Path(root) / "音楽").mkdir()
            entries = viewer.get_navigation()
            self.assertEqual([(e.source, e.folder) for e in entries], [("inbox", ""), ("notes", "音楽")])
            ids = [e.id for e in reversed(entries)]
            viewer.reorder_navigation(viewer.FolderOrder(names=ids))
            self.assertEqual([e.id for e in viewer.get_navigation()], ids)
            self.assertNotIn("archive", [e.source for e in viewer.get_navigation()])
            with self.assertRaises(HTTPException):
                viewer.reorder_navigation(viewer.FolderOrder(names=ids[:-1]))


    def test_root_excludes_system_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.multiple(viewer, ACTIVE_DIR=root, ROOT_DIR=root, INBOX_DIR=root/"inbox", ARCHIVE_DIR=root/"archive",
                                ASSETS_DIR=root/"assets", TRASH_DIR=root/"Trash"):
                for name in ("inbox", "archive", "assets", "Trash", "notes", "Music"):
                    (root/name).mkdir()
                self.assertEqual([e.name for e in viewer.get_navigation()], ["inbox", "Music"])
                for name in ("archive", "assets", "Trash", "inbox", "notes"):
                    with self.subTest(name=name), self.assertRaises(HTTPException):
                        viewer.create_folder(viewer.FolderCreate(name=name))
                    with self.assertRaises(HTTPException):
                        viewer.get_fragments("notes", name)



class TestRemoveThumbnail(unittest.TestCase):
    def test_removed_card_thumbnail_moves_to_trash_unless_shared(self):
        for shared in (False, True):
            with self.subTest(shared=shared), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                inbox, assets, archive, trash = [root/n for n in ('inbox', 'assets', 'archive', 'Trash')]
                for directory in (inbox, assets, archive):
                    directory.mkdir()
                image = assets/'thumb.webp'
                image.write_bytes(b'image')
                note = inbox/'test.md'
                note.write_text('text\nhttps://example.com\ntitle: Example\n![](../assets/thumb.webp)  \n')
                if shared:
                    (archive/'other.md').write_text('![](../assets/thumb.webp)')
                with patch.multiple(viewer, ACTIVE_DIR=root, ROOT_DIR=root, INBOX_DIR=inbox, ASSETS_DIR=assets, ARCHIVE_DIR=archive, TRASH_DIR=trash):
                    viewer.update_fragment('test', viewer.FragmentUpdate(content='text', remove_unused_thumbnails=True))
                self.assertEqual(image.exists(), shared)
                self.assertEqual(note.read_text(), 'text')
                if not shared:
                    self.assertEqual(len(list(trash.rglob('thumb.webp'))), 1)



class TestActiveLayout(unittest.TestCase):
    def test_new_posts_use_active_without_touching_legacy_notes(self):
        import fragmentbox
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active, assets = root/'active', root/'assets'
            (root/'Music').mkdir()
            legacy = root/'Music/old.md'
            legacy.write_text('unchanged')
            assets.mkdir()
            image = assets/'image.webp'
            image.write_bytes(b'image')
            with patch.multiple(viewer, ROOT_DIR=root, ACTIVE_DIR=active, INBOX_DIR=active/'inbox',
                                ASSETS_DIR=assets, ARCHIVE_DIR=root/'archive', TRASH_DIR=root/'Trash'):
                viewer.create_folder(viewer.FolderCreate(name='Music'))
                result = viewer.create_fragment(viewer.FragmentCreate(content='![](/assets/image.webp)'), 'notes', 'Music')
                stored = active/'Music'/f'{result.fragment.id}.md'
                self.assertIn('../../assets/image.webp', stored.read_text())
                self.assertEqual([f.name for f in viewer.get_navigation()], ['inbox', 'Music'])
                self.assertEqual(legacy.read_text(), 'unchanged')
                self.assertEqual((stored.parent/'../../assets/image.webp').resolve(), image.resolve())
                self.assertEqual((root/'archive/Music/../../assets/image.webp').resolve(), image.resolve())
            with patch.object(fragmentbox, 'INBOX_DIR', active/'inbox'):
                self.assertEqual(fragmentbox._image_reference(image), '../../assets/image.webp')



class TestImageLinkRepair(unittest.TestCase):
    def test_detect_and_repair_only_broken_local_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root/'active/Music'
            directory.mkdir(parents=True)
            assets = root/'assets'
            assets.mkdir()
            (assets/'image.webp').write_bytes(b'image')
            note = directory/'note.md'
            original = '![](../assets/image.webp)  \n![](../../assets/image.webp)  \n![](../assets/missing.webp)\n![](https://example.com/image.webp)\n'
            note.write_text(original)
            with patch.multiple(viewer, ACTIVE_DIR=root/'active', ASSETS_DIR=assets):
                fragment = viewer.parse_fragment(note)
                self.assertEqual([link.status for link in fragment.image_links], ['corrected', 'ok', 'missing'])
                self.assertEqual(note.read_text(), original)
                updated = viewer.repair_image_links('note', viewer.FragmentUpdate(content=fragment.content), 'notes', 'Music')
                self.assertNotIn('corrected', [link.status for link in updated.image_links])
                self.assertEqual(note.read_text(), original.replace('../assets/image.webp)', '../../assets/image.webp)', 1))
                with self.assertRaises(HTTPException) as ctx:
                    viewer.repair_image_links('note', viewer.FragmentUpdate(content='stale'), 'notes', 'Music')
                self.assertEqual(ctx.exception.status_code, 409)



class TestMoveFragment(unittest.TestCase):
    def test_move_round_trip_and_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active = root/'active'
            inbox, music = active/'inbox', active/'Music'
            inbox.mkdir(parents=True)
            music.mkdir()
            assets = root/'assets'
            assets.mkdir()
            image = assets/'a.webp'
            image.write_bytes(b'image')
            note = inbox/'note.md'
            content = 'body ![](../../assets/a.webp)'
            note.write_text(content)
            timestamp = note.stat().st_mtime_ns
            with patch.multiple(viewer, ACTIVE_DIR=active, INBOX_DIR=inbox, ASSETS_DIR=assets):
                viewer.move_fragment('note', viewer.FragmentMove(source='notes', folder='Music'), 'inbox', '')
                target = music/'note.md'
                self.assertFalse(note.exists())
                self.assertEqual(target.read_text(), content)
                self.assertEqual(target.stat().st_mtime_ns, timestamp)
                note.write_text('collision')
                with self.assertRaises(HTTPException) as ctx:
                    viewer.move_fragment('note', viewer.FragmentMove(source='inbox'), 'notes', 'Music')
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(note.read_text(), 'collision')
                self.assertEqual(target.read_text(), content)
                note.unlink()
                viewer.move_fragment('note', viewer.FragmentMove(source='inbox'), 'notes', 'Music')
                self.assertEqual(note.read_text(), content)
                self.assertFalse(target.exists())
                self.assertEqual(image.read_bytes(), b'image')

    def test_move_invalid_destinations_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = Path(tmp)/'active'
            inbox = active/'inbox'
            inbox.mkdir(parents=True)
            music = active/'Music'
            music.mkdir()
            note = inbox/'note.md'
            note.write_text('original')
            with patch.multiple(viewer, ACTIVE_DIR=active, INBOX_DIR=inbox):
                for body in [viewer.FragmentMove(source='inbox'), viewer.FragmentMove(source='notes'),
                             viewer.FragmentMove(source='notes', folder='../archive'),
                             viewer.FragmentMove(source='notes', folder='missing')]:
                    with self.assertRaises(HTTPException):
                        viewer.move_fragment('note', body, 'inbox', '')
                with self.assertRaises(HTTPException) as ctx:
                    viewer.move_fragment('note', viewer.FragmentMove(source='inbox'), 'archive', 'Music')
                self.assertEqual(ctx.exception.status_code, 422)
                with patch.object(viewer.shutil, 'copystat', side_effect=OSError('failed')):
                    with self.assertRaises(HTTPException) as ctx:
                        viewer.move_fragment('note', viewer.FragmentMove(source='notes', folder='Music'), 'inbox', '')
                    self.assertEqual(ctx.exception.status_code, 500)
                self.assertEqual(note.read_text(), 'original')
                self.assertFalse((music/'note.md').exists())


class TestArchiveFragment(unittest.TestCase):
    def test_restore_preserves_content_assets_and_recreates_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active, archive, assets = root/'active', root/'archive', root/'assets'
            assets.mkdir()
            image = assets/'a.webp'
            image.write_bytes(b'image')
            with patch.multiple(viewer, ACTIVE_DIR=active, INBOX_DIR=active/'inbox', ARCHIVE_DIR=archive, ASSETS_DIR=assets):
                for folder in ['inbox', 'Music']:
                    directory = archive/folder
                    directory.mkdir(parents=True)
                    note = directory/'test.md'
                    content = 'body\n![](../../assets/a.webp)  \n'
                    note.write_text(content)
                    timestamp = note.stat().st_mtime_ns
                    result = viewer.restore_fragment('test', 'archive', folder)
                    destination = active/folder/'test.md'
                    self.assertEqual(result.status, 'restored')
                    self.assertFalse(note.exists())
                    self.assertEqual(destination.read_text(), content)
                    self.assertEqual(destination.stat().st_mtime_ns, timestamp)
                    self.assertEqual(image.read_bytes(), b'image')
                    note.write_text('second')
                    with self.assertRaises(HTTPException) as ctx:
                        viewer.restore_fragment('test', 'archive', folder)
                    self.assertEqual(ctx.exception.status_code, 409)
                    self.assertEqual(note.read_text(), 'second')
                    self.assertEqual(destination.read_text(), content)

    def test_restore_rejects_invalid_scope_and_rolls_back_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive, active = root/'archive', root/'active'
            directory = archive/'Music'
            directory.mkdir(parents=True)
            note = directory/'test.md'
            note.write_text('original')
            with patch.multiple(viewer, ACTIVE_DIR=active, ARCHIVE_DIR=archive, INBOX_DIR=active/'inbox'):
                for source, folder in [('inbox', ''), ('archive', ''), ('archive', '../Music')]:
                    with self.assertRaises(HTTPException) as ctx:
                        viewer.restore_fragment('test', source, folder)
                    self.assertEqual(ctx.exception.status_code, 422)
                with patch.object(viewer.shutil, 'copystat', side_effect=OSError('failed')):
                    with self.assertRaises(HTTPException) as ctx:
                        viewer.restore_fragment('test', 'archive', 'Music')
                    self.assertEqual(ctx.exception.status_code, 500)
                self.assertEqual(note.read_text(), 'original')
                self.assertFalse((active/'Music'/'test.md').exists())
                (active/'Music').rmdir()
                (active/'Music').symlink_to(directory, target_is_directory=True)
                with self.assertRaises(HTTPException) as ctx:
                    viewer.restore_fragment('test', 'archive', 'Music')
                self.assertEqual(ctx.exception.status_code, 422)

    def test_archive_preserves_folder_content_and_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active, archive, assets = root/'active', root/'archive', root/'assets'
            assets.mkdir()
            image = assets/'a.webp'
            image.write_bytes(b'image')
            with patch.multiple(viewer, ACTIVE_DIR=active, INBOX_DIR=active/'inbox', ARCHIVE_DIR=archive, ASSETS_DIR=assets):
                for source, folder in [('inbox', ''), ('notes', 'Music')]:
                    directory = active/(folder or 'inbox')
                    directory.mkdir(parents=True)
                    note = directory/'test.md'
                    content = 'body\n![](../../assets/a.webp)  \n'
                    note.write_text(content)
                    viewer.archive_fragment('test', source, folder)
                    destination = archive/directory.name/'test.md'
                    self.assertFalse(note.exists())
                    self.assertEqual(destination.read_text(), content)
                    self.assertTrue(image.exists())
                    note.write_text('second')
                    with self.assertRaises(HTTPException) as ctx:
                        viewer.archive_fragment('test', source, folder)
                    self.assertEqual(ctx.exception.status_code, 409)
                    self.assertEqual(note.read_text(), 'second')
                    self.assertEqual(destination.read_text(), content)
                with self.assertRaises(HTTPException):
                    viewer.archive_fragment('test', 'archive', 'Music')


if __name__ == "__main__":
    unittest.main()
