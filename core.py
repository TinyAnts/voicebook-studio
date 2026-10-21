"""Document extraction, resumable jobs and audiobook assembly (no AI libraries)."""
from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import shutil
import subprocess
import wave
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / "audiobooks"
LIBRARY.mkdir(exist_ok=True)


@dataclass
class Chapter:
    title: str
    text: str


@dataclass
class Piece:
    chapter: str
    text: str
    index: int
    wav: Path


def clean_text(text: str) -> str:
    """Make PDF/EPUB text suitable for speech without stripping punctuation."""
    text = text.replace("\u00ad", "").replace("\ufeff", "")
    text = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "", text)
    text = re.sub(r"(?m)^[ \t]*\d{1,4}[ \t]*$", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_document(path: Path, first_page: int = 1, last_page: Optional[int] = None,
                     pdf_group_pages: int = 10) -> list[Chapter]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pymupdf
        chapters = []
        with pymupdf.open(str(path)) as doc:
            n = len(doc)
            start = int(first_page)
            end = min(n, int(last_page or n))
            if not (1 <= start <= end <= n):
                raise ValueError(f"Invalid page range: document contains {n} pages.")

            def add_chapter(title: str, page_start: int, page_end: int) -> None:
                texts = [clean_text(doc[i - 1].get_text("text", sort=True))
                         for i in range(page_start, page_end + 1)]
                text = " ".join(t for t in texts if t)
                if text.strip():
                    chapters.append(Chapter(title[:110], text))

            # Digitally published PDFs often include real chapter bookmarks.
            # Use those for true audiobook chapter boundaries when possible.
            bookmarks = doc.get_toc(simple=True)
            levels = {}
            for level, heading, page in bookmarks:
                if isinstance(page, int) and start <= page <= end and heading.strip():
                    levels.setdefault(level, []).append((page, heading.strip()))
            root_chapters = levels.get(1, [])
            second_level = levels.get(2, [])
            if len(root_chapters) <= 3 and len(second_level) >= 5:
                chosen = second_level
            elif len(root_chapters) >= 2:
                chosen = root_chapters
            elif len(second_level) >= 2:
                chosen = second_level
            else:
                chosen = []
            points = []
            for page, heading in sorted(chosen):
                if not points or points[-1][0] != page:
                    points.append((page, heading))
            if len(points) >= 2:
                if start < points[0][0]:
                    add_chapter("Front matter", start, points[0][0] - 1)
                for i, (page, heading) in enumerate(points):
                    stop = (points[i + 1][0] - 1) if i + 1 < len(points) else end
                    add_chapter(heading, page, stop)
            else:
                # Scanned/unbookmarked or arbitrary PDFs: group pages into
                # navigable sections, with clear labels (not fake chapter names).
                for group_start in range(start, end + 1, pdf_group_pages):
                    group_end = min(end, group_start + pdf_group_pages - 1)
                    title = (f"Pages {group_start}-{group_end}" if group_start != group_end
                             else f"Page {group_start}")
                    add_chapter(title, group_start, group_end)
        if not chapters:
            raise ValueError("No selectable text found. Scanned PDFs require OCR first.")
        return chapters
    if suffix == ".epub":
        try:
            from ebooklib import epub
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError("EPUB support needs ebooklib and beautifulsoup4. Run setup again.") from exc
        book = epub.read_epub(str(path))
        chapters = []
        for item_id, _linear in book.spine:
            item = book.get_item_with_id(item_id)
            if not item or not hasattr(item, "get_content"):
                continue
            soup = BeautifulSoup(item.get_content(), "html.parser")
            for element in soup(["script", "style", "nav", "svg"]):
                element.decompose()
            heading = soup.find(["h1", "h2", "h3"])
            title = heading.get_text(" ", strip=True) if heading else f"Section {len(chapters) + 1}"
            text = clean_text(soup.get_text(" ", strip=True))
            if len(text) >= 30:
                chapters.append(Chapter(title[:90], text))
        if not chapters:
            raise ValueError("No readable text found in this EPUB.")
        return chapters
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        sections = re.split(r"(?im)(?=^\s*(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b[^\n]*$)", text)
        chapters = [Chapter(f"Section {i}", clean_text(section)) for i, section in enumerate(sections, 1)
                    if len(clean_text(section)) > 20]
        if not chapters:
            raise ValueError("This text file has no usable text.")
        return chapters
    raise ValueError("Please upload a PDF, EPUB, TXT or MD file.")




def _epub_cover_bytes(source: Path) -> Optional[bytes]:
    """Find cover artwork from EPUB 2 metadata or EPUB 3 cover-image property.

    EPUB manifest paths are relative to the OPF directory, not the archive root.
    Keep extraction in memory and reject unexpectedly large image assets.
    """
    with zipfile.ZipFile(source) as archive:
        rootfile = ET.fromstring(archive.read("META-INF/container.xml"))
        package_path = None
        for element in rootfile.iter():
            if element.tag.rsplit("}", 1)[-1] == "rootfile":
                package_path = element.attrib.get("full-path")
                if package_path:
                    break
        if not package_path:
            return None
        package = ET.fromstring(archive.read(package_path))
        item_by_id: dict[str, tuple[str, str, str]] = {}
        cover_id = None
        cover_items: list[str] = []
        for element in package.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "meta" and element.attrib.get("name", "").lower() == "cover":
                cover_id = element.attrib.get("content")
            elif tag == "item":
                ident = element.attrib.get("id")
                href = element.attrib.get("href", "")
                mime = element.attrib.get("media-type", "")
                props = element.attrib.get("properties", "")
                if ident:
                    item_by_id[ident] = (href, mime, props)
                if "cover-image" in props.split():
                    cover_items.append(ident or "")
        names = []
        for ident in [*cover_items, cover_id]:
            if ident and ident in item_by_id:
                names.append(item_by_id[ident])
        # Some badly authored EPUBs omit explicit metadata.
        for ident, values in item_by_id.items():
            href, mime, _props = values
            if mime.startswith("image/") and "cover" in posixpath.basename(href).lower():
                names.append(values)
        opf_dir = posixpath.dirname(package_path)
        for href, mime, _props in names:
            if not mime.startswith("image/") or not href:
                continue
            asset_path = posixpath.normpath(posixpath.join(opf_dir, unquote(href.split("#")[0])))
            if asset_path.startswith("../") or asset_path.startswith("/"):
                continue
            try:
                info = archive.getinfo(asset_path)
            except KeyError:
                continue
            if info.file_size > 18 * 1024 * 1024:
                continue
            return archive.read(info)
    return None


def extract_book_cover(source: Path, destination: Path, override: Optional[Path] = None) -> Optional[Path]:
    """Create a normalized, square JPEG cover preserving the source artwork.

    Priority: user-provided image > EPUB embedded image > first PDF page.
    Returns None for a text document or a book without usable cover artwork.
    Pillow limits decompression bombs. This function never synthesizes fake cover art.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    image = None
    try:
        if override:
            if override.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise ValueError("Cover override must be JPG, PNG or WEBP.")
            with Image.open(override) as original:
                image = original.copy()
        elif source.suffix.lower() == ".pdf":
            import pymupdf
            with pymupdf.open(source) as doc:
                if not len(doc):
                    return None
                page = doc[0]
                # Keep a readable cover but avoid huge bitmaps from A4 PDFs.
                scale = min(2.5, 1400 / max(page.rect.width, page.rect.height))
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png"))).copy()
        elif source.suffix.lower() == ".epub":
            data = _epub_cover_bytes(source)
            if data:
                with Image.open(io.BytesIO(data)) as original:
                    image = original.copy()
        if image is None:
            return None
        image = ImageOps.exif_transpose(image).convert("RGB")
        # Keep portrait cover proportions, with unobtrusive edges for square album art.
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        background = Image.new("RGB", (1200, 1200), (21, 27, 39))
        left = (1200 - image.width) // 2
        top = (1200 - image.height) // 2
        background.paste(image, (left, top))
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        background.save(temporary, format="JPEG", quality=91, optimize=True, subsampling=0)
        temporary.replace(destination)
        return destination
    except (UnidentifiedImageError, OSError, ET.ParseError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        if override:
            raise ValueError(f"Cannot use cover image: {exc}") from exc
        return None


def save_book_cover(source: Path, folder: Path, override: Optional[Path] = None) -> Optional[Path]:
    """Write cover into the persistent job folder; leave cached narration unchanged."""
    return extract_book_cover(source, folder / "cover.jpg", override)


def split_text(text: str, max_chars: int = 320) -> list[str]:
    if not 120 <= max_chars <= 1000:
        raise ValueError("Chunk length should be between 120 and 1000 characters.")
    sentences = re.split(r'(?<=[.!?])\s+(?=[\w"“‘\[(])', clean_text(text))
    out = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        # Long uninterrupted sentences are split at word boundaries.
        words = sentence.split()
        segments, segment = [], ""
        for word in words:
            if len(word) > max_chars:
                if segment:
                    segments.append(segment)
                    segment = ""
                segments.extend(word[i:i + max_chars] for i in range(0, len(word), max_chars))
            elif len(segment) + len(word) + bool(segment) <= max_chars:
                segment = (segment + " " + word).strip()
            else:
                segments.append(segment)
                segment = word
        if segment:
            segments.append(segment)
        for part in segments:
            if current and len(current) + len(part) + 1 > max_chars:
                out.append(current)
                current = ""
            current = (current + " " + part).strip()
    if current:
        out.append(current)
    return out


def safe_title(filename: str) -> str:
    base = Path(filename).stem
    base = re.sub(r"[^\w. -]+", "", base, flags=re.UNICODE)
    base = re.sub(r"\s+", "-", base).strip("-. ")
    return base[:70] or "audiobook"


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def plan_job(source: Path, model: str, speaker: str, instruction: str,
             ref_path: Optional[Path], first_page: int, last_page: int,
             group_size: int, chars: int, seed: int,
             selected_chapters: Optional[list[int]] = None) -> tuple[Path, list[Piece], str]:
    if not source.is_file():
        raise ValueError("Please upload a book first.")
    title = safe_title(source.name)
    chapters = extract_document(source, first_page, last_page or None, group_size)
    selection = sorted({int(i) for i in (selected_chapters or range(len(chapters)))})
    if not selection or any(i < 0 or i >= len(chapters) for i in selection):
        raise ValueError("Select at least one valid chapter to narrate.")
    options = {"file": fingerprint(source), "model": model, "speaker": speaker,
               "instruct": instruction if model == "qwen17" else "",
               "voice": fingerprint(ref_path) if ref_path else None,
               "first_page": first_page, "last_page": last_page,
               "group_size": group_size, "chars": chars, "seed": seed,
               "selected_chapters": selection}
    key = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()[:12]
    folder = LIBRARY / f"{title}-{key}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chunks").mkdir(exist_ok=True)
    pieces = []
    for chapter_no in selection:
        chapter = chapters[chapter_no]
        for text in split_text(chapter.text, chars):
            index = len(pieces) + 1
            pieces.append(Piece(f"{chapter_no + 1:02d} · {chapter.title}", text, index, folder / "chunks" / f"{index:06d}.wav"))
    if not pieces:
        raise ValueError("No narratable text was found in your selected pages.")
    manifest = {"title": title, "original": source.name, "model": model, "speaker": speaker,
                "chapters": len(selection), "chunks": len(pieces), "key": key,
                "selected_chapters": selection}
    (folder / "book.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if ref_path:
        saved_ref = folder / ("reference" + ref_path.suffix.lower())
        if not saved_ref.exists():
            shutil.copyfile(ref_path, saved_ref)
    return folder, pieces, title


def generate_tasks(folder: Path, pieces: list[Piece], model: str, speaker: str,
                   instruction: str, seed: int, reference: Optional[Path]) -> Path:
    payload = {"model": model, "speaker": speaker, "instruction": instruction,
               "seed": seed, "reference": str(reference) if reference else "",
               "tasks": [{"index": p.index, "text": p.text, "wav": str(p.wav)}
                         for p in pieces if not (p.wav.exists() and p.wav.stat().st_size > 256)]}
    path = folder / "tasks.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def get_duration(path: Path) -> float:
    # All supported backends produce standard WAVs; wave.info avoids loading sound into memory.
    import soundfile as sf
    with sf.SoundFile(str(path)) as fd:
        return len(fd) / fd.samplerate


def _ffconcat_path(path: Path) -> str:
    # Paths are generated and controlled by our application (no arbitrary file paths).
    return "'" + str(path.resolve()).replace("\\", "/").replace("'", "'\\''") + "'"


def ffmpeg_binary() -> str:
    """Prefer system FFmpeg, then the executable bundled with imageio-ffmpeg."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, FileNotFoundError) as exc:
        raise RuntimeError("FFmpeg is unavailable. Re-run install.bat to install bundled FFmpeg.") from exc


def assemble(folder: Path, pieces: list[Piece], destination: Path, title: str,
             cover: Optional[Path] = None) -> Path:
    """Use FFmpeg concat to avoid decoding a full book into RAM; include M4B chapters."""
    ffmpeg = ffmpeg_binary()
    if any(not p.wav.exists() for p in pieces):
        raise RuntimeError("Some audio chunks are not generated yet.")
    if not pieces:
        raise RuntimeError("Nothing to export.")
    list_file = folder / "ffconcat.txt"
    list_file.write_text("ffconcat version 1.0\n" + "".join(f"file {_ffconcat_path(p.wav)}\n" for p in pieces), encoding="utf-8")
    metadata = [";FFMETADATA1", f"title={title}", "artist=Voicebook Studio"]
    current_chapter = None
    last_start_ms = 0
    time_ms = 0
    chapter_markers = []
    for piece in pieces:
        if piece.chapter != current_chapter:
            if chapter_markers:
                chapter_markers[-1][2] = time_ms
            chapter_markers.append([piece.chapter, time_ms, time_ms])
            current_chapter = piece.chapter
        time_ms += round(get_duration(piece.wav) * 1000)
    if chapter_markers:
        chapter_markers[-1][2] = time_ms
    for i, (heading, start, end) in enumerate(chapter_markers):
        if end <= start:
            continue
        # FFmetadata special characters need escaping.
        heading = str(heading).replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#").replace("\n", " ")
        metadata.extend(["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={heading}"])
    meta_file = folder / "chapters.ffmeta"
    meta_file.write_text("\n".join(metadata) + "\n", encoding="utf-8")
    output = destination.with_name(destination.stem + ".partial" + destination.suffix)
    if output.exists():
        output.unlink()
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-safe", "0", "-f", "concat", "-i", str(list_file),
           "-f", "ffmetadata", "-i", str(meta_file)]
    cover = cover or (folder / "cover.jpg")
    with_cover = cover.is_file()
    if with_cover:
        cmd.extend(["-i", str(cover)])
    cmd.extend(["-map", "0:a:0"])
    if with_cover:
        cmd.extend(["-map", "2:v:0", "-c:v", "mjpeg", "-disposition:v:0", "attached_pic",
                    "-metadata:s:v:0", "title=Album cover",
                    "-metadata:s:v:0", "comment=Cover (front)"])
    cmd.extend(["-map_metadata", "1", "-map_chapters", "1", "-af", "loudnorm=I=-18:TP=-2:LRA=11"])
    if destination.suffix.lower() == ".m4b":
        cmd.extend(["-c:a", "aac", "-b:a", "128k", "-f", "ipod"])
    else:
        cmd.extend(["-c:a", "libmp3lame", "-q:a", "3", "-id3v2_version", "3", "-f", "mp3"])
    cmd.append(str(output))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("FFmpeg export failed: " + (result.stderr or "Unknown error")[-1500:])
    output.replace(destination)
    return destination


def recent_books() -> str:
    items = sorted(list(LIBRARY.glob("*/*.m4b")) + list(LIBRARY.glob("*/*.mp3")),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not items:
        return "No exported audiobooks yet. Your files will be saved in the `audiobooks` folder."
    lines = []
    for p in items[:10]:
        size = p.stat().st_size / (1024 * 1024)
        lines.append(f"- **{p.name.replace('_', ' ')}** · {size:,.1f} MB · `{p.parent.name}`")
    return "\n".join(lines)
