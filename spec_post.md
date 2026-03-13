目的: 断片メモをローカル保存するPython GUI（macOS / Linux対応）
機能:
- 小さい入力ウィンドウ
- テキスト保存ショートカット
  - macOS: Cmd+S / Cmd+Return / Ctrl+Return
  - Linux: Ctrl+S / Ctrl+Return
- 保存先は config.toml の [paths].inbox で設定
- 1保存=1 md
- ファイル名は日時
- 保存後はテキストエリアをクリア
- 右側にタグボタン
- 押すと本文末尾に挿入
- 同じタグの重複挿入は不可
- 1つ目のタグは空行（\n\n）を挟んで挿入（Markdown上で独立行として扱われる）
- 2つ目以降はスペース区切りで並べる
- タグ一覧は config.toml の [tags].presets から読み込む（Pythonコード内に直書きしない）
URLメタデータ:
- 保存時にテキスト内のURLを検出し、メタデータを自動取得してURL直下に挿入
- 一般URL: trafilatura（title / sitename / description）
- YouTube: yt-dlp（title / sitename=YouTube / description=チャンネル名）
- サムネイル画像URLがある場合はダウンロードして WebP に変換し assets/ へ保存、本文に挿入
- 既にメタデータ取得済みのURLは再取得しない
- 各フィールドはMarkdown強制改行（行末スペース2つ）で整形
- メタデータ取得中はUIをロックし、完了後にロック解除して保存
画像:
- テキストエリアへの画像ファイルのドラッグ＆ドロップに対応
  - 画像拡張子のファイルのみ accept（全URLを受けて後段で弾く実装は避ける）
- 「IMG」ボタンでファイルダイアログから画像を選択して添付
- ラスター画像は pyvips で WebP に変換して assets/ フォルダへ保存
- SVG / GIF はそのままコピー（_COPY_ONLY_EXTENSIONS）
- 本文への挿入は Markdown 画像記法（![](../assets/ファイル名)）、行末は  \n
デザイン:
- ダークテーマ（背景 #2b2b2b）
- ボタン類は QPushButton で実装（スタイルシートで背景色制御）
技術:
- Python / PySide6
- tomllib（config.toml 読み込み用、標準ライブラリ）
- trafilatura（一般URLメタデータ取得）
- yt-dlp（YouTubeメタデータ取得）
- pyvips（画像 WebP 変換）
ファイル構成:
- fragmentbox.py  — メインスクリプト
- config.toml     — パス・タグ・画像設定
- pyproject.toml
