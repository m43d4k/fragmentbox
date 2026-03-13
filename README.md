# fragmentbox

A simple personal note-taking tool to quickly capture ideas and save them locally.

[日本語 README](README-ja.md)

## Overview

fragmentbox consists of two components:

- **fragmentbox.py** — A GUI (PySide6) for quickly writing and saving notes
- **viewer.py** — A web viewer (FastAPI) for browsing and searching saved notes

## Supported Platforms

- macOS
- Linux

## Requirements

- Python 3.12+
- [libvips](https://www.libvips.org/) (used for image compression)

  ```bash
  # macOS
  brew install vips

  # Ubuntu / Debian
  sudo apt install libvips
  ```

## Setup

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
```

## Usage

### Capture a note

![post](docs/screenshot_post.png)

Create and run the launch script `run_fragmentbox.sh` (see "Creating the Launch Script" below).

```bash
./run_fragmentbox.sh
# To enable debug logging
FRAGMENTBOX_LOG=DEBUG ./run_fragmentbox.sh
```

- Type a note in the text area and save with a keyboard shortcut
  - macOS: `Cmd+S` / `Cmd+Return` / `Ctrl+Return`
  - Linux: `Ctrl+S` / `Ctrl+Return`
- The save location can be configured in `config.toml` (one Markdown file per note, filename is a timestamp)
- Click a tag button on the right to append a tag to the note (tags are managed in the `[tags]` section of `config.toml`)
- URLs in the text have their metadata (title / site name / description / thumbnail) automatically fetched and inserted on save
  - General URLs: uses trafilatura
  - YouTube URLs: uses yt-dlp
- Attach images by drag & drop or via the "IMG" button
  - Raster images are converted to WebP and saved in the `assets/` folder
  - SVG / GIF files are copied as-is

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
- Toggle favorite (add/remove the `#favorite` tag)
- Delete notes from the Inbox only (moved to the Trash folder configured in `config.toml`; attached images are also moved)

Press `Ctrl+C` in the terminal to stop the server.

## Creating the Launch Script

`run_fragmentbox.sh` is not included in the repository because it depends on the local environment. Create it in the project root using the template below and make it executable with `chmod +x`.

```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [[ "$(uname)" == "Darwin" ]]; then
  export DYLD_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib:$DYLD_LIBRARY_PATH"
fi

source .venv/bin/activate
python fragmentbox.py
```

On macOS, `DYLD_LIBRARY_PATH` is set for libvips. Adjust the path to match your libvips installation.

## File Structure

```
fragmentbox/
├── fragmentbox.py   # GUI client
├── viewer.py        # FastAPI server
├── viewer.html      # Viewer frontend
├── css/
│   └── viewer.css   # Stylesheet
├── config.toml      # Path, port, tag, and image settings
└── pyproject.toml
```

## Configuration

Edit `config.toml` to change paths and the port.

```toml
[paths]
inbox   = "~/idea_pool/fragmentbox/inbox"
archive = "~/idea_pool/fragmentbox/archive"
trash   = "~/idea_pool/fragmentbox/Trash"
assets  = "~/idea_pool/fragmentbox/assets"

[viewer]
port = 8765

[tags]
presets = ["idea", "todo", "ref", "question", "memo", "later"]

[images]
quality = 80  # WebP conversion quality (1-100)
```

## Data Storage

All paths for inbox, archive, trash, and assets are configured in the `[paths]` section of `config.toml`.

## License

MIT
