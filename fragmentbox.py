import re
import threading
import tkinter as tk
import tomllib
from datetime import datetime
from pathlib import Path


CONFIG_FILE = Path(__file__).parent / "config.toml"

with CONFIG_FILE.open("rb") as _f:
    _config = tomllib.load(_f)

INBOX_DIR = Path(_config["paths"]["inbox"]).expanduser()

URL_PATTERN = re.compile(r'https?://\S+')
YOUTUBE_PATTERN = re.compile(r'https?://(www\.)?(youtube\.com|youtu\.be)/\S+')


def load_tags() -> list[str]:
    return _config.get("tags", {}).get("presets", [])


def save_fragment(text: str) -> Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = INBOX_DIR / f"{timestamp}.md"
    filepath.write_text(text, encoding="utf-8")
    return filepath


def insert_tag(text_widget: tk.Text, tag: str) -> None:
    content = text_widget.get("1.0", tk.END)
    if f"#{tag}" in content:
        return
    has_tag = any(f"#{t}" in content for t in load_tags())
    prefix = " " if has_tag else "\n\n"
    text_widget.insert(tk.END, f"{prefix}#{tag}")
    text_widget.focus_set()


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
    }


def _fetch_general(url: str) -> dict[str, str]:
    import trafilatura
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return {}
    meta = trafilatura.extract_metadata(downloaded)
    if not meta:
        return {}
    return {
        "title": meta.title or "",
        "sitename": meta.sitename or "",
        "description": meta.description or "",
    }


def _fetch_metadata(url: str) -> dict[str, str]:
    if YOUTUBE_PATTERN.match(url):
        return _fetch_youtube(url)
    return _fetch_general(url)


def _find_urls_without_metadata(content: str) -> list[str]:
    """本文中のURLのうち、直後に title: がないものを返す。"""
    urls = []
    for m in URL_PATTERN.finditer(content):
        after = content[m.end():]
        if not after.lstrip("\n ").startswith("title:"):
            urls.append(m.group(0))
    return urls


def _insert_metadata(text_widget: tk.Text, url: str, meta: dict[str, str]) -> None:
    lines = []
    if meta.get("title"):
        lines.append(f"title: {meta['title']}")
    if meta.get("sitename"):
        lines.append(f"sitename: {meta['sitename']}")
    if meta.get("description"):
        lines.append(f"description: {meta['description']}")
    if not lines:
        return

    content = text_widget.get("1.0", tk.END)
    url_start = content.find(url)
    if url_start == -1:
        return

    # URL直前の処理: 改行あり→行末にスペース2つ、改行なし→「スペース2つ+改行」を挿入
    if url_start > 0:
        if content[url_start - 1] == "\n":
            text_widget.insert(f"1.0 + {url_start - 1} chars", "  ")
        else:
            text_widget.insert(f"1.0 + {url_start} chars", "  \n")
        content = text_widget.get("1.0", tk.END)
        url_start = content.find(url)

    line_end = content.find("\n", url_start + len(url))
    insertion = "".join(f"  \n{line}" for line in lines) + "  \n"

    if line_end == -1:
        text_widget.insert(tk.END, insertion)
    else:
        text_widget.insert(f"1.0 + {line_end} chars", insertion)


def _fetch_all_and_save(
    text_widget: tk.Text, status_label: tk.Label, urls: list[str]
) -> None:
    """バックグラウンドスレッドで全URLのメタデータを取得し、保存する。"""
    results: list[tuple[str, dict[str, str]]] = []
    for url in urls:
        try:
            meta = _fetch_metadata(url)
        except Exception:
            meta = {}
        results.append((url, meta))
    text_widget.after(0, lambda: _apply_and_save(text_widget, status_label, results))


def _apply_and_save(
    text_widget: tk.Text,
    status_label: tk.Label,
    results: list[tuple[str, dict[str, str]]],
) -> None:
    """メタデータを挿入してから保存する（メインスレッドで実行）。"""
    for url, meta in results:
        _insert_metadata(text_widget, url, meta)
    _do_save(text_widget, status_label)


def _do_save(text_widget: tk.Text, status_label: tk.Label) -> None:
    content = text_widget.get("1.0", tk.END).strip()
    filepath = save_fragment(content)
    status_label.config(text=f"Saved: {filepath.name}", fg="#27ae60")
    text_widget.delete("1.0", tk.END)


def on_save(text_widget: tk.Text, status_label: tk.Label) -> None:
    content = text_widget.get("1.0", tk.END).strip()
    if not content:
        status_label.config(text="Please enter some text.", fg="#e74c3c")
        return

    urls = _find_urls_without_metadata(content)
    if urls:
        status_label.config(text="Fetching metadata...", fg="#aaaaaa")
        threading.Thread(
            target=_fetch_all_and_save,
            args=(text_widget, status_label, urls),
            daemon=True,
        ).start()
    else:
        _do_save(text_widget, status_label)


# --- UI 構築 ---

def build_ui(root: tk.Tk) -> None:
    root.title("fragmentbox")
    root.resizable(False, False)
    root.configure(bg="#2b2b2b")

    main_frame = tk.Frame(root, bg="#2b2b2b", padx=10, pady=10)
    main_frame.pack(fill=tk.BOTH, expand=True)

    text_area = tk.Text(
        main_frame,
        width=40,
        height=8,
        font=("Helvetica Neue", 13),
        bg="#3c3f41",
        fg="#f0f0f0",
        insertbackground="#f0f0f0",
        relief=tk.FLAT,
        padx=8,
        pady=8,
        wrap=tk.WORD,
        highlightbackground="#4a4a4a",
        highlightcolor="#4a4a4a",
        highlightthickness=1,
    )
    text_area.grid(row=0, column=0, sticky="nsew")
    text_area.focus_set()

    tag_frame = tk.Frame(main_frame, bg="#2b2b2b")
    tag_frame.grid(row=0, column=1, sticky="ns", padx=(8, 0))

    for tag in load_tags():
        btn = tk.Label(
            tag_frame,
            text=f"#{tag}",
            font=("Helvetica Neue", 11),
            bg="#4a4a4a",
            fg="#999999",
            padx=6,
            pady=4,
            cursor="hand2",
        )
        btn.pack(fill=tk.X, pady=2)
        btn.bind("<Button-1>", lambda e, t=tag: insert_tag(text_area, t))
        btn.bind("<Enter>", lambda e, w=btn: w.config(bg="#5a5a5a"))
        btn.bind("<Leave>", lambda e, w=btn: w.config(bg="#4a4a4a"))

    bottom_frame = tk.Frame(root, bg="#2b2b2b")
    bottom_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

    status_label = tk.Label(
        bottom_frame,
        text="",
        font=("Helvetica Neue", 11),
        bg="#2b2b2b",
        fg="#aaaaaa",
        anchor="w",
    )
    status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    save_btn = tk.Label(
        bottom_frame,
        text="Save",
        font=("Helvetica Neue", 12, "bold"),
        bg="#4a4a4a",
        fg="#999999",
        padx=16,
        pady=6,
        cursor="hand2",
    )
    save_btn.pack(side=tk.RIGHT)
    save_btn.bind("<Button-1>", lambda e: on_save(text_area, status_label))
    save_btn.bind("<Enter>", lambda e: save_btn.config(bg="#5a5a5a"))
    save_btn.bind("<Leave>", lambda e: save_btn.config(bg="#4a4a4a"))

    root.bind("<Command-Return>", lambda e: on_save(text_area, status_label))
    root.bind("<Command-s>", lambda e: on_save(text_area, status_label))
    root.bind("<Escape>", lambda e: root.destroy())


def main() -> None:
    root = tk.Tk()
    build_ui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
