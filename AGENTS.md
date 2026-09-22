# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

fragmentbox — テキスト、画像、URLの断片をMarkdownでローカルに保存し、閲覧・整理するパーソナルツール。

## 変更方針と現行実装

- 合意済みの変更方針は [SPEC.md 第11章](SPEC.md#11-フォルダ分類と手動アーカイブへの変更方針一部実装済み) を参照する。
- 実ディレクトリを分類の正本とする。ビューアのフォルダ一覧・作成・並び替えは実装済み（SPEC.md第12章）。ビューア下部の投稿欄から選択フォルダへ投稿できる（SPEC.md第13章）。記事単位のアーカイブ・復帰は実装済み（SPEC.md第21章）。通常記事の検索付きフォルダ移動は第22章で実装済み。移動アイコンはArchiveの記事に表示せず、移動先にもArchiveを含めない。
- アーカイブは所属フォルダと原文を保った移動とする。定期的なAI要約・再編集は運用の前提にしない。
- `paths.active` 配下の1階層を通常フォルダとし、Inboxも通常フォルダと同列に並べ、統合表示順を `.navigation-order.json` に保存する。Archiveだけ別枠。画面にactiveという親項目は出さない。GUIは引き続きInboxへ投稿する。
- Trashの方針はSPEC.md第19章を参照する。復元UIは作らず、元の場所・参照画像を記録して手動復元の余地を残す（未実装）。
- 未決事項はSPEC.mdに記載する。文書更新を理由に、設定や既存データを自動で移行しない。

## Code Style

`.editorconfig` に従う。Python / CSS は 4 スペース、それ以外は 2 スペース、UTF-8、LF。`*.md` / `*.txt` は末尾スペース維持。

## Python 実行環境

- Python は常に `uv run python` を使う（`python` / `.venv/bin/python` 直接呼び出し禁止）
- パッケージ操作は `uv add` / `uv remove` を使う（`pip` 直接禁止）

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

**viewer.py** — FastAPI ビューア・投稿API（デフォルト :8765）
- 投稿と画像添付は `fragmentbox.py` の画像変換・URL情報取得処理を再利用する。保存中は投稿先を固定する。
- Web投稿は `YYYYMMDD_HHMMSS_ffffff.md` を排他的に作成する。
- 返り値は Pydantic `BaseModel`（`dict` 禁止）
- `source` パラメータは `Source = Literal["notes", "inbox", "archive"]`
- `Fragment.created_at` は `datetime` 型
- 削除時は `IMAGE_PATTERN` で抽出した `../assets/` 参照画像も Trash へ移動

**viewer.html** — Vanilla JS SPA。タグ（AND/OR）・テキスト・日付・お気に入りでクライアントサイドフィルタリング。ANDモードでは、現在の全フィルター条件にタグを追加して0件になる未選択タグを無効化する。記事フッターにお気に入り・編集・移動・アーカイブ・削除ボタン。Archive内では移動・アーカイブ・削除を表示せず、復帰ボタンを表示する。

## Fragment ファイル形式

タグは `#tagname` インライン記法。本文末尾に `\n\n` を挟んで追加。

## Important Constraints

- **Git 追跡**: 未追跡ファイル（ignore 対象を含む）は、ユーザーから明示的な指示がない限り追跡対象に追加しない。
- **スレッド安全**: `MetadataWorker.run()` から Qt UI を操作しない。`QTimer.singleShot` をワーカースレッドから呼ばない。
- **DnD**: `dragEnterEvent` / `dropEvent` は `IMAGE_EXTENSIONS` のファイルのみ accept。全 URL を受けて後段で弾かない。
- **行末**: 画像・メタデータ挿入の行末は `  \n`（スペース2つ＋改行）。`\n` のみ不可。
- **Qt macOS**: `Ctrl` = ⌘、`Meta` = ⌃。`Meta+Return` は `sys.platform == "darwin"` のみ登録。
- **設定**: タグ一覧・パス・ポートは `config.toml` から読む。コードに直書きしない。
- **JS タグ正規表現**: `\w` は日本語等に非対応。`/#([\p{L}\p{N}_]+)/gu` を使う（`u` フラグ必須）。
- **ビューアのタグ候補**: ANDモードの選択済みタグは解除できるよう有効のままにする。候補が0件の未選択タグは非表示にせず、選択不可かつ破線枠・取り消し線で区別する。ORモードでは全タグを選択可能にする。
