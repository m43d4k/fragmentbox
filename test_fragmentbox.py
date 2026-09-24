"""fragmentbox.py のユニットテスト。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

import fragmentbox


class TestYouTubeMetadata(unittest.TestCase):
    def test_short_url_uses_preview_metadata_without_video_extraction(self):
        import io
        import json
        from unittest.mock import patch
        from urllib.parse import parse_qs, urlsplit
        url = 'https://youtu.be/-w0bzICBWeo?si=g04Zl1xGDKyL0T18'
        response = io.BytesIO(json.dumps({'title': 'Hallelujah', 'author_name': 'Channel', 'thumbnail_url': 'https://i.ytimg.com/vi/-w0bzICBWeo/hqdefault.jpg'}).encode())
        with patch('urllib.request.urlopen', return_value=response) as fetch:
            meta = fragmentbox._fetch_metadata(url)
        self.assertEqual(meta['title'], 'Hallelujah')
        self.assertEqual(meta['sitename'], 'YouTube')
        self.assertEqual(meta['description'], 'Channel')
        self.assertEqual(meta['image_url'], 'https://i.ytimg.com/vi/-w0bzICBWeo/hqdefault.jpg')
        self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0].full_url).query)['url'], [url])

    def test_missing_title_is_reported(self):
        import io
        from unittest.mock import patch
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{}')):
            with self.assertRaises(ValueError):
                fragmentbox._fetch_youtube('https://youtu.be/-w0bzICBWeo')


class TestRedditMetadata(unittest.TestCase):
    def test_post_uses_oembed_title_and_site_name(self):
        import io
        import json
        from unittest.mock import patch
        from urllib.parse import parse_qs, urlsplit
        url = 'https://www.reddit.com/r/Drumkits/comments/f2t7mu/title/?utm_source=amp&utm_medium'
        response = io.BytesIO(json.dumps({'title': 'KAYTRANADA Kit: 192 samples', 'provider_name': 'reddit'}).encode())
        with patch('urllib.request.urlopen', return_value=response) as fetch:
            meta = fragmentbox._fetch_metadata(url)
        self.assertEqual(meta['title'], 'r/Drumkits - KAYTRANADA Kit: 192 samples')
        self.assertEqual(meta['sitename'], 'Reddit')
        self.assertEqual(meta['description'], '')
        endpoint = fetch.call_args.args[0].full_url
        self.assertEqual(parse_qs(urlsplit(endpoint).query)['url'], ['https://www.reddit.com/r/Drumkits/comments/f2t7mu/title/'])

    def test_generic_title_is_not_saved_as_post_title(self):
        import io
        from unittest.mock import patch
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"title":"Reddit"}')):
            with self.assertRaises(ValueError):
                fragmentbox._fetch_reddit('https://www.reddit.com/r/test/comments/abc/post/')

    def test_other_sites_and_non_post_pages_use_general_fetch(self):
        from unittest.mock import patch
        for url in ['https://reddit.com.example.org/r/test/comments/abc/', 'https://www.reddit.com/r/Drumkits/']:
            with patch.object(fragmentbox, '_fetch_general', return_value={}) as general:
                fragmentbox._fetch_metadata(url)
                general.assert_called_once_with(url)


class TestLinkTitle(unittest.TestCase):
    def test_page_title_precedes_navigation_heading(self):
        import io
        from unittest.mock import patch
        page = '<html><head><meta charset="utf-8"><title>HIGHER ハイヤー 帽子</title></head><body><h1>ITEM LIST</h1></body></html>'
        with patch('urllib.request.urlopen', return_value=io.BytesIO(page.encode())):
            self.assertEqual(fragmentbox._fetch_general('https://example.com')['title'], 'HIGHER ハイヤー 帽子')

    def test_title_priority_and_empty_values(self):
        from trafilatura.utils import load_html
        for head, expected in [
            ('<meta property="og:title" content="OG &amp; title"><meta name="twitter:title" content="Twitter"><title>Page</title>', 'OG & title'),
            ('<meta property="og:title" content=" "><meta name="twitter:title" content="Twitter"><title>Page</title>', 'Twitter'),
            ('<title> Page   title </title>', 'Page title'),
            ('<title> </title>', 'Heading'),
        ]:
            with self.subTest(head=head):
                self.assertEqual(fragmentbox._link_title(load_html('<html><head>'+head+'</head><body>text</body></html>'), 'Heading'), expected)


class TestLinkImage(unittest.TestCase):
    def test_first_og_image_wins_over_site_default(self):
        import io
        from unittest.mock import patch
        page = '<html><head><title>Article</title><meta property="og:image" content="/images/bb45.jpg"><meta property="og:image" content="/default.png"><meta name="twitter:image" content="/twitter.jpg"></head><body>Article</body></html>'
        with patch('urllib.request.urlopen', return_value=io.BytesIO(page.encode())):
            meta = fragmentbox._fetch_general('https://example.com/blog/article')
            self.assertEqual(meta['image_urls'], ['https://example.com/images/bb45.jpg', 'https://example.com/default.png'])

    def test_empty_images_and_twitter_fallback(self):
        from trafilatura.utils import load_html
        for head, expected in [
            ('<meta property="og:image" content=" "><meta name="twitter:image" content=" /photo.jpg ">', '/photo.jpg'),
            ('<title>Article</title>', '/fallback.jpg'),
        ]:
            with self.subTest(head=head):
                self.assertEqual(fragmentbox._link_image(load_html('<html><head>'+head+'</head></html>'), '/fallback.jpg'), expected)


class TestBinaryThumbnail(unittest.TestCase):
    def test_only_gif_binary_is_accepted(self):
        import io
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        for data, accepted in [(b'GIF89a' + b'test', True), (b'<html>error</html>', False)]:
            response = io.BytesIO(data)
            response.headers = {'Content-Type': 'application/octet-stream'}
            with tempfile.TemporaryDirectory() as tmp:
                with patch('urllib.request.urlopen', return_value=response), patch.object(fragmentbox, 'import_image', return_value=Path(tmp)/'image.gif') as importer:
                    result = fragmentbox._download_thumbnail('https://example.com/image.gif', Path(tmp))
                    self.assertEqual(result is not None, accepted)
                    self.assertEqual(importer.called, accepted)


class TestDropTextEditPaste(unittest.TestCase):
    """貼り付けたテキストがプレーンテキストになることを確認する。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.editor = fragmentbox.DropTextEdit()

    def tearDown(self):
        self.editor.close()

    def test_rich_text_is_inserted_without_formatting(self):
        mime_data = QMimeData()
        mime_data.setHtml('<p><b style="color: red">太字</b><br>テキスト</p>')
        mime_data.setText("太字\nテキスト")

        self.editor.insertFromMimeData(mime_data)

        self.assertEqual(self.editor.toPlainText(), "太字\nテキスト")
        cursor = self.editor.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        char_format = cursor.charFormat()
        self.assertEqual(char_format.fontWeight(), 400)
        self.assertEqual(char_format.foreground().style(), Qt.BrushStyle.NoBrush)

    def test_plain_text_and_markdown_are_unchanged(self):
        text = "日本語とURL https://example.com\n**Markdown** #タグ"
        mime_data = QMimeData()
        mime_data.setText(text)

        self.editor.insertFromMimeData(mime_data)

        self.assertEqual(self.editor.toPlainText(), text)

    def test_paste_replaces_selected_text(self):
        self.editor.setPlainText("置換前の文字列")
        cursor = self.editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(3, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        mime_data = QMimeData()
        mime_data.setHtml("<i>置換後</i>")
        mime_data.setText("置換後")

        self.editor.insertFromMimeData(mime_data)

        self.assertEqual(self.editor.toPlainText(), "置換後の文字列")


if __name__ == "__main__":
    unittest.main()
