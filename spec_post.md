目的: 断片メモをローカル保存するMac用Python GUI
機能:
- 小さい入力ウィンドウ
- テキスト保存（Cmd+S または Cmd+Return）
- 保存先は ~/idea_pool/fragmentbox/inbox/
- 1保存=1 md
- ファイル名は日時
- 保存後はテキストエリアをクリア
- 右側にタグボタン
- 押すと本文末尾に挿入
- 同じタグの重複挿入は不可
- 1つ目のタグは空行（\n\n）を挟んで挿入（Markdown上で独立行として扱われる）
- 2つ目以降はスペース区切りで並べる
- タグ一覧は tags.yaml から読み込む（Pythonコード内に直書きしない）
URLメタデータ:
- 保存時にテキスト内のURLを検出し、メタデータを自動取得してURL直下に挿入
- 一般URL: trafilatura（title / sitename / description）
- YouTube: yt-dlp（title / sitename=YouTube / description=チャンネル名）
- 既にメタデータ取得済みのURLは再取得しない
- 各フィールドはMarkdown強制改行（行末スペース2つ）で整形
デザイン:
- ダークテーマ（背景 #2b2b2b）
- ボタン類は tk.Label で実装（macOSでの背景色反映のため）
技術:
- Python
- tkinter
- PyYAML（tags.yaml 読み込み用）
- trafilatura（一般URLメタデータ取得）
- yt-dlp（YouTubeメタデータ取得）
ファイル構成:
- fragmentbox.py  — メインスクリプト
- tags.yaml       — タグ一覧（起動時に読み込まれる）
- requirements.txt