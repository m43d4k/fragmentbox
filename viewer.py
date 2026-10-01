import json
import html
import ipaddress
import subprocess
import sys
import uuid
import hashlib
import os
import re
import shutil
import tempfile
import threading
import tomllib
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, unquote, urlsplit

import fragmentbox as capture
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = Path(__file__).parent

with (HERE / "config.toml").open("rb") as _f:
    _config = tomllib.load(_f)

ROOT_DIR    = Path(_config["paths"]["root"]).expanduser()
ACTIVE_DIR  = Path(_config["paths"]["active"]).expanduser()
INBOX_DIR   = Path(_config["paths"]["inbox"]).expanduser()
ARCHIVE_DIR = Path(_config["paths"]["archive"]).expanduser()
ASSETS_DIR  = Path(_config["paths"]["assets"]).expanduser()
PORT: int = _config.get("viewer", {}).get("port", 8765)

TAG_PATTERN   = re.compile(r"#(\w+)")
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\((?:\.\./)+assets/([^/()]+)\)")

Source = Literal["notes", "inbox", "archive"]


class ImageLink(BaseModel):
    original: str
    status: Literal["ok", "corrected", "missing"]
    corrected: str | None = None
    url: str | None = None


class Attachment(BaseModel):
    reference: str
    asset: str
    name: str
    size: int | None


ATTACHMENT_PATTERN = re.compile(r"(?<!!)\[([^\]\n]*)\]\(((?:\.\./)*assets/|/assets/)(attachment_[a-f0-9]{32}\.[a-z0-9]+)\)")


def _attachment_path(name: str) -> Path:
    if (not re.fullmatch(r"attachment_[a-f0-9]{32}\.[a-z0-9]+", name)
            or Path(name).suffix not in capture.ATTACHMENT_EXTENSIONS):
        raise HTTPException(422, "対応していない添付ファイルです")
    path = ASSETS_DIR / name
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "添付ファイルが見つかりません")
    return path


def attachment_links(content: str) -> list[Attachment]:
    result = []
    for match in ATTACHMENT_PATTERN.finditer(content):
        try:
            size = _attachment_path(match[3]).stat().st_size
        except HTTPException:
            size = None
        result.append(Attachment(reference=match[2] + match[3], asset=match[3],
                                 name=html.unescape(match[1]), size=size))
    return result


def _relative_attachment_references(content: str, directory: Path) -> str:
    def replace(match: re.Match) -> str:
        relative = Path(os.path.relpath(ASSETS_DIR / match[3], directory)).as_posix()
        return f"[{match[1]}]({relative})"
    return ATTACHMENT_PATTERN.sub(replace, content)


class Fragment(BaseModel):
    id: str
    created_at: datetime
    content: str
    tags: list[str]
    tag_lines: list[int] = Field(default_factory=list)
    image_links: list[ImageLink] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)


class FavoriteResponse(BaseModel):
    status: str
    favorited: bool
    tags: list[str]
    content: str
    tag_lines: list[int]


class DeleteResponse(BaseModel):
    status: str
    id: str


class FragmentUpdate(BaseModel):
    content: str
    remove_unused_thumbnails: bool = False
    enrich_links: bool = False


app = FastAPI()
app.mount("/vendor", StaticFiles(directory=HERE / "vendor"), name="vendor")
app.mount("/css", StaticFiles(directory=HERE / "css"), name="css")
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


def _source_dir(source: Source) -> Path:
    return {"notes": ACTIVE_DIR, "inbox": INBOX_DIR, "archive": ARCHIVE_DIR}[source]


class Folder(BaseModel):
    name: str


class FolderCreate(BaseModel):
    name: str


class FolderOrder(BaseModel):
    names: list[str]


_folder_lock = threading.Lock()


def _validate_name(name: str) -> None:
    if (not name or name != name.strip() or name.startswith(".")
            or any(c in name for c in '/\\:')
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or len(name.encode("utf-8")) > 255):
        raise HTTPException(422, "Invalid folder or file name")


def _folder_dir(source: Source, folder: str) -> Path:
    root = _source_dir(source)
    if not folder:
        return root
    _validate_name(folder)
    path = root / folder
    if source == "notes" and (folder == "notes" or path.resolve() in {
            p.resolve() for p in (INBOX_DIR, ARCHIVE_DIR, ASSETS_DIR)}):
        raise HTTPException(422, "Reserved directory")
    if path.is_symlink() or not path.is_dir():
        raise HTTPException(404, "Folder not found")
    return path


def _fragment_path(source: Source, folder: str, fragment_id: str) -> Path:
    _validate_name(fragment_id)
    path = _folder_dir(source, folder) / f"{fragment_id}.md"
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "Fragment not found")
    return path


def _folder_names(source: Source) -> list[str]:
    root = _source_dir(source)
    if not root.exists():
        return []
    reserved = {p.resolve() for p in (INBOX_DIR, ARCHIVE_DIR, ASSETS_DIR)} if source == "notes" else set()
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
                  and p.resolve() not in reserved and not (source == "notes" and p.name == "notes"))


@app.get("/api/folders")
def get_folders(source: Source = "notes") -> list[Folder]:
    names = _folder_names(source)
    order_file = _source_dir(source) / ".folder-order.json"
    order = []
    if order_file.exists():
        try:
            order = json.loads(order_file.read_text(encoding="utf-8"))
            if (not isinstance(order, list) or any(not isinstance(n, str) for n in order)
                    or len(order) != len(set(order))):
                raise ValueError("Invalid order")
        except (ValueError, OSError) as exc:
            raise HTTPException(500, "Cannot read folder order") from exc
    ordered = [n for n in order if n in names]
    return [Folder(name=n) for n in ordered + [n for n in names if n not in ordered]]


@app.post("/api/folders", status_code=201)
def create_folder(body: FolderCreate) -> Folder:
    _validate_name(body.name)
    if body.name == "notes" or (ACTIVE_DIR / body.name).resolve() in {
            p.resolve() for p in (INBOX_DIR, ARCHIVE_DIR, ASSETS_DIR)}:
        raise HTTPException(422, "Reserved directory")
    with _folder_lock:
        try:
            ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
            (ACTIVE_DIR / body.name).mkdir()
        except FileExistsError as exc:
            raise HTTPException(409, "Folder already exists") from exc
        except OSError as exc:
            raise HTTPException(500, "Cannot create folder") from exc
    return Folder(name=body.name)


@app.put("/api/folders/order")
def reorder_folders(body: FolderOrder, source: Source = "notes") -> list[Folder]:
    with _folder_lock:
        names = _folder_names(source)
        if len(body.names) != len(set(body.names)) or set(body.names) != set(names):
            raise HTTPException(409, "Folder list changed; reload before reordering")
        root = _source_dir(source)
        temp_path = None
        try:
            root.mkdir(parents=True, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix=".folder-order-", dir=root)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body.names, f, ensure_ascii=False)
                f.write("\n")
            os.replace(temp_path, root / ".folder-order.json")
        except OSError as exc:
            raise HTTPException(500, "Cannot save folder order") from exc
        finally:
            if temp_path and Path(temp_path).exists():
                Path(temp_path).unlink()
    return [Folder(name=n) for n in body.names]



class NavigationFolder(BaseModel):
    id: str
    name: str
    source: Source
    folder: str


@app.get("/api/navigation")
def get_navigation() -> list[NavigationFolder]:
    entries = [NavigationFolder(id="inbox:", name="inbox", source="inbox", folder="")]
    entries += [NavigationFolder(id=f"notes:{f.name}", name=f.name, source="notes", folder=f.name)
                for f in get_folders("notes")]
    path = ACTIVE_DIR / ".navigation-order.json"
    if not path.exists():
        return entries
    try:
        order = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(order, list) or any(not isinstance(n, str) for n in order)
                or len(order) != len(set(order))):
            raise ValueError("Invalid order")
    except (ValueError, OSError) as exc:
        raise HTTPException(500, "Cannot read folder order") from exc
    by_id = {entry.id: entry for entry in entries}
    return [by_id[key] for key in order if key in by_id] + [e for e in entries if e.id not in order]


@app.put("/api/navigation/order")
def reorder_navigation(body: FolderOrder) -> list[NavigationFolder]:
    with _folder_lock:
        entries = get_navigation()
        by_id = {entry.id: entry for entry in entries}
        if len(body.names) != len(set(body.names)) or set(body.names) != set(by_id):
            raise HTTPException(409, "Folder list changed; reload before reordering")
        temporary = None
        try:
            ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".navigation-order-", dir=ACTIVE_DIR)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body.names, f, ensure_ascii=False)
                f.write("\n")
            os.replace(temporary, ACTIVE_DIR / ".navigation-order.json")
        except OSError as exc:
            raise HTTPException(500, "Cannot save folder order") from exc
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)
    return [by_id[key] for key in body.names]


MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def image_links(content: str, note: Path) -> list[ImageLink]:
    result = []
    seen = set()
    assets = ASSETS_DIR.resolve()
    for match in MARKDOWN_IMAGE.finditer(content):
        reference = match.group(1)
        if reference in seen or urlsplit(reference).scheme or reference.startswith("//"):
            continue
        seen.add(reference)
        decoded = unquote(reference)
        original = (note.parent / decoded).resolve()
        if original.is_file():
            if original.parent == assets:
                result.append(ImageLink(original=reference, status="ok", url="/assets/" + quote(original.name)))
            continue
        # 共通assetsへの参照だけを補正し、同名の無関係なファイルには置き換えない。
        if not re.fullmatch(r"(?:\.\./)*assets/[^/]+|/assets/[^/]+", decoded):
            result.append(ImageLink(original=reference, status="missing"))
            continue
        candidate = ASSETS_DIR / Path(decoded).name
        if candidate.is_file() and not candidate.is_symlink():
            relative = Path(os.path.relpath(candidate.resolve(), note.parent.resolve())).as_posix()
            result.append(ImageLink(original=reference, status="corrected", corrected=relative,
                                    url="/assets/" + quote(candidate.name)))
        else:
            result.append(ImageLink(original=reference, status="missing"))
    return result


@app.post("/api/fragments/{fragment_id}/repair-image-links")
def repair_image_links(fragment_id: str, body: FragmentUpdate, source: Source = "inbox", folder: str = "") -> Fragment:
    path = _fragment_path(source, folder, fragment_id)
    with _folder_lock:
        original = path.read_text(encoding="utf-8")
        if original.rstrip() != body.content:
            raise HTTPException(409, "記事が変更されています。再読み込みしてから修正してください")
        corrections = {link.original: link.corrected for link in image_links(original, path) if link.status == "corrected"}
        def replace(match):
            corrected = corrections.get(match.group(1))
            if corrected is None:
                return match.group(0)
            start = match.start(1) - match.start()
            end = match.end(1) - match.start()
            return match.group(0)[:start] + corrected + match.group(0)[end:]
        updated = MARKDOWN_IMAGE.sub(replace, original)
        if updated != original:
            temporary = None
            try:
                fd, temporary = tempfile.mkstemp(prefix=".repair-", dir=path.parent)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(updated)
                shutil.copymode(path, temporary)
                os.replace(temporary, path)
            except OSError as exc:
                raise HTTPException(500, "画像リンクを修正できませんでした") from exc
            finally:
                if temporary:
                    Path(temporary).unlink(missing_ok=True)
    return parse_fragment(path)


def parse_fragment(path: Path) -> Fragment:
    content = path.read_text(encoding="utf-8").rstrip()
    tags = capture.extract_tags(content)
    try:
        dt = datetime.strptime(path.stem, "%Y%m%d_%H%M%S_%f" if path.stem.count("_") == 2 else "%Y%m%d_%H%M%S")
    except ValueError:
        dt = datetime.fromtimestamp(path.stat().st_mtime)
    return Fragment(
        id=path.stem,
        created_at=dt,
        content=content,
        tags=tags,
        tag_lines=capture.tag_line_numbers(content),
        image_links=image_links(content, path),
        attachments=attachment_links(content),
    )



class TagAnalysis(BaseModel):
    tags: list[str]
    separator: str


class TagContent(BaseModel):
    content: str


@app.post("/api/tags/analyze")
def analyze_tags(body: TagContent) -> TagAnalysis:
    return TagAnalysis(tags=capture.extract_tags(body.content),
                       separator=capture._tag_separator(body.content))


class FragmentCreate(BaseModel):
    content: str


class PostResponse(BaseModel):
    fragment: Fragment
    warnings: list[str]


class ComposerConfig(BaseModel):
    tags: list[str]
    image_extensions: list[str]
    image_max_bytes: int
    attachment_extensions: list[str]
    attachment_max_bytes: int


class ImageResponse(BaseModel):
    markdown: str


_IMAGE_MAX_BYTES = 20 * 1024 * 1024


@app.get("/api/composer")
def composer_config() -> ComposerConfig:
    return ComposerConfig(tags=_config.get("tags", {}).get("presets", []),
                          image_extensions=sorted(capture.IMAGE_EXTENSIONS),
                          image_max_bytes=_IMAGE_MAX_BYTES,
                          attachment_extensions=sorted(capture.ATTACHMENT_EXTENSIONS),
                          attachment_max_bytes=capture.ATTACHMENT_MAX_BYTES)


@app.post("/api/attachments", status_code=201)
async def upload_attachment(request: Request, filename: str) -> ImageResponse:
    _validate_name(filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in capture.ATTACHMENT_EXTENSIONS:
        raise HTTPException(422, "対応していないファイル形式です")
    name = f"attachment_{uuid.uuid4().hex}{suffix}"
    fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=ASSETS_DIR)
    try:
        size = 0
        with os.fdopen(fd, "wb") as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > capture.ATTACHMENT_MAX_BYTES:
                    raise HTTPException(413, "添付ファイルは100 MiB以下にしてください")
                stream.write(chunk)
        if not size:
            raise HTTPException(422, "添付ファイルが空です")
        os.replace(temporary, ASSETS_DIR / name)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return ImageResponse(markdown=capture.attachment_markdown(filename, f"/assets/{name}"))


class OpenResponse(BaseModel):
    status: str


@app.post("/api/attachments/{name}/open")
def open_attachment(name: str, request: Request) -> OpenResponse:
    # カスタムヘッダーにより、他サイトのフォーム等からアプリを起動させない。
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    origin = request.headers.get("origin")
    if (not local or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or request.headers.get("x-fragmentbox-open") != "1"
            or (origin and origin != str(request.base_url).rstrip("/"))):
        raise HTTPException(403, "このMacのビューアから開いてください")
    path = _attachment_path(name)
    if sys.platform != "darwin":
        raise HTTPException(422, "既定のアプリで開く操作はmacOS専用です")
    try:
        subprocess.run(["/usr/bin/open", str(path)], check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(500, "既定のアプリで開けませんでした。対応するアプリを確認してください") from exc
    return OpenResponse(status="opened")


def _posting_dir(source: Source, folder: str) -> Path:
    if source == "archive":
        raise HTTPException(422, "Archiveには投稿できません")
    if source == "notes" and not folder:
        raise HTTPException(422, "投稿先フォルダを選択してください")
    return _folder_dir(source, folder)


@app.post("/api/images", status_code=201)
async def upload_image(request: Request, filename: str) -> ImageResponse:
    suffix = Path(filename).suffix.lower()
    if suffix not in capture.IMAGE_EXTENSIONS:
        raise HTTPException(422, "対応していない画像形式です")
    fd, name = tempfile.mkstemp(suffix=suffix)
    path = Path(name)
    try:
        size = 0
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > _IMAGE_MAX_BYTES:
                    raise HTTPException(413, "画像は20 MiB以下にしてください")
                f.write(chunk)
        if not size:
            raise HTTPException(422, "画像が空です")
        try:
            dest = await run_in_threadpool(capture.import_image, path, ASSETS_DIR)
        except Exception as exc:
            raise HTTPException(422, "画像を保存できませんでした") from exc
        return ImageResponse(markdown=f"![](/assets/{dest.name})  \n")
    finally:
        path.unlink(missing_ok=True)


def _enrich_post(content: str) -> tuple[str, list[str]]:
    warnings = []
    lines = content.splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if (line.lstrip().startswith(("![", "title:", "sitename:", "description:"))
                or ATTACHMENT_PATTERN.fullmatch(line.strip())):
            continue
        has_title = False
        for following in lines[i + 1:]:
            if not following.strip():
                break
            if following.strip().startswith("title:"):
                has_title = True
                break
        if has_title:
            continue
        matches = list(capture.URL_PATTERN.finditer(line))
        for match in reversed(matches):
            url = match.group().rstrip(".,;:!?()'\">")
            try:
                meta = capture._fetch_metadata(url)
            except Exception:
                warnings.append(f"URL情報を取得できませんでした: {url}")
                continue
            details = [f"{key}: {meta[key]}" for key in ("title", "sitename", "description") if meta.get(key)]
            for image_url in capture._metadata_image_urls(meta):
                thumb = capture._download_thumbnail(image_url, ASSETS_DIR)
                if thumb:
                    details.append(f"![](/assets/{thumb.name})")
                else:
                    warnings.append(f"サムネイルを取得できませんでした: {url}")
            if not details:
                warnings.append(f"URL情報が見つかりませんでした: {url}")
                continue
            start, end = match.start(), match.start() + len(url)
            prefix, suffix = line[:start], line[end:]
            line = (prefix + ("  \n" if prefix else "") + url + "  \n"
                    + "".join(detail + "  \n" for detail in details) + suffix.lstrip("\r\n"))
        lines[i] = line
    return "".join(lines), warnings


def _relative_image_references(content: str, directory: Path) -> str:
    content = _relative_attachment_references(content, directory)
    # 添付時の共通URLを、選択された投稿先から解決可能な相対パスへ変換する。
    def image_reference(match: re.Match) -> str:
        name = match.group(2)
        asset = ASSETS_DIR / name
        if asset.is_symlink() or not asset.is_file():
            raise HTTPException(422, "添付画像が見つかりません")
        relative = Path(os.path.relpath(asset, directory)).as_posix()
        return f"![{match.group(1)}]({relative})"
    return re.sub(r"!\[([^\]]*)\]\(/assets/([^/()]+)\)", image_reference, content)


@app.post("/api/fragments", status_code=201)
def create_fragment(body: FragmentCreate, source: Source = "notes", folder: str = "") -> PostResponse:
    directory = _posting_dir(source, folder)
    content = body.content.rstrip()
    if not content:
        raise HTTPException(422, "本文を入力してください")
    content, warnings = _enrich_post(content)
    content = _relative_image_references(content, directory)
    # 最後の画像行もMarkdown強制改行を保持する。
    if re.search(r"!\[[^\]]*\]\([^)]*\)$", content):
        content += "  \n"
    filename = datetime.now().strftime("%Y%m%d_%H%M%S_%f.md")
    path = directory / filename
    with _folder_lock:
        try:
            directory = _posting_dir(source, folder)
            path = directory / filename
            if not folder:
                directory.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as f:
                f.write(content)
        except FileExistsError as exc:
            raise HTTPException(409, "保存名が重複しました。再度保存してください") from exc
        except OSError as exc:
            raise HTTPException(500, "投稿を保存できませんでした") from exc
        return PostResponse(fragment=parse_fragment(path), warnings=warnings)


@app.get("/api/fragments")
def get_fragments(source: Source = "inbox", folder: str = "") -> list[Fragment]:
    d = _folder_dir(source, folder)
    if not d.exists():
        return []
    paths = sorted(d.glob("*.md"), reverse=True)
    return [parse_fragment(p) for p in paths if not p.is_symlink()]


@app.get("/api/tags")
def get_tags(source: Source = "inbox", folder: str = "") -> list[str]:
    d = _folder_dir(source, folder)
    if not d.exists():
        return []
    tags: set[str] = set()
    for path in d.glob("*.md"):
        if path.is_symlink():
            continue
        content = path.read_text(encoding="utf-8")
        tags.update(capture.extract_tags(content))
    return sorted(tags)


@app.patch("/api/fragments/{fragment_id}/favorite")
def toggle_favorite(fragment_id: str, source: Source = "inbox", folder: str = "") -> FavoriteResponse:
    with _folder_lock:
        path = _fragment_path(source, folder, fragment_id)
        content = path.read_text(encoding="utf-8").rstrip()
        if "favorite" in capture.extract_tags(content):
            lines = content.splitlines(keepends=True)
            for number in capture.tag_line_numbers(content):
                lines[number] = re.sub(r"[ \t]*#favorite(?!\w)", "", lines[number])
            content = "".join(lines).rstrip()
            favorited = False
        else:
            content += capture._tag_separator(content) + "#favorite"
            favorited = True
        path.write_text(content + "\n", encoding="utf-8")
        return FavoriteResponse(status="ok", favorited=favorited, tags=capture.extract_tags(content),
                                content=content, tag_lines=capture.tag_line_numbers(content))


def _asset_references(content: str, note: Path) -> set[Path]:
    assets = ASSETS_DIR.resolve()
    result = {ASSETS_DIR.resolve() / match[3] for match in ATTACHMENT_PATTERN.finditer(content)
              if Path(match[3]).suffix in capture.ATTACHMENT_EXTENSIONS
              and not (ASSETS_DIR / match[3]).is_symlink()}
    for reference in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", content):
        if reference.startswith("/assets/"):
            candidate = ASSETS_DIR / reference[len("/assets/"):]
        elif "://" in reference or reference.startswith("/"):
            continue
        else:
            candidate = note.parent / reference
        resolved = candidate.resolve()
        if resolved.parent == assets and not candidate.is_symlink():
            result.add(resolved)
    return result


def _thumbnail_references(content: str, note: Path) -> set[Path]:
    lines = content.splitlines()
    result = set()
    for i, line in enumerate(lines):
        if not re.fullmatch(r"https?://\S+", line.strip()):
            continue
        j = i + 1
        has_title = False
        while j < len(lines) and re.match(r"^(title|sitename|description):", lines[j]):
            has_title |= bool(re.match(r"^title:\s*\S", lines[j]))
            j += 1
        while has_title and j < len(lines) and re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", lines[j].strip()):
            result.update(_asset_references(lines[j], note))
            j += 1
    return result


def _unreferenced_assets(candidates: set[Path], excluded: set[Path]) -> set[Path]:
    remaining = set(candidates)
    if not remaining:
        return set()
    roots = {ROOT_DIR, ACTIVE_DIR, INBOX_DIR, ARCHIVE_DIR}
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        def failed(error):
            raise error
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
            dirs[:] = [name for name in dirs if not name.startswith(".")
                       and not (Path(directory) / name).is_symlink()
                       and (Path(directory) / name).resolve() != ASSETS_DIR.resolve()]
            for name in files:
                path = Path(directory) / name
                if path.suffix != ".md" or path.is_symlink():
                    continue
                resolved = path.resolve()
                if resolved in seen or resolved in excluded:
                    continue
                seen.add(resolved)
                remaining -= _asset_references(path.read_text(encoding="utf-8"), path)
                if not remaining:
                    return set()
    return remaining


def _unreferenced_thumbnails(candidates: set[Path], edited: Path, content: str) -> set[Path]:
    return _unreferenced_assets(candidates - _asset_references(content, edited), {edited.resolve()})


def _atomic_write(path: Path, data: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".fragmentbox-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class TagRename(BaseModel):
    old: str
    new: str


class TagRenameResponse(BaseModel):
    old: str
    new: str
    count: int


def _rename_tag_text(content: str, old: str, new: str) -> str:
    lines = content.splitlines(keepends=True)
    for number in capture.tag_line_numbers(content):
        lines[number] = TAG_PATTERN.sub(
            lambda match: '#' + new if match[1] == old else match[0], lines[number])
    return ''.join(lines)


@app.post("/api/tags/rename")
def rename_tag(body: TagRename, source: Source = "inbox", folder: str = "") -> TagRenameResponse:
    if any(not re.fullmatch(r"\w+", tag) for tag in (body.old, body.new)):
        raise HTTPException(422, "タグ名は文字・数字・アンダースコアで入力してください（#は不要です）")
    if source == 'inbox':
        if folder:
            raise HTTPException(422, "フォルダの指定が不正です")
        name = INBOX_DIR.name
    else:
        if not folder:
            raise HTTPException(422, "フォルダを選択してください")
        _folder_dir(source, folder)
        name = folder
    _validate_name(name)
    with _folder_lock:
        directories = [INBOX_DIR if name == INBOX_DIR.name else ACTIVE_DIR / name, ARCHIVE_DIR / name]
        changes = []
        try:
            for directory in directories:
                if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
                    raise HTTPException(422, "対象フォルダを読み込めません")
                if not directory.exists():
                    continue
                for path in sorted(directory.glob('*.md')):
                    if path.is_symlink():
                        raise HTTPException(422, "対象記事にシンボリックリンクがあります")
                    original = path.read_bytes()
                    updated = _rename_tag_text(original.decode('utf-8'), body.old, body.new).encode('utf-8')
                    if original != updated:
                        stat = path.stat()
                        changes.append((path, original, updated, (stat.st_atime_ns, stat.st_mtime_ns)))
            written = []
            try:
                for path, original, updated, times in changes:
                    _atomic_write(path, updated)
                    written.append((path, original, times))
                    os.utime(path, ns=times)
            except OSError:
                for path, original, times in reversed(written):
                    _atomic_write(path, original)
                    os.utime(path, ns=times)
                raise
        except (OSError, UnicodeError) as exc:
            raise HTTPException(500, "タグ名を変更できませんでした") from exc
    return TagRenameResponse(old=body.old, new=body.new, count=len(changes))


class FragmentEditResponse(Fragment):
    warnings: list[str] = Field(default_factory=list)


@app.put("/api/fragments/{fragment_id}")
def update_fragment(fragment_id: str, body: FragmentUpdate, source: Source = "inbox", folder: str = "") -> FragmentEditResponse:
    with _folder_lock:
        path = _fragment_path(source, folder, fragment_id)
        original = path.read_text(encoding="utf-8")
    content, warnings = _enrich_post(body.content) if body.enrich_links else (body.content, [])
    if body.enrich_links:
        content = _relative_image_references(content, path.parent)
    with _folder_lock:
        path = _fragment_path(source, folder, fragment_id)
        if path.read_text(encoding="utf-8") != original:
            raise HTTPException(409, "記事が変更されました。再読み込みして確認してください")
        try:
            removed = set()
            if body.remove_unused_thumbnails:
                candidates = _thumbnail_references(original, path) - _thumbnail_references(content, path)
                removed = _unreferenced_thumbnails(candidates, path, content)
            _atomic_write(path, content.encode("utf-8"))
            for image in removed:
                image.unlink(missing_ok=True)
        except (OSError, UnicodeError) as exc:
            raise HTTPException(500, "記事または画像の更新に失敗しました。再読み込みして状態を確認してください") from exc
        return FragmentEditResponse(**parse_fragment(path).model_dump(), warnings=warnings)


class ArchiveResponse(BaseModel):
    status: str
    id: str
    folder: str


class FragmentMove(BaseModel):
    source: Literal["inbox", "notes"]
    folder: str = ""


@app.post("/api/fragments/{fragment_id}/move")
def move_fragment(fragment_id: str, body: FragmentMove, source: Source = "inbox", folder: str = "") -> ArchiveResponse:
    if source == "archive" or (source == "notes" and not folder) or (source == "inbox" and folder):
        raise HTTPException(422, "通常フォルダの記事を選択してください")
    if (body.source == "notes" and not body.folder) or (body.source == "inbox" and body.folder):
        raise HTTPException(422, "移動先のフォルダを選択してください")
    with _folder_lock:
        path = _fragment_path(source, folder, fragment_id)
        directory = _folder_dir(body.source, body.folder)
        if directory.resolve() == path.parent.resolve():
            raise HTTPException(422, "現在のフォルダには移動できません")
        destination = directory / path.name
        created = False
        try:
            with destination.open("xb") as target:
                created = True
                content = _relative_attachment_references(path.read_bytes().decode("utf-8"), directory)
                target.write(content.encode("utf-8"))
            shutil.copystat(path, destination)
            path.unlink()
        except FileExistsError as exc:
            raise HTTPException(409, "移動先に同名の記事があります") from exc
        except OSError as exc:
            if created:
                destination.unlink(missing_ok=True)
            raise HTTPException(500, "記事を移動できませんでした") from exc
    return ArchiveResponse(status="moved", id=fragment_id, folder=directory.name)


@app.post("/api/fragments/{fragment_id}/archive")
def archive_fragment(fragment_id: str, source: Source = "inbox", folder: str = "") -> ArchiveResponse:
    if source == "archive" or (source == "notes" and not folder) or (source == "inbox" and folder):
        raise HTTPException(422, "通常フォルダの記事を選択してください")
    with _folder_lock:
        path = _fragment_path(source, folder, fragment_id)
        name = path.parent.name
        _validate_name(name)
        directory = ARCHIVE_DIR / name
        if directory.is_symlink():
            raise HTTPException(422, "アーカイブ先にシンボリックリンクは使えません")
        destination = directory / path.name
        created = False
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as target:
                created = True
                content = _relative_attachment_references(path.read_bytes().decode("utf-8"), directory)
                target.write(content.encode("utf-8"))
            shutil.copystat(path, destination)
            path.unlink()
        except FileExistsError as exc:
            raise HTTPException(409, "アーカイブ先に同名の記事があります") from exc
        except OSError as exc:
            if created:
                destination.unlink(missing_ok=True)
            raise HTTPException(500, "アーカイブへ移動できませんでした") from exc
    return ArchiveResponse(status="archived", id=fragment_id, folder=name)


@app.post("/api/fragments/{fragment_id}/restore")
def restore_fragment(fragment_id: str, source: Source = "archive", folder: str = "") -> ArchiveResponse:
    if source != "archive" or not folder:
        raise HTTPException(422, "アーカイブ内のフォルダの記事を選択してください")
    with _folder_lock:
        path = _fragment_path(source, folder, fragment_id)
        directory = INBOX_DIR if folder == INBOX_DIR.name else ACTIVE_DIR / folder
        if directory.is_symlink() or (folder != INBOX_DIR.name and (
                folder == "notes" or directory.resolve() in {
                    p.resolve() for p in (ARCHIVE_DIR, ASSETS_DIR)})):
            raise HTTPException(422, "このフォルダには戻せません")
        destination = directory / path.name
        created = False
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as target:
                created = True
                content = _relative_attachment_references(path.read_bytes().decode("utf-8"), directory)
                target.write(content.encode("utf-8"))
            shutil.copystat(path, destination)
            path.unlink()
        except FileExistsError as exc:
            raise HTTPException(409, "戻し先に同名の記事があります") from exc
        except OSError as exc:
            if created:
                destination.unlink(missing_ok=True)
            raise HTTPException(500, "記事を元のフォルダへ戻せませんでした") from exc
    return ArchiveResponse(status="restored", id=fragment_id, folder=folder)


def _delete_articles(paths: list[Path]) -> None:
    candidates = set()
    for path in paths:
        candidates.update(_asset_references(path.read_text(encoding="utf-8"), path))
    images = _unreferenced_assets(candidates, {path.resolve() for path in paths})
    for path in paths:
        path.unlink()
    for image in images:
        image.unlink(missing_ok=True)


@app.delete("/api/fragments/{fragment_id}")
def delete_fragment(fragment_id: str, source: Source = "inbox", folder: str = "") -> DeleteResponse:
    if source == "archive":
        raise HTTPException(422, "Cannot delete archived fragments")
    with _folder_lock:
        path = _fragment_path(source, folder, fragment_id)
        try:
            _delete_articles([path])
        except (OSError, UnicodeError) as exc:
            raise HTTPException(500, "削除処理に失敗しました。一部削除済みの可能性があります。再読み込みしてください") from exc
    return DeleteResponse(status="deleted", id=fragment_id)


class FolderDeletePreview(BaseModel):
    name: str
    count: int
    revision: str


class FolderDeleteRequest(BaseModel):
    revision: str


def _folder_contents(name: str) -> tuple[Path, list[Path], str]:
    if not name:
        raise HTTPException(422, "フォルダを選択してください")
    directory = _folder_dir("notes", name)
    paths = sorted(directory.iterdir())
    if any(p.is_symlink() or not p.is_file() or p.suffix != ".md" for p in paths):
        raise HTTPException(422, "記事以外のファイルやサブフォルダがあります。内容を確認してください")
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return directory, paths, digest.hexdigest()


@app.get("/api/folders/{name}/delete-preview")
def preview_folder_delete(name: str) -> FolderDeletePreview:
    with _folder_lock:
        _, paths, revision = _folder_contents(name)
    return FolderDeletePreview(name=name, count=len(paths), revision=revision)


@app.delete("/api/folders/{name}")
def delete_folder(name: str, body: FolderDeleteRequest) -> FolderDeletePreview:
    with _folder_lock:
        directory, paths, revision = _folder_contents(name)
        if revision != body.revision:
            raise HTTPException(409, "フォルダの内容が変わりました。削除を確認し直してください")
        order = [f.id for f in get_navigation() if f.id != f"notes:{name}"]
        try:
            _delete_articles(paths)
            directory.rmdir()
            _atomic_write(ACTIVE_DIR / ".navigation-order.json", json.dumps(order, ensure_ascii=False).encode())
        except (OSError, UnicodeError) as exc:
            raise HTTPException(500, "フォルダの削除処理に失敗しました。一部削除済みの可能性があります。再読み込みしてください") from exc
    return FolderDeletePreview(name=name, count=len(paths), revision=revision)


@app.patch("/api/folders/{name}")
def rename_folder(name: str, body: FolderCreate) -> Folder:
    with _folder_lock:
        if not name:
            raise HTTPException(422, "フォルダを選択してください")
        original = _folder_dir("notes", name)
        _validate_name(body.name)
        target = ACTIVE_DIR / body.name
        if body.name == "notes" or target.resolve() in {p.resolve() for p in (INBOX_DIR, ARCHIVE_DIR, ASSETS_DIR)}:
            raise HTTPException(422, "予約されたフォルダ名です")
        if name == body.name:
            return Folder(name=name)
        archived, archived_target = ARCHIVE_DIR / name, ARCHIVE_DIR / body.name
        if target.exists() or target.is_symlink() or archived_target.exists() or archived_target.is_symlink():
            raise HTTPException(409, "同名のフォルダがあります。統合せず名前変更を中止しました")
        if archived.is_symlink() or (archived.exists() and not archived.is_dir()):
            raise HTTPException(422, "Archive内の同名項目を変更できません")
        updates = {}
        for root, filename in [(ACTIVE_DIR, '.navigation-order.json'), (ACTIVE_DIR, '.folder-order.json'), (ARCHIVE_DIR, '.folder-order.json')]:
            path = root / filename
            if not path.exists():
                continue
            raw = path.read_bytes()
            try:
                values = json.loads(raw)
                if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                    raise ValueError()
            except ValueError as exc:
                raise HTTPException(500, "フォルダの表示順を読み込めません") from exc
            old, new = (f'notes:{name}', f'notes:{body.name}') if filename == '.navigation-order.json' else (name, body.name)
            updates[path] = (raw, json.dumps([new if v == old else v for v in values], ensure_ascii=False).encode())
        moved, written = [], []
        try:
            original.rename(target)
            moved.append((target, original))
            if archived.exists():
                archived.rename(archived_target)
                moved.append((archived_target, archived))
            for path, (old, new) in updates.items():
                _atomic_write(path, new)
                written.append((path, old))
        except OSError as exc:
            for path, old in reversed(written):
                _atomic_write(path, old)
            for destination, source_path in reversed(moved):
                destination.rename(source_path)
            raise HTTPException(500, "フォルダ名を変更できませんでした") from exc
    return Folder(name=body.name)


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
