import logging
import os
import re
import shutil
import sys
import tomllib
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "config.toml"

with CONFIG_FILE.open("rb") as _f:
    _config = tomllib.load(_f)

INBOX_DIR    = Path(_config["paths"]["inbox"]).expanduser()
ASSETS_DIR   = Path(_config["paths"]["assets"]).expanduser()
IMAGE_QUALITY = _config.get("images", {}).get("quality", 80)

IMAGE_EXTENSIONS      = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tiff", ".tif"}
_COPY_ONLY_EXTENSIONS = {".svg", ".gif"}  # このアプリでは無変換コピーする形式

URL_PATTERN     = re.compile(r'https?://\S+')
YOUTUBE_PATTERN = re.compile(r'https?://(www\.)?(youtube\.com|youtu\.be)/\S+')


def load_tags() -> list[str]:
    return _config.get("tags", {}).get("presets", [])


def save_fragment(text: str) -> Path:
    if not text.strip():
        raise ValueError("Cannot save empty fragment")
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = INBOX_DIR / f"{timestamp}.md"
    filepath.write_text(text, encoding="utf-8")
    return filepath


def import_image(src: Path) -> Path:
    """画像をアセットフォルダへ保存する。
    ラスター画像は pyvips で WebP に圧縮、SVG/GIF はそのままコピー。
    """
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique = uuid.uuid4().hex[:8]
    suffix = src.suffix.lower()

    if suffix in _COPY_ONLY_EXTENSIONS:
        new_name = f"{timestamp}_{unique}{suffix}"
        dest = ASSETS_DIR / new_name
        shutil.copy2(str(src), str(dest))
        return dest

    try:
        import pyvips
    except ImportError as e:
        raise ImportError(
            "pyvips が見つかりません。'pip install pyvips' を実行するか、"
            "libvips をインストールしてください。"
        ) from e

    new_name = f"{timestamp}_{unique}.webp"
    dest = ASSETS_DIR / new_name
    image = pyvips.Image.new_from_file(str(src)).autorot()
    image.webpsave(str(dest), Q=IMAGE_QUALITY)
    return dest


# --- メタデータ取得 ---

def _fetch_youtube(url: str) -> dict[str, str]:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "title": info.get("title") or "",
        "sitename": "YouTube",
        "description": info.get("channel") or info.get("uploader") or "",
        "image_url": info.get("thumbnail") or "",
    }


def _fetch_general(url: str) -> dict[str, str]:
    import trafilatura
    from urllib.parse import urljoin
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return {}
    meta = trafilatura.extract_metadata(downloaded)
    if not meta:
        return {}
    image_url = meta.image or ""
    if image_url:
        image_url = urljoin(url, image_url)  # 相対URLを絶対URLに解決
    return {
        "title": meta.title or "",
        "sitename": meta.sitename or "",
        "description": meta.description or "",
        "image_url": image_url,
    }


_THUMBNAIL_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _download_thumbnail(image_url: str) -> Path | None:
    """サムネイル画像URLをダウンロードし、import_image() で保存する。"""
    import tempfile
    import urllib.request
    from urllib.parse import urlparse

    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".jpg"

    fd, tmp = tempfile.mkstemp(suffix=suffix)
    tmp_path = Path(tmp)
    try:
        req = urllib.request.Request(
            image_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; fragmentbox)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                logger.warning("Thumbnail skipped: Content-Type=%r for %s", content_type, image_url)
                return None
            content_length = resp.headers.get("Content-Length")
            try:
                cl_int = int(content_length) if content_length else None
            except ValueError:
                cl_int = None
            if cl_int is not None and cl_int > _THUMBNAIL_MAX_BYTES:
                logger.warning("Thumbnail skipped: Content-Length=%s for %s", content_length, image_url)
                return None
            data = resp.read(_THUMBNAIL_MAX_BYTES + 1)
        if len(data) > _THUMBNAIL_MAX_BYTES:
            logger.warning("Thumbnail skipped: response exceeded %d bytes for %s", _THUMBNAIL_MAX_BYTES, image_url)
            return None
        import os
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        fd = -1
        return import_image(tmp_path)
    except Exception:
        logger.exception("Failed to download thumbnail: %s", image_url)
        return None
    finally:
        if fd != -1:
            import os
            os.close(fd)
        tmp_path.unlink(missing_ok=True)


def _fetch_metadata(url: str) -> dict[str, str]:
    if YOUTUBE_PATTERN.match(url):
        return _fetch_youtube(url)
    return _fetch_general(url)


def _find_urls_without_metadata(content: str) -> list[tuple[str, int]]:
    """本文中のURLのうち、直後の連続行に title: がないものを (url, occurrence_index) で返す。

    occurrence_index は同一URLの何番目の出現かを示す（0始まり）。
    """
    url_counts: dict[str, int] = {}
    results: list[tuple[str, int]] = []
    lines = content.splitlines()
    for i, line in enumerate(lines):
        for m in URL_PATTERN.finditer(line):
            url = m.group(0).rstrip(".,;:!?()'\">")
            # URL 行の直後の連続行（空行が来るまで）に title: があるか確認
            has_title = False
            j = i + 1
            while j < len(lines) and lines[j].strip():
                if lines[j].strip().startswith("title:"):
                    has_title = True
                    break
                j += 1
            if not has_title:
                idx = url_counts.get(url, 0)
                url_counts[url] = idx + 1
                results.append((url, idx))
    return results


def _insert_metadata(
    text_widget: "DropTextEdit", url: str, occurrence: int, meta: dict[str, str]
) -> None:
    lines = []
    if meta.get("title"):
        lines.append(f"title: {meta['title']}")
    if meta.get("sitename"):
        lines.append(f"sitename: {meta['sitename']}")
    if meta.get("description"):
        lines.append(f"description: {meta['description']}")
    if meta.get("thumbnail"):
        lines.append(f"![](../assets/{meta['thumbnail']})")
    if not lines:
        return

    content = text_widget.toPlainText()

    # occurrence 番目の出現位置を特定
    url_pos = -1
    for _ in range(occurrence + 1):
        url_pos = content.find(url, url_pos + 1)
        if url_pos == -1:
            return

    url_end = url_pos + len(url)
    line_end = content.find("\n", url_end)
    metadata_text = "".join(f"  \n{line}" for line in lines) + "  \n"

    cursor = text_widget.textCursor()
    cursor.beginEditBlock()

    # URL 行末にメタデータを挿入（後ろへの操作なので前の位置に影響しない）
    if line_end == -1:
        cursor.movePosition(cursor.MoveOperation.End)
    else:
        cursor.setPosition(line_end)
    cursor.insertText(metadata_text)

    # URL の前にハードブレーク（  \n）を付与
    if url_pos > 0:
        if content[url_pos - 1] == "\n":
            cursor.setPosition(url_pos - 1)
            cursor.setPosition(url_pos, cursor.MoveMode.KeepAnchor)
            cursor.insertText("  \n")
        else:
            cursor.setPosition(url_pos)
            cursor.insertText("  \n")

    cursor.endEditBlock()

    cursor.movePosition(cursor.MoveOperation.End)
    text_widget.setTextCursor(cursor)


def _set_status(label: QLabel, text: str, color: str) -> None:
    label.setText(text)
    label.setStyleSheet(f"color: {color}; font-size: 11px;")


def _do_save(text_widget: "DropTextEdit", status_label: QLabel) -> None:
    content = text_widget.toPlainText().strip()
    filepath = save_fragment(content)
    _set_status(status_label, f"Saved: {filepath.name}", "#27ae60")
    text_widget.clear()


def _apply_and_save(
    text_widget: "DropTextEdit",
    status_label: QLabel,
    results: list[tuple[str, int, dict[str, str]]],
) -> None:
    for url, occurrence, meta in results:
        _insert_metadata(text_widget, url, occurrence, meta)
    _do_save(text_widget, status_label)


class MetadataWorker(QThread):
    """バックグラウンドで URL メタデータを取得し、Signal で結果を返す。"""

    metadata_ready = Signal(list)  # list[tuple[str, int, dict[str, str]]]

    def __init__(self, urls_with_idx: list[tuple[str, int]], parent=None):
        super().__init__(parent)
        self._urls_with_idx = urls_with_idx

    def run(self):
        results: list[tuple[str, int, dict[str, str]]] = []
        for url, idx in self._urls_with_idx:
            try:
                meta = _fetch_metadata(url)
            except Exception:
                logger.exception("Failed to fetch metadata for %s", url)
                meta = {}

            image_url = meta.pop("image_url", "")
            if image_url:
                thumb = _download_thumbnail(image_url)
                if thumb:
                    meta["thumbnail"] = thumb.name

            results.append((url, idx, meta))
        self.metadata_ready.emit(results)


def _handle_image_path(
    text_widget: "DropTextEdit", status_label: QLabel, path: Path
) -> None:
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return
    try:
        dest = import_image(path)
        cursor = text_widget.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(f"![](../assets/{dest.name})  \n")
        _set_status(status_label, f"Image: {dest.name}", "#27ae60")
    except Exception as e:
        _set_status(status_label, f"Error: {e}", "#e74c3c")


# --- UI ---

class DropTextEdit(QTextEdit):
    """画像ファイルのドロップに対応した QTextEdit。"""

    image_dropped = Signal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def _image_urls(self, mime_data) -> list[Path]:
        return [
            Path(url.toLocalFile())
            for url in mime_data.urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS
        ]

    def dragEnterEvent(self, event):
        if self._image_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._image_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        paths = self._image_urls(event.mimeData())
        if paths:
            for path in paths:
                self.image_dropped.emit(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


_BTN_SS = """
    QPushButton {{
        background-color: #4a4a4a;
        color: #999999;
        border: none;
        padding: {pad};
        font-size: {size}px;
        {extra}
    }}
    QPushButton:hover {{ background-color: #5a5a5a; }}
"""


class FragmentBoxWindow(QWidget):
    def __init__(self):
        super().__init__()
        self._worker: MetadataWorker | None = None
        self._tags = load_tags()
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("fragmentbox")
        self.setFixedWidth(520)
        self.setStyleSheet("QWidget { background-color: #2b2b2b; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # テキストエリア + タグ列
        row = QHBoxLayout()
        row.setSpacing(0)

        self.text_area = DropTextEdit()
        self.text_area.setFixedHeight(160)
        self.text_area.setStyleSheet("""
            QTextEdit {
                background-color: #3c3f41;
                color: #f0f0f0;
                border: 1px solid #4a4a4a;
                padding: 8px;
                font-size: 13px;
            }
        """)
        self.text_area.image_dropped.connect(self._handle_image_drop)
        row.addWidget(self.text_area, 1)

        tag_col = QVBoxLayout()
        tag_col.setContentsMargins(8, 0, 0, 0)
        tag_col.setSpacing(4)
        for tag in self._tags:
            btn = QPushButton(f"#{tag}")
            btn.setStyleSheet(_BTN_SS.format(pad="4px 6px", size=11, extra=""))
            btn.clicked.connect(lambda checked, t=tag: self._insert_tag(t))
            tag_col.addWidget(btn)
        tag_col.addStretch()
        row.addLayout(tag_col)
        outer.addLayout(row)

        # ボトムバー
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        bottom.addWidget(self.status_label, 1)

        self.img_btn = QPushButton("IMG")
        self.img_btn.setStyleSheet(_BTN_SS.format(pad="6px 10px", size=11, extra=""))
        self.img_btn.clicked.connect(self._pick_images)
        bottom.addWidget(self.img_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet(
            _BTN_SS.format(pad="6px 16px", size=12, extra="font-weight: bold;")
        )
        self.save_btn.clicked.connect(self._on_save)
        bottom.addWidget(self.save_btn)

        outer.addLayout(bottom)

        # "Ctrl+Return": 文字列指定のため StandardKey と異なりプラットフォーム変換は保証されない
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._save_shortcut.activated.connect(self._on_save)
        # "Meta+Return": macOS で追加登録する保存ショートカット
        # Linux では Meta が Super 系になるため登録しない
        self._meta_return_shortcut: QShortcut | None = None
        if sys.platform == "darwin":
            self._meta_return_shortcut = QShortcut(QKeySequence("Meta+Return"), self)
            self._meta_return_shortcut.activated.connect(self._on_save)
        # StandardKey.Save: Mac=Cmd+S / Linux・Win=Ctrl+S
        self._ctrl_s_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self._ctrl_s_shortcut.activated.connect(self._on_save)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)

        self.text_area.setFocus()

    def _set_busy(self) -> None:
        self.save_btn.setEnabled(False)
        self.img_btn.setEnabled(False)
        self._save_shortcut.setEnabled(False)
        if self._meta_return_shortcut:
            self._meta_return_shortcut.setEnabled(False)
        self._ctrl_s_shortcut.setEnabled(False)

    def _set_idle(self) -> None:
        self.save_btn.setEnabled(True)
        self.img_btn.setEnabled(True)
        self._save_shortcut.setEnabled(True)
        if self._meta_return_shortcut:
            self._meta_return_shortcut.setEnabled(True)
        self._ctrl_s_shortcut.setEnabled(True)

    def _insert_tag(self, tag: str) -> None:
        content = self.text_area.toPlainText()
        if f"#{tag}" in content:
            return
        has_tag = any(f"#{t}" in content for t in self._tags)
        prefix = " " if has_tag else "\n\n"
        cursor = self.text_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(f"{prefix}#{tag}")
        self.text_area.setFocus()

    def _handle_image_drop(self, path: Path) -> None:
        _handle_image_path(self.text_area, self.status_label, path)

    def _pick_images(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select images", "", f"Images ({exts});;All files (*.*)"
        )
        for p in paths:
            _handle_image_path(self.text_area, self.status_label, Path(p))

    def _on_save(self) -> None:
        content = self.text_area.toPlainText().strip()
        if not content:
            _set_status(self.status_label, "Please enter some text.", "#e74c3c")
            return

        urls_with_idx = _find_urls_without_metadata(content)
        if urls_with_idx:
            _set_status(self.status_label, "Fetching metadata...", "#aaaaaa")
            self._set_busy()
            self._worker = MetadataWorker(urls_with_idx)
            self._worker.metadata_ready.connect(self._on_metadata_done)
            # QThread.finished は run() の正常・異常終了どちらでも emit される
            self._worker.finished.connect(self._set_idle)
            self._worker.start()
        else:
            _do_save(self.text_area, self.status_label)

    def _on_metadata_done(self, results: list[tuple[str, int, dict[str, str]]]) -> None:
        try:
            _apply_and_save(self.text_area, self.status_label, results)
        finally:
            self._worker = None


def main() -> None:
    _log_level = os.environ.get("FRAGMENTBOX_LOG", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, _log_level, logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = QApplication(sys.argv)
    window = FragmentBoxWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
