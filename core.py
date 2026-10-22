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
    reseed: int = 0   # >0: narrate again with a different random seed (repair a bad passage)


def load_text_fixes(title: str) -> dict:
    """Per-book passage repairs in audiobooks/_text-fixes/<title>.json.

    {"replace": {text_key: new_text ('' drops the passage)}, "reseed": {text_key: n}}
    Positions (and so all other saved passages) stay unchanged.
    """
    try:
        data = json.loads((LIBRARY / "_text-fixes" / f"{title}.json").read_text(encoding="utf-8"))
        return {"replace": dict(data.get("replace", {})), "reseed": {k: int(v) for k, v in data.get("reseed", {}).items()}}
    except (OSError, ValueError, AttributeError, TypeError):
        return {"replace": {}, "reseed": {}}


def clean_text(text: str) -> str:
    """Make PDF/EPUB text suitable for speech without stripping punctuation."""
    text = text.replace("\u00ad", "").replace("\ufeff", "")
    text = re.sub(r"(?<=\w)-[ \t]*\n[ \t]*(?=\w)", "", text)
    text = re.sub(r"(?m)^[ \t]*\d{1,4}[ \t]*$", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)
    return re.sub(r"\s+", " ", text).strip()


TEXT_VERSION = 2   # 1 = original extraction; 2 = also drops URL-only lines and running headers
_URL_ONLY = re.compile(r"^\s*(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,24}(?:/\S*)?\s*$", re.I)


def is_noise_line(line: str) -> bool:
    """A line that is only a web address (download-site watermarks, page footers)."""
    return bool(_URL_ONLY.match(line)) and not re.fullmatch(r"\s*[\d.,]+\s*", line)


def extract_document(path: Path, first_page: int = 1, last_page: Optional[int] = None,
                     pdf_group_pages: int = 10, text_version: int = TEXT_VERSION) -> list[Chapter]:
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

            raw_pages = {i: doc[i - 1].get_text("text", sort=True) for i in range(start, end + 1)}
            if text_version >= 2:
                # Running headers/footers: the same short line on at least 30% of (and 8+) pages.
                from collections import Counter
                counts = Counter(line.strip() for text in raw_pages.values()
                                 for line in set(text.splitlines()) if 0 < len(line.strip()) <= 80)
                limit = max(8, int(0.3 * len(raw_pages)))
                repeated = {line for line, n in counts.items() if n >= limit and not line.isdigit()}
                raw_pages = {i: "\n".join(line for line in text.splitlines()
                                          if line.strip() not in repeated and not is_noise_line(line))
                             for i, text in raw_pages.items()}

            def add_chapter(title: str, page_start: int, page_end: int) -> None:
                texts = [clean_text(raw_pages[i]) for i in range(page_start, page_end + 1)]
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
            strings = [x for x in soup.stripped_strings if text_version < 2 or not is_noise_line(x)]
            text = clean_text(" ".join(strings))
            if len(text) >= 30:
                chapters.append(Chapter(title[:90], text))
        if not chapters:
            raise ValueError("No readable text found in this EPUB.")
        return chapters
    if suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if text_version >= 2:
            text = "\n".join(line for line in text.splitlines() if not is_noise_line(line))
        sections = re.split(r"(?im)(?=^\s*(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b[^\n]*$)", text)
        chapters = []
        for section in sections:
            if len(clean_text(section)) <= 20:
                continue
            first = section.strip().splitlines()[0].strip()
            heading = re.match(r"(?i)(?:chapter|part)\s+(?:\d+|[ivxlcdm]+)\b", first)
            # Use the chapter heading as its title; numbering stays "Section N" otherwise.
            chapters.append(Chapter(first[:90] if heading else f"Section {len(chapters) + 1}", clean_text(section)))
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


def voice_key(model: str, speaker: str, instruction: str, ref_path: Optional[Path], seed: int) -> str:
    """Settings that change the narration of a passage (not chapter selection or passage position)."""
    data = {"model": model, "speaker": speaker, "instruct": instruction if model == "qwen17" else "",
            "voice": fingerprint(ref_path) if ref_path and Path(ref_path).is_file() else None, "seed": int(seed)}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def text_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


def _usable_wav(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 256
    except OSError:
        return False


def _folder_passages(other: Path, wanted_key: str) -> dict[str, Path]:
    """Map text-key -> saved WAV for another job folder narrated with identical voice settings."""
    found: dict[str, Path] = {}
    try:
        index = json.loads((other / "passages.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = None
    if isinstance(index, dict) and index.get("voice_key"):
        if index["voice_key"] != wanted_key:
            return found
        for name, key in index.get("passages", {}).items():
            wav = other / "chunks" / Path(name).name
            if _usable_wav(wav):
                found.setdefault(key, wav)
        return found
    # Folders created by older versions: rebuild the mapping from book.json + tasks.json.
    try:
        book = json.loads((other / "book.json").read_text(encoding="utf-8"))
        tasks = json.loads((other / "tasks.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return found
    ref = None
    if tasks.get("reference"):
        ref = other / Path(str(tasks["reference"]).replace("\\", "/")).name
    key = voice_key(book.get("model", ""), book.get("speaker", ""), tasks.get("instruction", ""),
                    ref, int(tasks.get("seed", 42)))
    if key != wanted_key:
        return found
    for item in tasks.get("tasks", []):
        wav = other / "chunks" / Path(str(item.get("wav", "")).replace("\\", "/")).name
        if item.get("text") and _usable_wav(wav):
            found.setdefault(text_key(item["text"]), wav)
    return found


def reuse_saved_passages(folder: Path, title: str, key: str, pieces: list[Piece]) -> int:
    """Copy identical, already narrated passages from other selections of the same book.

    Changing the chapter selection or PDF section size creates a new job folder; without this,
    every passage would be generated again even though the same text was already narrated.
    """
    missing = [p for p in pieces if not _usable_wav(p.wav) and not p.reseed]
    if not missing:
        return 0
    available: dict[str, Path] = {}
    for other in LIBRARY.glob(f"{title}-*"):
        if other.is_dir() and other.resolve() != folder.resolve():
            for k, wav in _folder_passages(other, key).items():
                available.setdefault(k, wav)
    reused = 0
    for piece in missing:
        source = available.get(text_key(piece.text))
        if source is None:
            continue
        temporary = piece.wav.with_name(piece.wav.stem + ".copy.wav")
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(piece.wav)
            reused += 1
        except OSError:
            temporary.unlink(missing_ok=True)
    return reused


def discard_mismatched_passages(folder: Path, pieces: list[Piece]) -> int:
    """Delete saved WAVs whose recorded text differs from the passage now at that position.

    Passages are stored by position (000123.wav). If text extraction ever changes, position 123
    can hold different words; without this check the old audio would be exported silently.
    """
    recorded: dict[str, str] = {}
    try:
        recorded = json.loads((folder / "passages.json").read_text(encoding="utf-8")).get("passages", {})
    except (OSError, ValueError, AttributeError):
        try:
            for item in json.loads((folder / "tasks.json").read_text(encoding="utf-8")).get("tasks", []):
                name = Path(str(item.get("wav", "")).replace("\\", "/")).name
                if name and item.get("text"):
                    recorded[name] = text_key(item["text"])
        except (OSError, ValueError, AttributeError):
            return 0
    removed = 0
    for piece in pieces:
        old = recorded.get(piece.wav.name)
        if old and old != text_key(piece.text) and piece.wav.exists():
            piece.wav.unlink(missing_ok=True)
            removed += 1
    return removed


def plan_job(source: Path, model: str, speaker: str, instruction: str,
             ref_path: Optional[Path], first_page: int, last_page: int,
             group_size: int, chars: int, seed: int,
             selected_chapters: Optional[list[int]] = None) -> tuple[Path, list[Piece], str]:
    if not source.is_file():
        raise ValueError("Please upload a book first.")
    title = safe_title(source.name)
    selection = sorted({int(i) for i in selected_chapters}) if selected_chapters is not None else None
    # Unchanged on purpose: the folder key decides where existing narration is found.
    options = {"file": fingerprint(source), "model": model, "speaker": speaker,
               "instruct": instruction if model == "qwen17" else "",
               "voice": fingerprint(ref_path) if ref_path else None,
               "first_page": first_page, "last_page": last_page,
               "group_size": group_size, "chars": chars, "seed": seed,
               "selected_chapters": selection}
    if selection is None:
        chapters = extract_document(source, first_page, last_page or None, group_size)
        selection = list(range(len(chapters)))
        options["selected_chapters"] = selection
    key = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()[:12]
    folder = LIBRARY / f"{title}-{key}"
    # Folders narrated before text cleanup v2 keep the original extraction, so their saved
    # passages still line up with the text and nothing is narrated again.
    try:
        previous = json.loads((folder / "book.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    has_audio = (folder / "chunks").is_dir() and any((folder / "chunks").glob("*.wav"))
    version = int(previous.get("text_version", 1)) if previous and has_audio else TEXT_VERSION
    chapters = extract_document(source, first_page, last_page or None, group_size, text_version=version)
    if not selection or any(i < 0 or i >= len(chapters) for i in selection):
        raise ValueError("Select at least one valid chapter to narrate.")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chunks").mkdir(exist_ok=True)
    fixes = load_text_fixes(title)
    pieces = []
    index = 0
    for chapter_no in selection:
        chapter = chapters[chapter_no]
        for text in split_text(chapter.text, chars):
            index += 1   # positions never shift, even when a fix drops a passage
            key0 = text_key(text)
            if key0 in fixes["replace"]:
                text = " ".join(str(fixes["replace"][key0]).split())
                if not text:
                    continue
            pieces.append(Piece(f"{chapter_no + 1:02d} · {chapter.title}", text, index,
                                folder / "chunks" / f"{index:06d}.wav", fixes["reseed"].get(key0, 0)))
    if not pieces:
        raise ValueError("No narratable text was found in your selected pages.")
    manifest = {"title": title, "original": source.name, "model": model, "speaker": speaker,
                "chapters": len(selection), "total_chapters": len(chapters), "chunks": len(pieces), "key": key,
                "selected_chapters": selection, "text_version": version}
    (folder / "book.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if ref_path:
        saved_ref = folder / ("reference" + ref_path.suffix.lower())
        if not saved_ref.exists():
            shutil.copyfile(ref_path, saved_ref)
    discard_mismatched_passages(folder, pieces)
    vkey = voice_key(model, speaker, instruction, ref_path, seed)
    (folder / "passages.json").write_text(json.dumps(
        {"voice_key": vkey, "passages": {p.wav.name: text_key(p.text) for p in pieces}}, indent=1), encoding="utf-8")
    reuse_saved_passages(folder, title, vkey, pieces)
    return folder, pieces, title


def generate_tasks(folder: Path, pieces: list[Piece], model: str, speaker: str,
                   instruction: str, seed: int, reference: Optional[Path],
                   engine: str = "auto", batch_size: int = 0, name: str = "tasks.json") -> Path:
    payload = {"model": model, "speaker": speaker, "instruction": instruction,
               "seed": seed, "reference": str(reference) if reference else "",
               "engine": engine, "batch_size": int(batch_size or 0),
               "tasks": [{"index": p.index, "text": p.text, "wav": str(p.wav), "chapter": p.chapter}
                         for p in pieces if not _usable_wav(p.wav)]}
    path = folder / name
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
             cover: Optional[Path] = None, **options) -> Path:  # options may include author/comment tags
    """Stream export with optional speed, pauses, progress and cancellation."""
    from export_audio import export_audio
    return export_audio(folder, pieces, destination, title, cover, **options)


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
