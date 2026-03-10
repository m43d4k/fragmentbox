# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**fragmentbox** — テキストフラグメント（アイデアの断片）をローカルのインボックスに素早く投入するための小さなパーソナルツール。

## Environment

- Python 3.13.12（mise で管理）
- 仮想環境: `.venv/`（セッション開始時に自動でアクティベートされる）

```bash
# 仮想環境のセットアップ
python -m venv .venv
source .venv/bin/activate

# 依存関係のインストール（追加後）
pip install -r requirements.txt  # または pyproject.toml 使用時: pip install -e .
```

## Code Style

- editorconfig に従う: Python は 4 スペースインデント、UTF-8、LF 改行
