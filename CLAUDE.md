# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

fragmentbox — テキストフラグメント（アイデアの断片）をローカルのインボックスに素早く投入するための小さなパーソナルツール。

## Code Style

`.editorconfig` に従う。Python / CSS は 4 スペース、それ以外は 2 スペース、UTF-8、LF。`*.md` / `*.txt` は末尾スペース維持。

## Running the Apps

```bash
./run_fragmentbox.sh
FRAGMENTBOX_LOG=DEBUG ./run_fragmentbox.sh

./run_viewe.sh   # typo に注意
```

`DYLD_LIBRARY_PATH` は `run_fragmentbox.sh` がセットする。コード内で `os.environ["DYLD_LIBRARY_PATH"]` を操作しない。

## Architecture

2つの独立したエントリポイント。どちらも起動時に `config.toml` を読み込む。

**fragmentbox.py** — PySide6 投稿 GUI
- `FragmentBoxWindow`: メインウィンドウ
- `DropTextEdit`: 画像 DnD 対応の `QTextEdit` サブクラス
- `MetadataWorker`: URL メタデータをバックグラウンド取得する `QThread` サブクラス。`metadata_ready` Signal で結果を返す

保存フロー: URL 検出 → `MetadataWorker` で取得 → `title:` / `sitename:` / `description:` / `![]()` を URL 直下に挿入 → `YYYYMMDD_HHMMSS.md` で保存

画像: ラスター → pyvips で WebP 変換。SVG / GIF → そのままコピー（`_COPY_ONLY_EXTENSIONS`、pyvips の制限ではなくアプリの方針）。pyvips は `import_image()` 内で遅延 import。

`_download_thumbnail`: `tempfile.mkstemp()` + `os.fdopen()` で書き込む。`Content-Type: image/*` 以外・10 MB 超はスキップ。`trafilatura` の `meta.image` は `urljoin(url, image_url)` で絶対 URL に解決する。

**viewer.py** — FastAPI ビューア（デフォルト :8765）
- 返り値は Pydantic `BaseModel`（`dict` 禁止）
- `source` パラメータは `Source = Literal["inbox", "archive"]`
- `Fragment.created_at` は `datetime` 型
- 削除時は `IMAGE_PATTERN` で抽出した `../assets/` 参照画像も Trash へ移動

**viewer.html** — Vanilla JS SPA。タグ（AND/OR）・テキスト・日付・お気に入りでクライアントサイドフィルタリング。

## Fragment ファイル形式

タグは `#tagname` インライン記法。本文末尾に `\n\n` を挟んで追加。

## Important Constraints

- **スレッド安全**: `MetadataWorker.run()` から Qt UI を操作しない。`QTimer.singleShot` をワーカースレッドから呼ばない。
- **DnD**: `dragEnterEvent` / `dropEvent` は `IMAGE_EXTENSIONS` のファイルのみ accept。全 URL を受けて後段で弾かない。
- **行末**: 画像・メタデータ挿入の行末は `  \n`（スペース2つ＋改行）。`\n` のみ不可。
- **Qt macOS**: `Ctrl` = ⌘、`Meta` = ⌃。`Meta+Return` は `sys.platform == "darwin"` のみ登録。
- **設定**: タグ一覧・パス・ポートは `config.toml` から読む。コードに直書きしない。
