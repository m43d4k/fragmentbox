目的: fragmentboxのinbox / archiveに保存されたmdファイルをWebブラウザで閲覧するビューア
構成:
- Pythonサーバー（FastAPI）: mdファイルを読み込みJSON APIとして提供
- フロントエンド: HTML + JavaScript でカード形式表示

表示:
- 1ファイル=1カード（Twitterのタイムライン風）
- 新しい順に並べる
- ファイル名（日時）から投稿日時をカードに表示
- タグ（#tag形式）はカード上でハイライト表示、クリックでタグ絞り込み
- URLはリンクプレビューカード形式で表示（サイト名 / タイトルリンク / 説明文）
  - タイトル1行、説明文2行でclamp
- 本文中の連続する空行は1行分に圧縮して表示（ファイルの改行数に依存しない）

ソース切り替え:
- ヘッダーに inbox / archive タブを表示
- タブ切り替え時に検索・タグ・日付フィルタをリセットして再ロード
- アーカイブは読み取り専用（ゴミ箱ボタン非表示）

検索・フィルタ:
- テキスト検索（リアルタイム）
- タグ絞り込み（複数選択、AND/OR切り替え可）
- 日付範囲絞り込み（from / to、片方だけも可）
- タグ・日付それぞれにクリアボタン

削除（inboxのみ）:
- カードフッターにゴミ箱アイコンボタンを表示
- ボタン押下で確認ダイアログ（小モーダル）を表示、許可で ~/idea_pool/fragmentbox/Trash/ へ移動
- Trash ディレクトリが存在しない場合は自動作成

API:
- GET /api/fragments?source=inbox|archive — フラグメント一覧（JSON）、デフォルト inbox
- GET /api/tags?source=inbox|archive — 使用中タグ一覧（JSON）、デフォルト inbox
- DELETE /api/fragments/{id} — 指定フラグメントを Trash へ移動（inbox専用）

設定:
- config.toml で inbox / archive / trash のパスとサーバーポートを管理

起動方式:
- `python viewer.py` を実行するとサーバーが起動し、ブラウザが自動的に開く
- 常駐しない。ターミナルを閉じる or Ctrl+C で終了

技術:
- Python / FastAPI + uvicorn
- HTML / CSS / JavaScript（バニラ、フレームワークなし）

ファイル構成:
- viewer.py       — FastAPIサーバー（起動時にブラウザを自動オープン）
- viewer.html     — フロントエンド
- css/viewer.css  — スタイルシート
- config.toml     — パス・ポート・タグプリセット設定
