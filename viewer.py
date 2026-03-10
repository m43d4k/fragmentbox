import re
import shutil
import threading
import tomllib
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).parent

with (HERE / "config.toml").open("rb") as _f:
    _config = tomllib.load(_f)

INBOX_DIR   = Path(_config["paths"]["inbox"]).expanduser()
ARCHIVE_DIR = Path(_config["paths"]["archive"]).expanduser()
TRASH_DIR   = Path(_config["paths"]["trash"]).expanduser()
PORT: int = _config.get("viewer", {}).get("port", 8765)

TAG_PATTERN = re.compile(r"#(\w+)")

app = FastAPI()
app.mount("/css", StaticFiles(directory=HERE / "css"), name="css")


def _source_dir(source: str) -> Path:
    return ARCHIVE_DIR if source == "archive" else INBOX_DIR


def parse_fragment(path: Path) -> dict:
    content = path.read_text(encoding="utf-8").strip()
    tags = TAG_PATTERN.findall(content)
    try:
        dt = datetime.strptime(path.stem, "%Y%m%d_%H%M%S")
    except ValueError:
        dt = datetime.fromtimestamp(path.stat().st_mtime)
    return {
        "id": path.stem,
        "datetime": dt.isoformat(),
        "content": content,
        "tags": tags,
    }


@app.get("/api/fragments")
def get_fragments(source: str = "inbox") -> list[dict]:
    d = _source_dir(source)
    if not d.exists():
        return []
    paths = sorted(d.glob("*.md"), reverse=True)
    return [parse_fragment(p) for p in paths]


@app.get("/api/tags")
def get_tags(source: str = "inbox") -> list[str]:
    d = _source_dir(source)
    if not d.exists():
        return []
    tags: set[str] = set()
    for path in d.glob("*.md"):
        content = path.read_text(encoding="utf-8")
        tags.update(TAG_PATTERN.findall(content))
    return sorted(tags)


@app.delete("/api/fragments/{fragment_id}")
def delete_fragment(fragment_id: str) -> dict:
    path = INBOX_DIR / f"{fragment_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fragment not found")
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    dest = TRASH_DIR / path.name
    shutil.move(str(path), str(dest))
    return {"status": "moved", "id": fragment_id}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "viewer.html")


def _open_browser() -> None:
    import time
    time.sleep(0.8)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT)
