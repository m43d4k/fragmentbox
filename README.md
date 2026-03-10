# fragmentbox

A simple personal note-taking tool to quickly capture ideas and save them locally.

[日本語 README](README-ja.md)

## Overview

fragmentbox consists of two components:

- **fragmentbox.py** — A macOS GUI (tkinter) for quickly writing and saving notes
- **viewer.py** — A web viewer (FastAPI) for browsing and searching saved notes

## Requirements

- Python 3.13+
- macOS (GUI uses tkinter)

## Setup

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Capture a note

![post](docs/screenshot_post.png)

```bash
python fragmentbox.py
```

- Type a note in the text area and save with `Cmd+S` or `Cmd+Return`
- The save location can be configured in `config.toml` (one file per note, filename is a timestamp)
- Click a tag button on the right to append a tag to the note (tags are managed in `tags.yaml`)
- URLs in the text are automatically enriched with metadata (title / site name / description) on save
  - General URLs: uses trafilatura
  - YouTube URLs: uses yt-dlp

### Browse notes

![viewer](docs/screenshot_viewer.png)

```bash
python viewer.py
```

The server starts and a browser window opens automatically (port: `8765`).

**Viewer features:**

- Inbox / Archive tab switching
- Real-time text search
- Tag filtering (multiple selection, AND/OR toggle)
- Date range filter
- Delete notes from the Inbox (moved to the Trash folder configured in `config.toml`)

Press `Ctrl+C` in the terminal to stop the server.

## File Structure

```
fragmentbox/
├── fragmentbox.py   # GUI client
├── viewer.py        # FastAPI server
├── viewer.html      # Viewer frontend
├── css/
│   └── viewer.css   # Stylesheet
├── tags.yaml        # Tag list (loaded at startup by fragmentbox.py)
├── config.toml      # Path and port configuration
└── requirements.txt
```

## Configuration

Edit `config.toml` to change paths and the port.

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

## Data Storage

All paths for inbox, archive, and trash are configured in the `[paths]` section of `config.toml`.

## License

MIT
