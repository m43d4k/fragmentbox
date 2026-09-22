# fragmentbox

思いついたことをすぐにメモしてローカルに保存できる、シンプルなパーソナルメモツール。

[English README](README.md)

## 概要

fragmentbox は2つのコンポーネントで構成されています。

- **fragmentbox.py** — メモをすばやく書いて保存する GUI（PySide6）
- **viewer.py** — 保存されたメモをブラウザで一覧・検索する Web ビューア（FastAPI）

## ドキュメントと変更方針

ビューアは実ディレクトリによるフォルダ表示・作成・並び替えに対応する。投稿GUIは引き続きInboxへ保存する。ビューア下部の投稿欄は選択フォルダへ保存する。記事右下のアーカイブボタンで所属フォルダを保って退避できる。アーカイブ内の記事は「元のフォルダに戻す」ボタンで復帰できる。通常記事の移動アイコンからフォルダを検索して移動できる。

終わった情報は、原文と所属フォルダを保って手動でアーカイブし、通常表示から外す方針とする。定期的なAI要約・再編集は運用の前提にしない。

- [SPEC.md](SPEC.md): 第2〜10章に従来の仕様、第11章に変更方針、第12〜13章にフォルダ・投稿機能と現行仕様との差分を記載する。
- [spec_post.md](spec_post.md) / [spec_viewer.md](spec_viewer.md): 従来の運用に関する旧要件メモ。

## 対応プラットフォーム

- macOS
- Linux

## 必要環境

- Python 3.12+

## セットアップ

```bash
# 仮想環境の作成と有効化
python -m venv .venv
source .venv/bin/activate

# 依存関係のインストール
pip install -e .
```

## 使い方

### メモを書く

![post](docs/screenshot_post.png)

起動スクリプト `run_fragmentbox.sh` を作成して実行します（後述の「起動スクリプトの作成」を参照）。

```bash
./run_fragmentbox.sh
# デバッグログを出したいとき
FRAGMENTBOX_LOG=DEBUG ./run_fragmentbox.sh
```

- テキストエリアにメモを入力し、保存ショートカットで保存
  - macOS: `Cmd+S` / `Cmd+Return` / `Ctrl+Return`
  - Linux: `Ctrl+S` / `Ctrl+Return`
- 保存先は `config.toml` で設定できます（1 保存 = 1 Markdown ファイル、ファイル名は日時）
- 右側のタグボタンを押すと本文末尾にタグを挿入（タグは `config.toml` の `[tags]` セクションで管理）
- テキスト内の URL は保存時にメタデータ（タイトル・サイト名・説明・サムネイル）を自動取得して挿入
  - 一般 URL: trafilatura を使用
  - YouTube URL: yt-dlp を使用
- 画像ファイルをドラッグ＆ドロップ、または「IMG」ボタンで選択してフラグメントに添付
  - ラスター画像は WebP に変換して `assets/` フォルダへ保存
  - SVG / GIF はそのままコピー

### メモを閲覧する

![viewer](docs/screenshot_viewer.png)

```bash
python viewer.py
```

サーバーが起動し、ブラウザが自動的に開きます（ポート: `8765`）。

**ビューア機能:**

- 左ペインにInboxと通常フォルダを同列表示し、Archiveだけ別枠で表示
- テキスト検索（リアルタイム）
- タグ絞り込み（複数選択・AND/OR 切り替え）
- 日付範囲フィルタ
- お気に入りのトグル（`#favorite` タグの付け外し）・お気に入りのみ表示
- メモの編集（通常フォルダ / Inbox / Archive。記事のペンシルアイコンから、その記事内で編集する）
- メモの削除（通常フォルダ / Inbox。`config.toml` で設定した Trash フォルダへ移動。添付画像も同時移動）

終了するにはターミナルで `Ctrl+C` を押します。

## 起動スクリプトの作成

`run_fragmentbox.sh` はローカル環境依存のため Git に含まれていません。以下を参考にプロジェクトルートに作成し、`chmod +x` で実行権限を付与してください。

```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

source .venv/bin/activate
python fragmentbox.py
```

## ファイル構成

```
fragmentbox/
├── fragmentbox.py   # GUI クライアント
├── viewer.py        # FastAPI サーバー
├── viewer.html      # ビューア フロントエンド
├── css/
│   └── viewer.css   # スタイルシート
├── config.toml      # パス・ポート・タグ・画像設定
└── pyproject.toml
```

## 設定

`config.toml` でパスとポートを変更できます。

```toml
[paths]
root    = "~/idea_pool/fragmentbox"
active  = "~/idea_pool/fragmentbox/active"
inbox   = "~/idea_pool/fragmentbox/active/inbox"
archive = "~/idea_pool/fragmentbox/archive"
trash   = "~/idea_pool/fragmentbox/Trash"
assets  = "~/idea_pool/fragmentbox/assets"

[viewer]
port = 8765

[tags]
presets = ["idea", "todo", "ref", "question", "memo", "later"]

[images]
quality = 80  # WebP 変換時の品質 (1-100)
```

## フォルダ操作

- 新しいセッションの初期表示はinbox。同じタブの再読み込みでは選択フォルダを保持する。左ペインにinboxと作成済みフォルダを同列で縦に表示する。notesという項目は表示しない。
- 最上部の `+` を押し、名前を入力してEnterまたは「作成」でフォルダを作る。「取消」またはEscapeで閉じる。
- フォルダ名をクリックすると、そのフォルダ内のメモを表示する。
- 名前をドラッグ＆ドロップして並び替える。キーボードでは名前にフォーカスし、`Alt + ↑ / ↓` で移動する。順序は再起動後も保持する。
- 新規フォルダは `paths.active` 直下の1階層。inboxも同じ一覧で並び替え・投稿できる。archiveだけを別枠に置き、通常フォルダ一覧は常に表示する。
- Inboxを含む表示順は `paths.active` の `.navigation-order.json` に保存する。既存MDの移行は行わない。

## 記事の整理・閲覧

- 記事は古い順に並び、新しいものほど下に表示する。初めて開くフォルダは最下部を表示し、フォルダを切り替えて戻ると前回のスクロール位置を復元する。スクロール位置は再読み込みでリセットする。
- 右下のフォルダと右矢印のアイコンで移動先を選ぶ。フォルダ名を検索して絞り込み、クリックまたは `↑ / ↓` とEnterで移動する。Escまたは欄外クリックで閉じる。候補は左ペインの並び順で、Inboxを含み、現在のフォルダとArchiveを除く。アーカイブの記事には移動アイコンを表示しない。
- アーカイブアイコンで `active/フォルダ名/記事.md` から `archive/フォルダ名/記事.md` へ移す。アーカイブ内では復帰アイコンで元の同名フォルダへ戻す。戻し先のフォルダがなければ作成する。
- 移動・アーカイブ・復帰はファイル名、本文、日時を保持する。画像は共通の `assets` に残し、相対リンクも変更しない。同名記事があれば上書きせず、元の場所に残してエラーを表示する。
- 編集は記事内で行う。リンクカードはそのまま表示し、角の×で削除する。Saveで確定し、他の記事から参照されない削除対象サムネイルをTrashへ移す。Cancelでは変更しない。
- 画像リンクを表示時に補正した場合は「リンク補正あり」と隣の `fix` を表示する。`fix` でMD内の補正可能な画像リンクを修正する。画像がない参照は警告し、自動修正しない。

## ビューアから投稿

左ペインでフォルダを選び、画面下部の投稿欄へ入力してSaveで保存する。投稿先は入力欄の上に表示する。投稿後は入力欄が空になり、一覧を更新する。Archiveへは投稿できない。

- 入力欄の下に横並びで表示するタグは `config.toml` のプリセットから読み込み、重複せず本文末尾へ追加する。
- IMGまたは画像ファイルのドロップで添付する。複数選択対応、1枚20 MiBまで。ラスターはWebP、SVG/GIFは元形式で保存する。
- 保存時にURLのタイトル・サイト名・説明・サムネイルを取得する。取得できなかった場合も本文は保存し、警告を表示する。
- 投稿欄内でmacOSはCmd+S / Cmd+Return / Ctrl+Return、その他はCtrl+S / Ctrl+Returnで保存する。
- 保存・添付中は入力とフォルダ切替を無効にする。失敗時は入力内容を保持する。フォルダを変えても下書きは保持する。
- 画像は添付時に保存するため、投稿を破棄すると未参照の画像が残る。

## データの保存場所

root / active / inbox / archive / trash / assets のパスはすべて `config.toml` の `[paths]` セクションで設定します。

## License

MIT
