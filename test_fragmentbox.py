"""fragmentbox.py のユニットテスト。"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

import fragmentbox


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
