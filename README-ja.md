　# fragmentbox

思いついたことをすぐにメモしてローカルに保存できる、シンプルなパーソナルメモツール。

[English README](README.md)

## 概要

fragmentbox は2つのコンポーネントで構成されています。

- **fragmentbox.py** — メモをすばやく書いて保存する Mac 用 GUI（tkinter）
- **viewer.py** — 保存されたメモをブラウザで一覧・検索する Web ビューア（FastAPI）

## 必要環境

- Python 3.13+
- macOS（GUI は tkinter を使用）

## セットアップ

```bash
# 仮想環境の作成と有効化
python -m venv .venv
source .venv/bin/activate

# 依存関係のインストール
pip install -r requirements.txt
```

## 使い方

### メモを書く

![post](docs/screenshot_post.png)

```bash
python fragmentbox.py
```

- テキストエリアにメモを入力し、`Cmd+S` または `Cmd+Return` で保存
- 保存先は `config.toml` で設定できます（1 保存 = 1 Markdown ファイル、ファイル名は日時）
- 右側のタグボタンを押すと本文末尾にタグを挿入（タグは `tags.yaml` で管理）
- テキスト内の URL は保存時にメタデータ（タイトル・サイト名・説明）を自動取得して挿入
  - 一般 URL: trafilatura を使用
  - YouTube URL: yt-dlp を使用

### メモを閲覧する

![viewer](docs/screenshot_viewer.png)

```bash
python viewer.py
```

サーバーが起動し、ブラウザが自動的に開きます（ポート: `8765`）。

**ビューア機能:**

- Inbox / Archive タブ切り替え
- テキスト検索（リアルタイム）
- タグ絞り込み（複数選択・AND/OR 切り替え）
- 日付範囲フィルタ
- メモの削除（Inbox のみ。`config.toml` で設定した Trash フォルダへ移動）

終了するにはターミナルで `Ctrl+C` を押します。

## ファイル構成

```
fragmentbox/
├── fragmentbox.py   # GUI クライアント
├── viewer.py        # FastAPI サーバー
├── viewer.html      # ビューア フロントエンド
├── css/
│   └── viewer.css   # スタイルシート
├── tags.yaml        # タグ一覧（fragmentbox.py が起動時に読み込む）
├── config.toml      # パス・ポート設定
└── requirements.txt
```

## 設定

`config.toml` でパスとポートを変更できます。

```toml
[paths]
inbox   = "~/idea_pool/fragmentbox/inbox"
archive = "~/idea_pool/fragmentbox/archive"
trash   = "~/idea_pool/fragmentbox/Trash"

[viewer]
port = 8765

[tags]
presets = ["idea", "todo", "ref", "question", "memo", "later"]
```

## データの保存場所

inbox / archive / trash のパスはすべて `config.toml` の `[paths]` セクションで設定します。

## License

MIT
