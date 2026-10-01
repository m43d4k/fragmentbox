import logging
import html
import os
import re
import shutil
import sys
import tomllib
import uuid
from datetime import datetime
from pathlib import Path

from markdown_it import MarkdownIt

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
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
ATTACHMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".json", ".mp3", ".wav",
                         ".aiff", ".aif", ".flac", ".m4a", ".ogg", ".mid", ".midi"}
ATTACHMENT_MAX_BYTES = 100 * 1024 * 1024


def attachment_markdown(name: str, reference: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("ファイル名に制御文字は使えません")
    label = html.escape(name, quote=False).replace("[", "&#91;").replace("]", "&#93;")
    return f"[{label}]({reference})  \n"


def import_attachment(src: Path) -> Path:
    if src.suffix.lower() not in ATTACHMENT_EXTENSIONS or src.is_symlink() or not src.is_file():
        raise ValueError("対応していないファイルです")
    if not 0 < src.stat().st_size <= ATTACHMENT_MAX_BYTES:
        raise ValueError("添付ファイルは空でない100 MiB以下のファイルにしてください")
    attachment_markdown(src.name, "")  # コピー前にファイル名を検証する。
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    dest = ASSETS_DIR / f"attachment_{uuid.uuid4().hex}{src.suffix.lower()}"
    try:
        with src.open("rb") as source, dest.open("xb") as target:
            shutil.copyfileobj(source, target)
        if dest.stat().st_size > ATTACHMENT_MAX_BYTES:
            raise ValueError("添付ファイルは100 MiB以下にしてください")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return dest

URL_PATTERN     = re.compile(r'https?://\S+')
YOUTUBE_PATTERN = re.compile(r'https?://(www\.)?(youtube\.com|youtu\.be)/\S+')
TAG_PATTERN     = re.compile(r'#(\w+)')
TAG_AT_END_PATTERN = re.compile(r'#\w+([ \t]*)$')


TAG_LINE_PATTERN = re.compile(r"[ \t]*#\w+(?:[ \t]+#\w+)*[ \t]*")
_TAG_MARKDOWN = MarkdownIt("commonmark")


def _collect_tag_line(state, silent: bool) -> bool:
    # Observe only text reached by the Markdown parser, outside code and links.
    if not silent and not state.linkLevel and state.env.get("tag_source") == state.src:
        start = state.src.rfind("\n", 0, state.pos) + 1
        end = state.src.find("\n", state.pos)
        if end < 0:
            end = len(state.src)
        if (not state.src[start:state.pos].strip()
                and TAG_LINE_PATTERN.fullmatch(state.src[start:end])):
            state.env["tag_lines"].add(state.src.count("\n", 0, start))
    return False


_TAG_MARKDOWN.inline.ruler.before("text", "collect_tag_line", _collect_tag_line)


def tag_line_numbers(content: str) -> list[int]:
    """Top-level paragraph lines containing tags only (zero-based)."""
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    frontmatter_end = 0
    if lines and lines[0].lstrip("\ufeff") in ("---", "+++"):
        delimiter = lines[0].lstrip("\ufeff")
        frontmatter_end = next((i + 1 for i in range(1, len(lines))
                                if lines[i] == delimiter), len(lines))
    # Mask metadata without changing line numbers or Markdown block boundaries.
    masked = "\n".join([""] * frontmatter_end + lines[frontmatter_end:])
    env = {}
    tokens = _TAG_MARKDOWN.parse(masked, env)
    result = []
    for index, token in enumerate(tokens):
        if token.type != "paragraph_open" or token.level != 0:
            continue
        inline = tokens[index + 1]
        local = dict(env, tag_source=inline.content, tag_lines=set())
        _TAG_MARKDOWN.inline.parse(inline.content, _TAG_MARKDOWN, local, [])
        for offset in sorted(local["tag_lines"]):
            number = inline.map[0] + offset
            if TAG_LINE_PATTERN.fullmatch(lines[number]):
                result.append(number)
    return result


def extract_tags(content: str) -> list[str]:
    lines = content.splitlines()
    return list(dict.fromkeys(tag for number in tag_line_numbers(content)
                              for tag in TAG_PATTERN.findall(lines[number])))


def load_tags() -> list[str]:
    return _config.get("tags", {}).get("presets", [])


def _has_tag(content: str, tag: str) -> bool:
    return tag in extract_tags(content)


def _tag_separator(content: str) -> str:
    match = TAG_AT_END_PATTERN.search(content)
    if match is None or len(content.split("\n")) - 1 not in tag_line_numbers(content):
        return "\n\n"
    return "" if match.group(1) else " "


def save_fragment(text: str) -> Path:
    if not text.strip():
        raise ValueError("Cannot save empty fragment")
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = INBOX_DIR / f"{timestamp}.md"
    filepath.write_text(text, encoding="utf-8")
    return filepath



def _image_reference(path: Path) -> str:
    return Path(os.path.relpath(path, INBOX_DIR)).as_posix()


def import_image(src: Path, assets_dir: Path | None = None) -> Path:
    """画像をアセットフォルダへ保存する。
    ラスター画像は pyvips で WebP に圧縮、SVG/GIF はそのままコピー。
    """
    assets_dir = ASSETS_DIR if assets_dir is None else assets_dir
    assets_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique = uuid.uuid4().hex[:8]
    suffix = src.suffix.lower()

    if suffix in _COPY_ONLY_EXTENSIONS:
        new_name = f"{timestamp}_{unique}{suffix}"
        dest = assets_dir / new_name
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
    dest = assets_dir / new_name
    image = pyvips.Image.new_from_file(str(src)).autorot()
    image.webpsave(str(dest), Q=IMAGE_QUALITY)
    return dest


# --- メタデータ取得 ---

def _fetch_youtube(url: str) -> dict[str, str | list[str]]:
    import json
    import urllib.request
    from urllib.parse import urlencode

    endpoint = "https://www.youtube.com/oembed?" + urlencode({"url": url, "format": "json"})
    request = urllib.request.Request(
        endpoint, headers={"User-Agent": "Mozilla/5.0 (compatible; fragmentbox)"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read(_THUMBNAIL_MAX_BYTES + 1)
    if len(data) > _THUMBNAIL_MAX_BYTES:
        raise ValueError("YouTube metadata exceeded 10 MB")
    info = json.loads(data)
    title = info.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("YouTubeの動画タイトルを取得できませんでした")
    return {
        "title": " ".join(title.split()),
        "sitename": "YouTube",
        "description": info.get("author_name") or "",
        "image_url": info.get("thumbnail_url") or "",
    }


def _link_title(document, fallback: str = "") -> str:
    """リンク用メタ情報とページタイトルを本文の見出しより優先する。"""
    for key in ("og:title", "twitter:title"):
        for element in document.iter("meta"):
            if (element.get("property", "").lower() == key
                    or element.get("name", "").lower() == key):
                title = " ".join(element.get("content", "").split())
                if title:
                    return title
    for element in document.xpath("//head/title"):
        title = " ".join(element.text_content().split())
        if title:
            return title
    return fallback


def _link_images(document, fallback: str = "") -> list[str]:
    """OG画像を指定順に取得し、なければTwitter画像を使う。"""
    for keys in (("og:image", "og:image:url"), ("twitter:image", "twitter:image:src")):
        images = []
        for element in document.iter("meta"):
            if (element.get("property", "").lower() in keys
                    or element.get("name", "").lower() in keys):
                image = element.get("content", "").strip()
                if image and image not in images:
                    images.append(image)
        if images:
            return images
    return [fallback] if fallback else []


def _link_image(document, fallback: str = "") -> str:
    images = _link_images(document, fallback)
    return images[0] if images else ""


def _metadata_image_urls(meta) -> list[str]:
    return meta.get("image_urls") or ([meta["image_url"]] if meta.get("image_url") else [])


def _fetch_general(url: str) -> dict[str, str | list[str]]:
    import trafilatura
    import urllib.request
    from trafilatura.utils import load_html
    from urllib.parse import urljoin
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; fragmentbox)"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        downloaded = response.read(_THUMBNAIL_MAX_BYTES + 1)
    if len(downloaded) > _THUMBNAIL_MAX_BYTES:
        raise ValueError("Metadata page exceeded 10 MB")
    if not downloaded:
        return {}
    document = load_html(downloaded)
    if document is None:
        return {}
    title = _link_title(document)
    meta = trafilatura.extract_metadata(downloaded)
    if not meta:
        return {"title": title} if title else {}
    image_urls = list(dict.fromkeys(urljoin(url, image) for image in _link_images(document, meta.image or "")))
    return {
        "title": title or meta.title or "",
        "sitename": meta.sitename or "",
        "description": meta.description or "",
        "image_url": image_urls[0] if image_urls else "",
        "image_urls": image_urls,
    }


_THUMBNAIL_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _download_thumbnail(image_url: str, assets_dir: Path | None = None) -> Path | None:
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
            generic_binary = content_type.split(";", 1)[0].strip().lower() == "application/octet-stream"
            if not content_type.startswith("image/") and not generic_binary:
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
        if generic_binary:
            if data[:6] not in (b"GIF87a", b"GIF89a"):
                logger.warning("Thumbnail skipped: binary response is not a GIF: %s", image_url)
                return None
            if tmp_path.suffix != ".gif":
                logger.warning("Thumbnail skipped: GIF response has a non-GIF URL: %s", image_url)
                return None
        import os
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        fd = -1
        return import_image(tmp_path, assets_dir)
    except Exception:
        logger.exception("Failed to download thumbnail: %s", image_url)
        return None
    finally:
        if fd != -1:
            import os
            os.close(fd)
        tmp_path.unlink(missing_ok=True)


def _fetch_reddit(url: str) -> dict[str, str | list[str]]:
    import json
    import urllib.request
    from urllib.parse import urlencode, urlsplit, urlunsplit

    parsed = urlsplit(url)
    canonical = urlunsplit(("https", "www.reddit.com", parsed.path, "", ""))
    endpoint = "https://www.reddit.com/oembed?" + urlencode({"url": canonical})
    request = urllib.request.Request(
        endpoint, headers={"User-Agent": "Mozilla/5.0 (compatible; fragmentbox)"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read(_THUMBNAIL_MAX_BYTES + 1)
    if len(data) > _THUMBNAIL_MAX_BYTES:
        raise ValueError("Reddit metadata exceeded 10 MB")
    meta = json.loads(data)
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip() or title.strip().lower() == "reddit":
        raise ValueError("Redditの投稿タイトルを取得できませんでした")
    title = " ".join(title.split())
    subreddit = re.match(r"^/r/([^/]+)/comments/", parsed.path, re.IGNORECASE)
    if subreddit:
        title = f"r/{subreddit.group(1)} - {title}"
    image = meta.get("thumbnail_url")
    return {
        "title": title,
        "sitename": "Reddit",
        "description": "",
        "image_url": image if isinstance(image, str) else "",
    }


def _fetch_metadata(url: str) -> dict[str, str | list[str]]:
    from urllib.parse import urlsplit
    if YOUTUBE_PATTERN.match(url):
        return _fetch_youtube(url)
    parsed = urlsplit(url)
    if (parsed.hostname in {"reddit.com", "www.reddit.com", "old.reddit.com", "new.reddit.com"}
            and re.match(r"^/(?:r/[^/]+/)?comments/[a-z0-9]+(?:/|$)", parsed.path, re.IGNORECASE)):
        return _fetch_reddit(url)
    return _fetch_general(url)


def _find_urls_without_metadata(content: str) -> list[tuple[str, int]]:
    """本文中のURLのうち、直後の連続行に title: がないものを (url, occurrence_index) で返す。

    occurrence_index は同一URLの何番目の出現かを示す（0始まり）。
    """
    url_counts: dict[str, int] = {}
    results: list[tuple[str, int]] = []
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if re.fullmatch(r"\[[^\]]*\]\([^)]*attachment_[a-f0-9]{32}\.[a-z0-9]+\)\s*", line):
            continue
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
    text_widget: "DropTextEdit", url: str, occurrence: int, meta: dict[str, str | list[str]]
) -> None:
    lines = []
    if meta.get("title"):
        lines.append(f"title: {meta['title']}")
    if meta.get("sitename"):
        lines.append(f"sitename: {meta['sitename']}")
    if meta.get("description"):
        lines.append(f"description: {meta['description']}")
    for thumbnail in meta.get("thumbnails", []) or ([meta["thumbnail"]] if meta.get("thumbnail") else []):
        lines.append(f"![]({_image_reference(ASSETS_DIR / thumbnail)})")
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
    content = text_widget.toPlainText().rstrip()
    filepath = save_fragment(content)
    _set_status(status_label, f"Saved: {filepath.name}", "#27ae60")
    text_widget.clear()


def _apply_and_save(
    text_widget: "DropTextEdit",
    status_label: QLabel,
    results: list[tuple[str, int, dict[str, str | list[str]]]],
) -> None:
    for url, occurrence, meta in results:
        _insert_metadata(text_widget, url, occurrence, meta)
    _do_save(text_widget, status_label)


class MetadataWorker(QThread):
    """バックグラウンドで URL メタデータを取得し、Signal で結果を返す。"""

    metadata_ready = Signal(list)  # list[tuple[str, int, dict[str, str | list[str]]]]

    def __init__(self, urls_with_idx: list[tuple[str, int]], parent=None):
        super().__init__(parent)
        self._urls_with_idx = urls_with_idx

    def run(self):
        results: list[tuple[str, int, dict[str, str | list[str]]]] = []
        for url, idx in self._urls_with_idx:
            try:
                meta = _fetch_metadata(url)
            except Exception:
                logger.exception("Failed to fetch metadata for %s", url)
                meta = {}

            thumbnails = []
            for image_url in _metadata_image_urls(meta):
                thumb = _download_thumbnail(image_url)
                if thumb:
                    thumbnails.append(thumb.name)
            meta.pop("image_url", None)
            meta.pop("image_urls", None)
            meta["thumbnails"] = thumbnails

            results.append((url, idx, meta))
        self.metadata_ready.emit(results)


def _handle_image_path(
    text_widget: "DropTextEdit", status_label: QLabel, path: Path
) -> None:
    if path.suffix.lower() not in IMAGE_EXTENSIONS | ATTACHMENT_EXTENSIONS:
        return
    try:
        is_image = path.suffix.lower() in IMAGE_EXTENSIONS
        dest = import_image(path) if is_image else import_attachment(path)
        cursor = text_widget.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if not is_image and text_widget.toPlainText() and not text_widget.toPlainText().endswith("\n"):
            cursor.insertText("  \n")
        cursor.insertText(f"![]({_image_reference(dest)})  \n" if is_image
                          else attachment_markdown(path.name, _image_reference(dest)))
        _set_status(status_label, f"添付: {path.name}", "#27ae60")
    except Exception as e:
        _set_status(status_label, f"Error: {e}", "#e74c3c")


# --- UI ---

class DropTextEdit(QTextEdit):
    """対応する画像・添付ファイルのドロップを受け付ける QTextEdit。"""

    image_dropped = Signal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setAcceptDrops(True)

    def _image_urls(self, mime_data) -> list[Path]:
        return [
            Path(url.toLocalFile())
            for url in mime_data.urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS | ATTACHMENT_EXTENSIONS
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
        self.setStyleSheet("QWidget { background-color: #2b2b2b; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # テキストエリア + タグ列
        row = QHBoxLayout()
        row.setSpacing(0)

        self.text_area = DropTextEdit()
        self.text_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
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
        tag_buttons = []
        for tag in self._tags:
            btn = QPushButton(f"#{tag}")
            btn.setStyleSheet(_BTN_SS.format(pad="4px 6px", size=11, extra=""))
            btn.clicked.connect(lambda checked, t=tag: self._insert_tag(t))
            tag_col.addWidget(btn)
            tag_buttons.append(btn)
        tag_col.addStretch()
        row.addLayout(tag_col)
        outer.addLayout(row, 1)

        # ボトムバー
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        bottom.addWidget(self.status_label, 1)

        self.img_btn = QPushButton("添付")
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

        # 起動時は入力欄をタグボタン列の自然な高さに合わせる。
        # 以降は固定せず、ウインドウとともに縦横へ伸縮させる。
        if tag_buttons:
            text_height = sum(btn.sizeHint().height() for btn in tag_buttons)
            text_height += tag_col.spacing() * (len(tag_buttons) - 1)
        else:
            text_height = 160
        margins = outer.contentsMargins()
        initial_height = (
            margins.top()
            + text_height
            + outer.spacing()
            + bottom.sizeHint().height()
            + margins.bottom()
        )
        self.resize(520, initial_height)

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
        if _has_tag(content, tag):
            return
        prefix = _tag_separator(content)
        cursor = self.text_area.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(f"{prefix}#{tag}")
        self.text_area.setFocus()

    def _handle_image_drop(self, path: Path) -> None:
        _handle_image_path(self.text_area, self.status_label, path)

    def _pick_images(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS | ATTACHMENT_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "添付ファイルを選択", "", f"対応ファイル ({exts})"
        )
        for p in paths:
            _handle_image_path(self.text_area, self.status_label, Path(p))

    def _on_save(self) -> None:
        content = self.text_area.toPlainText().rstrip()
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

    def _on_metadata_done(self, results: list[tuple[str, int, dict[str, str | list[str]]]]) -> None:
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
