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
        self.assertEqual(frag.content, "  前後に空白")

    def test_tags_extracted(self):
        path = self._write_temp_md("アイデアメモ\n\n#idea #todo", stem="20240315_093000")
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
            body = viewer.FragmentUpdate(content="更新後\n\n#newtag")
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
            (self.root / name / "same.md").write_text(name + "\n\n#test")
        self.assertEqual(viewer.get_fragments("notes", "音楽")[0].content, "音楽\n\n#test")
        viewer.update_fragment("same", viewer.FragmentUpdate(content="変更"), "notes", "音楽")
        self.assertEqual((self.root / "開発/same.md").read_text(), "開発\n\n#test")
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

    def test_delete_targets_selected_folder(self):
        for name in ("a", "b"):
            (self.root / name).mkdir()
            (self.root / name / "same.md").write_text(name)
        viewer.delete_fragment("same", "notes", "a")
        self.assertFalse((self.root / "a/same.md").exists())
        self.assertEqual((self.root / "b/same.md").read_text(), "b")
        viewer.delete_fragment("same", "notes", "b")
        self.assertFalse((self.root / "b/same.md").exists())



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
        body = viewer.FragmentCreate(content="メモ\n\n#音楽")
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
                                ASSETS_DIR=root/"assets"):
                for name in ("inbox", "archive", "assets", "notes", "Music"):
                    (root/name).mkdir()
                self.assertEqual([e.name for e in viewer.get_navigation()], ["inbox", "Music"])
                for name in ("archive", "assets", "inbox", "notes"):
                    with self.subTest(name=name), self.assertRaises(HTTPException):
                        viewer.create_folder(viewer.FolderCreate(name=name))
                    with self.assertRaises(HTTPException):
                        viewer.get_fragments("notes", name)



class TestRemoveThumbnail(unittest.TestCase):
    def test_removed_card_thumbnail_is_deleted_unless_shared(self):
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
                with patch.multiple(viewer, ACTIVE_DIR=root, ROOT_DIR=root, INBOX_DIR=inbox, ASSETS_DIR=assets, ARCHIVE_DIR=archive):
                    viewer.update_fragment('test', viewer.FragmentUpdate(content='text', remove_unused_thumbnails=True))
                self.assertEqual(image.exists(), shared)
                self.assertEqual(note.read_text(), 'text')
                self.assertFalse(trash.exists())



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
                                ASSETS_DIR=assets, ARCHIVE_DIR=root/'archive'):
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



class TestMultipleThumbnails(unittest.TestCase):
    def test_all_link_images_are_saved_and_recognized_for_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root/'assets'
            assets.mkdir()
            paths = [assets/'a.jpg', assets/'b.jpg']
            for path in paths:
                path.write_bytes(b'image')
            from unittest.mock import patch
            with patch.multiple(viewer, ASSETS_DIR=assets), patch.object(viewer.capture, '_fetch_metadata', return_value={'title': 'Title', 'image_urls': ['https://example.com/a.jpg', 'https://example.com/b.jpg']}), patch.object(viewer.capture, '_download_thumbnail', side_effect=paths):
                content, warnings = viewer._enrich_post('https://example.com')
                self.assertFalse(warnings)
                self.assertIn('![](/assets/a.jpg)', content)
                self.assertIn('![](/assets/b.jpg)', content)
                content = content.replace('/assets/', '../../assets/')
                self.assertEqual(viewer._thumbnail_references(content, root/'active'/'inbox'/'note.md'), {path.resolve() for path in paths})


class TestTagRename(unittest.TestCase):
    def test_rename_only_selected_folder_and_its_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            active, archive = root/'active', root/'archive'
            for directory in [active/'Music', archive/'Music', active/'Other', active/'inbox']:
                directory.mkdir(parents=True)
                (directory/'note.md').write_text('#音楽 #音楽制作\nhttps://example.com/#音楽\ntitle: #音楽\n')
            with patch.multiple(viewer, ACTIVE_DIR=active, INBOX_DIR=active/'inbox', ARCHIVE_DIR=archive):
                result = viewer.rename_tag(viewer.TagRename(old='音楽', new='music'), 'notes', 'Music')
                self.assertEqual(result.count, 2)
                for directory in [active/'Music', archive/'Music']:
                    self.assertEqual((directory/'note.md').read_text(), '#music #音楽制作\nhttps://example.com/#音楽\ntitle: #音楽\n')
                self.assertTrue((active/'Other'/'note.md').read_text().startswith('#音楽 '))
                with self.assertRaises(HTTPException):
                    viewer.rename_tag(viewer.TagRename(old='music', new='bad tag'), 'notes', 'Music')
                with self.assertRaises(HTTPException):
                    viewer.rename_tag(viewer.TagRename(old='music', new='ok'), 'archive', '')

    def test_inbox_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox, archived = root/'active'/'inbox', root/'archive'/'inbox'
            for directory in [inbox, archived]:
                directory.mkdir(parents=True)
                (directory/'note.md').write_text('#old')
            with patch.multiple(viewer, ACTIVE_DIR=root/'active', INBOX_DIR=inbox, ARCHIVE_DIR=root/'archive'):
                original_write = viewer._atomic_write
                calls = 0
                def failing_write(path, data):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise OSError('failed')
                    original_write(path, data)
                with patch.object(viewer, '_atomic_write', side_effect=failing_write):
                    with self.assertRaises(HTTPException):
                        viewer.rename_tag(viewer.TagRename(old='old', new='new'))
                for directory in [inbox, archived]:
                    self.assertEqual((directory/'note.md').read_text(), '#old')
                self.assertEqual(viewer.rename_tag(viewer.TagRename(old='old', new='new')).count, 2)


class TestEditLinkEnrichment(unittest.TestCase):
    def test_edit_fetches_new_link_images_and_preserves_existing_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            folder, assets = root/'active'/'Music', root/'assets'
            folder.mkdir(parents=True)
            assets.mkdir()
            note = folder/'note.md'
            original = 'https://example.com/old\ntitle: Old\n'
            note.write_text(original)
            images = [assets/'a.webp', assets/'b.webp']
            for image in images:
                image.write_bytes(b'image')
            with patch.multiple(viewer, ROOT_DIR=root, ACTIVE_DIR=root/'active', ASSETS_DIR=assets), patch.object(viewer.capture, '_fetch_metadata', return_value={'title': 'New', 'image_urls': ['https://example.com/a', 'https://example.com/b']}) as fetch, patch.object(viewer.capture, '_download_thumbnail', side_effect=images):
                result = viewer.update_fragment('note', viewer.FragmentUpdate(content=original+'\nhttps://example.com/new', enrich_links=True), 'notes', 'Music')
            fetch.assert_called_once_with('https://example.com/new')
            self.assertIn('title: Old', result.content)
            self.assertIn('title: New', result.content)
            self.assertIn('![](../../assets/a.webp)', note.read_text())
            self.assertIn('![](../../assets/b.webp)', note.read_text())
            self.assertEqual(result.warnings, [])

    def test_edit_preserves_text_and_returns_warning_on_fetch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'note.md').write_text('old')
            with patch.object(viewer, 'INBOX_DIR', root), patch.object(viewer.capture, '_fetch_metadata', side_effect=OSError('offline')):
                result = viewer.update_fragment('note', viewer.FragmentUpdate(content='https://example.com', enrich_links=True))
            self.assertEqual(result.content, 'https://example.com')
            self.assertTrue(result.warnings)


class TestFolderManagement(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.active, self.archive, self.assets = [self.root/n for n in ('active', 'archive', 'assets')]
        for path in (self.active/'Music', self.active/'inbox', self.archive/'Music', self.assets):
            path.mkdir(parents=True)
        self.patcher = patch.multiple(viewer, ROOT_DIR=self.root, ACTIVE_DIR=self.active,
                                     INBOX_DIR=self.active/'inbox', ARCHIVE_DIR=self.archive, ASSETS_DIR=self.assets)
        self.patcher.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.patcher.stop)

    def test_rename_preserves_articles_archive_and_order(self):
        content = '![](../../assets/picture.webp)'
        for root in (self.active, self.archive):
            (root/'Music'/'note.md').write_text(content)
        viewer.reorder_navigation(viewer.FolderOrder(names=['notes:Music', 'inbox:']))
        viewer.rename_folder('Music', viewer.FolderCreate(name='音楽'))
        for root in (self.active, self.archive):
            self.assertFalse((root/'Music').exists())
            self.assertEqual((root/'音楽'/'note.md').read_text(), content)
        self.assertEqual([f.id for f in viewer.get_navigation()], ['notes:音楽', 'inbox:'])

    def test_rename_rejects_inbox_collisions_and_rolls_back(self):
        for name in ['inbox', '../outside']:
            with self.assertRaises(HTTPException):
                viewer.rename_folder(name, viewer.FolderCreate(name='New'))
        (self.archive/'Other').mkdir()
        with self.assertRaises(HTTPException) as ctx:
            viewer.rename_folder('Music', viewer.FolderCreate(name='Other'))
        self.assertEqual(ctx.exception.status_code, 409)
        viewer.reorder_navigation(viewer.FolderOrder(names=['notes:Music', 'inbox:']))
        with patch.object(viewer, '_atomic_write', side_effect=OSError('failed')):
            with self.assertRaises(HTTPException):
                viewer.rename_folder('Music', viewer.FolderCreate(name='New'))
        self.assertTrue((self.active/'Music').exists())
        self.assertTrue((self.archive/'Music').exists())
        self.assertFalse((self.active/'New').exists())

    def test_delete_folder_preserves_archive_and_shared_images(self):
        for name in ['only.webp', 'shared.webp', 'unrelated.webp']:
            (self.assets/name).write_bytes(b'image')
        (self.active/'Music'/'a.md').write_text('![](../../assets/only.webp)\n![](../../assets/shared.webp)')
        (self.archive/'Music'/'b.md').write_text('![](../../assets/shared.webp)')
        preview = viewer.preview_folder_delete('Music')
        self.assertEqual(preview.count, 1)
        viewer.delete_folder('Music', viewer.FolderDeleteRequest(revision=preview.revision))
        self.assertFalse((self.active/'Music').exists())
        self.assertTrue((self.archive/'Music'/'b.md').exists())
        self.assertFalse((self.assets/'only.webp').exists())
        self.assertTrue((self.assets/'shared.webp').exists())
        self.assertTrue((self.assets/'unrelated.webp').exists())
        self.assertFalse((self.root/'Trash').exists())
        self.assertEqual([f.id for f in viewer.get_navigation()], ['inbox:'])

    def test_delete_checks_preview_and_rejects_unknown_contents(self):
        preview = viewer.preview_folder_delete('Music')
        note = self.active/'Music'/'a.md'
        note.write_text('new')
        with self.assertRaises(HTTPException) as ctx:
            viewer.delete_folder('Music', viewer.FolderDeleteRequest(revision=preview.revision))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(note.read_text(), 'new')
        with self.assertRaises(HTTPException):
            viewer.preview_folder_delete('inbox')
        (self.active/'Music'/'nested').mkdir()
        with self.assertRaises(HTTPException):
            viewer.preview_folder_delete('Music')

    def test_article_deletion_cleans_images_and_preserves_archive_reference(self):
        (self.assets/'only.webp').write_bytes(b'image')
        (self.assets/'shared.webp').write_bytes(b'image')
        note = self.active/'Music'/'a.md'
        note.write_text('![](../../assets/only.webp)\n![](../../assets/shared.webp)')
        (self.archive/'Music'/'b.md').write_text('![](../../assets/shared.webp)')
        result = viewer.delete_fragment('a', 'notes', 'Music')
        self.assertEqual(result.status, 'deleted')
        self.assertFalse(note.exists())
        self.assertFalse((self.assets/'only.webp').exists())
        self.assertTrue((self.assets/'shared.webp').exists())


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




class TestAttachments(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.inbox = self.root / 'inbox'
        self.inbox.mkdir()
        self.active = self.root / 'active'
        self.active.mkdir()
        (self.active / '資料').mkdir()
        self.patcher = patch.multiple(viewer, ROOT_DIR=self.root, ASSETS_DIR=self.assets,
                                     INBOX_DIR=self.inbox, ACTIVE_DIR=self.active,
                                     ARCHIVE_DIR=self.root / 'archive')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def request(self, data=b'', headers=True, client='127.0.0.1'):
        from starlette.requests import Request
        async def receive():
            return {'type': 'http.request', 'body': data, 'more_body': False}
        return Request({'type': 'http', 'method': 'POST', 'path': '/', 'scheme': 'http',
                        'server': ('127.0.0.1', 8765), 'client': (client, 1234),
                        'headers': [(b'host', b'127.0.0.1:8765')] +
                        ([(b'x-fragmentbox-open', b'1')] if headers else [])}, receive)

    def upload(self, name='余白 [資料].PDF', data=b'%PDF-1.4 test'):
        import asyncio
        return asyncio.run(viewer.upload_attachment(self.request(data), name))

    def test_upload_card_move_archive_restore_delete(self):
        uploaded = self.upload()
        post = viewer.create_fragment(viewer.FragmentCreate(content=uploaded.markdown), 'inbox')
        card = post.fragment.attachments[0]
        self.assertEqual(card.name, '余白 [資料].PDF')
        self.assertEqual(card.size, 13)
        asset = self.assets / card.asset
        self.assertEqual(asset.read_bytes(), b'%PDF-1.4 test')
        viewer.move_fragment(post.fragment.id, viewer.FragmentMove(source='notes', folder='資料'), 'inbox')
        viewer.archive_fragment(post.fragment.id, 'notes', '資料')
        archived = viewer.parse_fragment(self.root / 'archive' / '資料' / f'{post.fragment.id}.md')
        self.assertEqual(archived.attachments[0].size, 13)
        viewer.restore_fragment(post.fragment.id, 'archive', '資料')
        viewer.delete_fragment(post.fragment.id, 'notes', '資料')
        self.assertFalse(asset.exists())

    def test_edit_attaches_file_and_normalizes_reference(self):
        post = viewer.create_fragment(viewer.FragmentCreate(content="元の記事"), 'inbox').fragment
        uploaded = self.upload()
        updated = viewer.update_fragment(post.id, viewer.FragmentUpdate(
            content="編集済み\n" + uploaded.markdown, enrich_links=True), 'inbox')
        self.assertEqual(updated.attachments[0].name, '余白 [資料].PDF')
        self.assertIn('](../assets/attachment_', updated.content)
        self.assertTrue(updated.content.startswith('編集済み\n'))
        self.assertEqual(updated.attachments[0].size, 13)

    def test_shared_attachment_survives_deletion(self):
        upload = self.upload()
        first = viewer.create_fragment(viewer.FragmentCreate(content=upload.markdown), 'inbox').fragment
        second = viewer.create_fragment(viewer.FragmentCreate(content=upload.markdown), 'notes', '資料').fragment
        viewer.delete_fragment(first.id, 'inbox')
        self.assertTrue((self.assets / second.attachments[0].asset).exists())

    def test_reject_bad_empty_oversize_upload_and_clean_up(self):
        for name, data in [('run.command', b'x'), ('../doc.pdf', b'x'), ('empty.txt', b''), ('big.wav', b'1234')]:
            with self.subTest(name=name), patch.object(viewer.capture, 'ATTACHMENT_MAX_BYTES', 3):
                with self.assertRaises(HTTPException):
                    self.upload(name, data)
        self.assertEqual(list(self.assets.iterdir()), [])

    def test_open_is_local_explicit_and_restricted(self):
        uploaded = self.upload()
        fragment = viewer.create_fragment(viewer.FragmentCreate(content=uploaded.markdown), 'inbox').fragment
        asset = fragment.attachments[0].asset
        with patch.object(viewer.sys, 'platform', 'darwin'), patch.object(viewer.subprocess, 'run') as run:
            viewer.open_attachment(asset, self.request())
            self.assertEqual(run.call_args.args[0], ['/usr/bin/open', str(self.assets / asset)])
            for bad in [self.request(headers=False), self.request(client='192.168.1.2')]:
                with self.assertRaises(HTTPException):
                    viewer.open_attachment(asset, bad)
            for name in ['../outside.pdf', 'manual.pdf', 'attachment_' + 'a' * 32 + '.command']:
                with self.assertRaises(HTTPException):
                    viewer.open_attachment(name, self.request())
            (self.assets / asset).unlink()
            (self.assets / asset).symlink_to(self.root / 'outside.pdf')
            with self.assertRaises(HTTPException):
                viewer.open_attachment(asset, self.request())
            self.assertEqual(run.call_count, 1)


class TestStandaloneTags(unittest.TestCase):
    def test_non_tag_contexts_are_excluded(self):
        contexts = [
            '本文 #音楽', 'https://example.com/#音楽', '## #音楽',
            '#音楽\n===', '#音楽\n---', 'title: #音楽',
            '[#音楽](https://example.com)', '![#音楽](image.png)',
            '```md\n#音楽\n```', '~~~\n#音楽\n~~~', '    #音楽', '\t#音楽',
            '`start\n#音楽\nend`', '**`start\n#音楽\nend`**',
            '> #音楽', '- #音楽', '<div>\n#音楽\n</div>',
            '---\ntitle: example\n#音楽\n---', '+++\n#音楽\n+++',
            '[label](https://example.com "start\n#音楽\nend")',
        ]
        for content in contexts:
            with self.subTest(content=content):
                self.assertEqual(viewer.capture.extract_tags(content), [])
                self.assertEqual(viewer._rename_tag_text(content, '音楽', 'music'), content)

    def test_standalone_lines_and_rename(self):
        content = '本文 #音楽\r\n#音楽 #制作\r\n\r\n  #音楽 #tag_1  \r\n'
        self.assertEqual(viewer.capture.extract_tags(content), ['音楽', '制作', 'tag_1'])
        self.assertEqual(viewer._rename_tag_text(content, '音楽', 'music'),
                         '本文 #音楽\r\n#music #制作\r\n\r\n  #music #tag_1  \r\n')

    def test_api_preserves_indented_code_and_only_lists_real_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'note.md'
            path.write_text('    #code\n\n本文 #body\n\n#real\n')
            fragment = viewer.parse_fragment(path)
            self.assertEqual(fragment.tags, ['real'])
            self.assertEqual(fragment.tag_lines, [4])
            with patch.object(viewer, '_source_dir', return_value=Path(tmp)):
                self.assertEqual(viewer.get_tags(), ['real'])

    def test_tag_button_analysis_ignores_body_and_code(self):
        for content in ['本文 #音楽', '```\n#音楽\n```', '    #音楽']:
            with self.subTest(content=content):
                result = viewer.analyze_tags(viewer.TagContent(content=content))
                self.assertEqual(result.tags, [])
                self.assertEqual(result.separator, '\n\n')
                self.assertFalse(viewer.capture._has_tag(content, '音楽'))
        result = viewer.analyze_tags(viewer.TagContent(content='本文\n\n#音楽'))
        self.assertEqual(result.tags, ['音楽'])
        self.assertEqual(result.separator, ' ')

    def test_favorite_preserves_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'note.md'
            original = '本文 #favorite\n```\n#favorite\n```'
            path.write_text(original)
            with patch.object(viewer, '_fragment_path', return_value=path):
                self.assertTrue(viewer.toggle_favorite('note').favorited)
                self.assertEqual(path.read_text(), original + '\n\n#favorite\n')
                self.assertFalse(viewer.toggle_favorite('note').favorited)
                self.assertEqual(path.read_text().rstrip(), original)


if __name__ == "__main__":
    unittest.main()
