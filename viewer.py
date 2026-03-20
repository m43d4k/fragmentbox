import re
import shutil
import threading
import tomllib
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

HERE = Path(__file__).parent

with (HERE / "config.toml").open("rb") as _f:
    _config = tomllib.load(_f)

INBOX_DIR   = Path(_config["paths"]["inbox"]).expanduser()
ARCHIVE_DIR = Path(_config["paths"]["archive"]).expanduser()
TRASH_DIR   = Path(_config["paths"]["trash"]).expanduser()
ASSETS_DIR  = Path(_config["paths"]["assets"]).expanduser()
PORT: int = _config.get("viewer", {}).get("port", 8765)

TAG_PATTERN   = re.compile(r"#(\w+)")
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(\.\./assets/([^)]+)\)")

Source = Literal["inbox", "archive"]


class Fragment(BaseModel):
    id: str
    created_at: datetime
    content: str
    tags: list[str]


class FavoriteResponse(BaseModel):
    status: str
    favorited: bool
    tags: list[str]


class DeleteResponse(BaseModel):
    status: str
    id: str


class FragmentUpdate(BaseModel):
    content: str


app = FastAPI()
app.mount("/css", StaticFiles(directory=HERE / "css"), name="css")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


def _source_dir(source: Source) -> Path:
    return ARCHIVE_DIR if source == "archive" else INBOX_DIR


def parse_fragment(path: Path) -> Fragment:
    content = path.read_text(encoding="utf-8").strip()
    tags = TAG_PATTERN.findall(content)
    try:
        dt = datetime.strptime(path.stem, "%Y%m%d_%H%M%S")
    except ValueError:
        dt = datetime.fromtimestamp(path.stat().st_mtime)
    return Fragment(
        id=path.stem,
        created_at=dt,
        content=content,
        tags=tags,
    )


@app.get("/api/fragments")
def get_fragments(source: Source = "inbox") -> list[Fragment]:
    d = _source_dir(source)
    if not d.exists():
        return []
    paths = sorted(d.glob("*.md"), reverse=True)
    return [parse_fragment(p) for p in paths]


@app.get("/api/tags")
def get_tags(source: Source = "inbox") -> list[str]:
    d = _source_dir(source)
    if not d.exists():
        return []
    tags: set[str] = set()
    for path in d.glob("*.md"):
        content = path.read_text(encoding="utf-8")
        tags.update(TAG_PATTERN.findall(content))
    return sorted(tags)


@app.patch("/api/fragments/{fragment_id}/favorite")
def toggle_favorite(fragment_id: str, source: Source = "inbox") -> FavoriteResponse:
    d = _source_dir(source)
    path = d / f"{fragment_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fragment not found")
    content = path.read_text(encoding="utf-8").rstrip()
    if "#favorite" in content:
        content = re.sub(r"[ \t]*#favorite\b", "", content).rstrip()
        favorited = False
    else:
        content = content + " #favorite"
        favorited = True
    path.write_text(content + "\n", encoding="utf-8")
    return FavoriteResponse(status="ok", favorited=favorited, tags=TAG_PATTERN.findall(content))


@app.put("/api/fragments/{fragment_id}")
def update_fragment(fragment_id: str, body: FragmentUpdate, source: Source = "inbox") -> Fragment:
    d = _source_dir(source)
    path = d / f"{fragment_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fragment not found")
    path.write_text(body.content, encoding="utf-8")
    return parse_fragment(path)


@app.delete("/api/fragments/{fragment_id}")
def delete_fragment(fragment_id: str) -> DeleteResponse:
    path = INBOX_DIR / f"{fragment_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Fragment not found")
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding="utf-8")
    shutil.move(str(path), str(TRASH_DIR / path.name))
    for filename in IMAGE_PATTERN.findall(content):
        img_path = ASSETS_DIR / filename
        if img_path.exists():
            shutil.move(str(img_path), str(TRASH_DIR / filename))
    return DeleteResponse(status="moved", id=fragment_id)


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
