"""Voicebook Studio: local-first PDF/EPUB audiobook maker.

A lightweight Gradio frontend calls model-specific workers in isolated environments.
No third-party AI API, database, paid account or remote hosting is required.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import gradio as gr

from core import (
    LIBRARY, ROOT, assemble, extract_document, generate_tasks,
    get_duration, plan_job, recent_books, ffmpeg_binary,
    extract_book_cover, save_book_cover,
)

MODELS = {
    "Qwen3-TTS 1.7B — highest quality to try first": "qwen17",
    "Qwen3-TTS 0.6B — less GPU memory": "qwen06",
    "Chatterbox Multilingual V3 — custom voice": "chatter_v3",
    "Chatterbox Turbo — custom English voice": "chatter_turbo",
    "Kokoro-82M — very fast": "kokoro",
}
VOICES = {
    "qwen17": ["Aiden", "Ryan"],
    "qwen06": ["Aiden", "Ryan"],
    "chatter_v3": ["Reference recording"],
    "chatter_turbo": ["Reference recording"],
    "kokoro": ["af_heart", "af_bella", "af_sarah", "am_michael", "am_adam", "bf_emma", "bm_george"],
}
STYLES = {
    "Nonfiction — clear and warm":
        "Read in a natural, calm, warm professional nonfiction audiobook voice. "
        "Steady pace, subtle emphasis, clear diction, and comfortable pauses; no theatrics.",
    "Fiction — immersive storytelling":
        "Read like an engaging, emotionally nuanced fiction audiobook narrator. "
        "Natural pacing, vivid but restrained expression, consistent narrator identity.",
    "Calm bedtime listening":
        "Read slowly, gently and softly, with clear diction and a relaxed, soothing rhythm.",
}
DEMO_TEXT = (
    "The farmhouse stood at the edge of a quiet valley. By morning, the clouds "
    "had cleared, and the first light moved across the hills. There was work to be "
    "done, but for a moment, everything was still."
)
ACTIVE: dict[str, object] = {"process": None, "stop_requested": False}
ACTIVE_LOCK = threading.Lock()


def python_for(model: str) -> Path:
    env = "qwen" if model.startswith("qwen") else "chatterbox" if model.startswith("chatter") else "kokoro"
    root = ROOT / (".venv-" + env)
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise gr.Error(
            f"{env} is not installed yet. Run install.bat (for Qwen) or "
            f"install-chatterbox.bat / install-kokoro.bat, then retry."
        )
    return python


def update_model(label: str):
    model = MODELS[label]
    values = VOICES[model]
    is_qwen = model.startswith("qwen")
    chatter = model.startswith("chatter")
    note = (
        "**Chatterbox requires a clean 6–15 second recording** (WAV, MP3 or FLAC). "
        "Use your own voice or a voice you have permission to clone. "
        "The recording is reused across chapters for consistent narration."
        if chatter else
        "**Qwen:** audition Aiden and Ryan before converting a book. "
        "The free pretrained voices run entirely on your computer."
        if is_qwen else
        "**Kokoro:** choose any of the listed predefined voices; free and fast."
    )
    return (
        gr.update(choices=values, value=values[0]),
        gr.update(visible=chatter),
        gr.update(visible=is_qwen),
        note,
    )


def set_style(choice: str):
    return STYLES[choice]


def inspect_chapters(book, first_page, last_page, chapter_pages):
    if not book:
        return gr.update(choices=[], value=[]), "Upload a book to see its chapters."
    try:
        chapters = extract_document(
            Path(book), int(first_page), int(last_page) or None, int(chapter_pages)
        )
        choices = [(f"{i+1:02d} · {c.title} · {len(c.text):,} chars", str(i))
                   for i, c in enumerate(chapters)]
        return gr.update(choices=choices, value=[value for _name, value in choices]), (
            f"**{len(chapters)} sections available.** All selected by default. "
            "For EPUB these follow the book's internal sections; for PDF they are "
            "groups of pages. You can deselect any section."
        )
    except Exception as exc:
        return gr.update(choices=[], value=[]), f"**Unable to read document:** {exc}"




def cover_preview(book, override):
    """Display exactly the image that will be embedded in generated audio."""
    if not book and not override:
        return None, "Upload a book to preview its cover."
    if not book:
        return None, "Upload a book to accompany your selected cover image."
    source = Path(book)
    uploaded = Path(override) if override else None
    try:
        stamp = f"{source.resolve()}:{source.stat().st_mtime_ns}:{source.stat().st_size}"
        if uploaded:
            stamp += f":{uploaded.resolve()}:{uploaded.stat().st_mtime_ns}:{uploaded.stat().st_size}"
        digest = hashlib.sha256(stamp.encode("utf-8")).hexdigest()[:16]
        target = LIBRARY / "_cover-previews" / f"{digest}.jpg"
        result = target if target.is_file() else extract_book_cover(source, target, uploaded)
        if result:
            return str(result), (
                "**Your uploaded cover** — automatically embedded in the final M4B/MP3."
                if uploaded else "**Cover detected** — automatically embedded in the final M4B/MP3."
            )
        return None, "No embedded cover found. Upload a JPG/PNG/WEBP to add artwork."
    except Exception as exc:
        return None, f"**Cover preview failed:** {exc}"


def samples() -> list[tuple[str, str]]:
    entries = []
    for file in LIBRARY.glob("*/preview.mp3"):
        try:
            data = json.loads((file.parent / "book.json").read_text(encoding="utf-8"))
            title = f"{data['original']} · {data['model']} · {data['speaker']}"
        except (OSError, KeyError, ValueError):
            title = file.parent.name
        entries.append((title, str(file)))
    entries.sort(key=lambda p: Path(p[1]).stat().st_mtime, reverse=True)
    return entries[:50]


def completed_books() -> list[tuple[str, str]]:
    entries = []
    for ext in ("m4b", "mp3"):
        for path in LIBRARY.glob(f"*/*.{ext}"):
            if path.name in {"preview.mp3", "listening-sample.mp3"}:
                continue
            entries.append((f"{path.stem} · {path.stat().st_size/(1024*1024):.1f} MB", str(path)))
    return sorted(entries, key=lambda it: Path(it[1]).stat().st_mtime, reverse=True)[:50]


def select_saved_preview(path):
    return path if path and Path(path).is_file() else None


def stop_job():
    with ACTIVE_LOCK:
        proc = ACTIVE.get("process")
        if isinstance(proc, subprocess.Popen) and proc.poll() is None:
            ACTIVE["stop_requested"] = True
            proc.terminate()
            return "**Stopped.** Completed passages are saved; run the same job again to resume."
    return "No generation is running."


def run_generation(book, cover_file, selected_chapters, model_label, voice, reference,
                   first_page, last_page, chapter_pages, chunk_chars,
                   instructions, seed, output_format, audition_text,
                   audition_from_book, preview, progress=gr.Progress()):
    """Stream progress and return an audible clip plus a downloadable file."""
    yield "Checking your settings…", None, None, recent_books(), gr.update(choices=samples())
    model = MODELS[model_label]
    if model.startswith("chatter") and not reference:
        raise gr.Error("Chatterbox needs a 6–15 second narrator recording before preview or generation.")
    try:
        ffmpeg_binary()
    except RuntimeError as exc:
        raise gr.Error(str(exc)) from exc
    py = python_for(model)

    # Audition a known passage, independent of the uploaded book, by default.
    # An audition based on a book takes only its first selected 320-character chunk.
    if preview and not audition_from_book:
        excerpt = (audition_text or DEMO_TEXT).strip()
        if len(excerpt) < 20:
            raise gr.Error("Please enter at least 20 characters for the audition sample.")
        digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()[:16]
        trial_dir = LIBRARY / "_audition-inputs"
        trial_dir.mkdir(exist_ok=True)
        source = trial_dir / f"voice-audition-{digest}.txt"
        source.write_text(excerpt, encoding="utf-8")
        selected = None
    else:
        if not book:
            raise gr.Error("Upload a PDF/EPUB first, or uncheck 'Use book excerpt' for a voice audition.")
        source = Path(book)
        if not selected_chapters:
            raise gr.Error("Choose at least one chapter in the chapter selector.")
        selected = [int(x) for x in selected_chapters]

    ref = Path(reference) if reference and model.startswith("chatter") else None
    try:
        folder, all_pieces, title = plan_job(
            source, model, voice, instructions, ref,
            int(first_page) if source.suffix.lower() == ".pdf" else 1,
            int(last_page) if source.suffix.lower() == ".pdf" else 0,
            int(chapter_pages), int(chunk_chars), int(seed), selected,
        )
    except Exception as exc:
        raise gr.Error(str(exc)) from exc

    if source.suffix.lower() in {".pdf", ".epub"}:
        try:
            save_book_cover(source, folder, Path(cover_file) if cover_file else None)
        except Exception as exc:
            raise gr.Error(f"Cannot embed selected cover: {exc}") from exc
    elif cover_file:
        try:
            save_book_cover(source, folder, Path(cover_file))
        except Exception as exc:
            raise gr.Error(f"Cannot embed selected cover: {exc}") from exc

    pieces = all_pieces[:1] if preview else all_pieces
    already = sum(p.wav.is_file() and p.wav.stat().st_size > 256 for p in pieces)
    kind = "Voice audition" if preview else "Audiobook"
    yield (
        f"**{kind}:** {len(pieces)} passages, {already} already saved. "
        "Preparing voice model…"
    ), None, None, recent_books(), gr.update(choices=samples())

    # Copy references into the resumable book folder before launching a worker.
    if ref:
        ref = folder / ("reference" + ref.suffix.lower())
    tasks_file = generate_tasks(folder, pieces, model, voice, instructions, int(seed), ref)
    outstanding = len(json.loads(tasks_file.read_text(encoding="utf-8"))["tasks"])
    if outstanding:
        log_path = folder / "worker.log"
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [str(py), "-u", str(ROOT / "worker.py"), "--tasks", str(tasks_file)],
                cwd=str(ROOT), stdout=subprocess.PIPE, stderr=log,
                encoding="utf-8", errors="replace", bufsize=1, text=True,
            )
            with ACTIVE_LOCK:
                ACTIVE["process"] = proc
                ACTIVE["stop_requested"] = False
            error = None
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    if not raw.startswith("VOICEBOOK_EVENT:"):
                        continue
                    try:
                        msg = json.loads(raw[len("VOICEBOOK_EVENT:"):])
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "error":
                        error = msg.get("message")
                    elif msg.get("type") == "status":
                        yield f"**{kind}:** {msg['message']}", None, None, recent_books(), gr.update(choices=samples())
                    elif msg.get("type") == "chunk":
                        finished = already + int(msg.get("done", 0))
                        progress(min(1, finished / len(pieces)), desc=f"Passage {finished} of {len(pieces)}")
                        yield (f"**{kind}:** {finished}/{len(pieces)} passages. "
                               "Progress is saved automatically."), None, None, recent_books(), gr.update(choices=samples())
                code = proc.wait()
                if code:
                    with ACTIVE_LOCK:
                        stopped = ACTIVE.get("stop_requested", False)
                    if stopped:
                        yield "Stopped — generated passages remain saved for resuming.", None, None, recent_books(), gr.update(choices=samples())
                        return
                    tail = log_path.read_text(encoding="utf-8", errors="replace")[-1400:]
                    raise gr.Error(f"Generation interrupted: {error or tail or 'unknown error'}. "
                                   "Run it again to reuse completed passages. "
                                   "If GPU memory is insufficient, try Qwen 0.6B.")
            finally:
                with ACTIVE_LOCK:
                    if ACTIVE.get("process") is proc:
                        ACTIVE["process"] = None
                        ACTIVE["stop_requested"] = False
                if proc.poll() is None:
                    proc.terminate()

    if any(not p.wav.is_file() for p in pieces):
        raise gr.Error("Audio is incomplete. Run again to resume.")
    yield "Encoding audio and chapter markers…", None, None, recent_books(), gr.update(choices=samples())
    extension = "mp3" if preview else output_format.lower()
    dest = folder / ("preview.mp3" if preview else f"{title}-{model}.{extension}")
    try:
        assemble(folder, pieces, dest, title + (" — voice audition" if preview else ""))
        if preview:
            listening = dest
        else:
            listening = folder / "listening-sample.mp3"
            # Rebuild the sample whenever a different full-book output was created.
            assemble(folder, pieces[:min(3, len(pieces))], listening, title + " — excerpt")
        duration = sum(get_duration(p.wav) for p in pieces)
    except Exception as exc:
        raise gr.Error(f"Could not export audiobook: {exc}") from exc
    progress(1, desc="Complete")
    detail = "Listen above, or compare it with saved auditions below." if preview else (
        "Download the complete file, or open the output folder. "
        "M4B includes chapter markers; MP3 is a single file."
    )
    yield (
        f"✅ **{kind} ready** · {duration / 60:.1f} minutes · {detail} "
        f"Saved in `{dest.parent}`"
    ), str(listening), str(dest), recent_books(), gr.update(choices=samples())


def audition(*args):
    yield from run_generation(*args, True)


def generate_book(*args):
    yield from run_generation(*args, False)


CSS = """
.gradio-container {max-width: 1150px !important; margin: auto !important;}
#hero {background: linear-gradient(125deg,#12253e,#205f8e);
       padding:24px 30px;border-radius:18px;margin:4px 0 12px;color:#fff;}
#hero h1 {color:#fff;font-size:30px;margin:0 0 5px;}
#hero p {color:#d8ebfd;margin:0;}
"""

with gr.Blocks(title="Voicebook Studio | Free AI Audiobooks") as demo:
    gr.HTML("""<div id="hero"><h1>🎧 Voicebook Studio</h1>
    <p>Turn long PDFs and EPUBs into narrated audiobooks. Choose chapters, audition voices, listen and download.</p></div>""")
    with gr.Row():
        with gr.Column(scale=6):
            gr.Markdown("### 1 · Upload a book")
            book = gr.File(label="PDF, EPUB, TXT or MD", file_types=[".pdf", ".epub", ".txt", ".md"], type="filepath")
            with gr.Accordion("Cover artwork (automatically detected)", open=False):
                cover_file = gr.File(
                    label="Optional: replace book cover with your own JPG / PNG / WEBP",
                    file_types=[".jpg", ".jpeg", ".png", ".webp"], type="filepath",
                )
                gr.Markdown("EPUB: uses the embedded cover. PDF: uses the first page. Upload an image here to override either one. Embedded in M4B **and** MP3.")
            with gr.Accordion("Choose chapters", open=True):
                chapters = gr.CheckboxGroup(label="Chapters / sections", choices=[], value=[])
                chapter_info = gr.Markdown("Upload a book to see available sections.")
            gr.Markdown("### 2 · Pick a narrator")
            model_label = gr.Dropdown(choices=list(MODELS), value=list(MODELS)[0], label="Free local voice model")
            voice = gr.Dropdown(choices=VOICES["qwen17"], value="Aiden", label="Narrator")
            model_help = gr.Markdown("**Qwen:** Aiden and Ryan are English narrator voices. Try both!")
            reference = gr.File(label="Your authorized 6–15 second narrator voice recording (Chatterbox)",
                                file_types=[".wav", ".mp3", ".flac"], type="filepath", visible=False)
            with gr.Accordion("Narration tone", open=False) as tone_panel:
                style = gr.Dropdown(choices=list(STYLES), value=list(STYLES)[0], label="Storytelling style")
                instructions = gr.Textbox(value=STYLES[list(STYLES)[0]], lines=3,
                                          label="Instructions for Qwen 1.7B (optional to edit)")
            gr.Markdown("### 3 · Audition the voice")
            audition_text = gr.Textbox(value=DEMO_TEXT, lines=3, label="Short passage to hear",
                                      info="Edit this passage to test difficult names or a scene from your book.")
            audition_from_book = gr.Checkbox(label="Use the beginning of the first selected chapter instead", value=False)
            audition_button = gr.Button("▶ Generate voice preview", variant="secondary")
            gr.Markdown("### 4 · Create your audiobook")
            with gr.Row():
                go_button = gr.Button("✨ Generate selected chapters", variant="primary", scale=3)
                stop_button = gr.Button("⏹ Stop", variant="stop", scale=1)
        with gr.Column(scale=5):
            gr.Markdown("### Cover artwork")
            cover_image = gr.Image(label="Audiobook cover preview", type="filepath", interactive=False, height=255)
            cover_info = gr.Markdown("Upload a book to preview its cover.")
            gr.Markdown("### Listen and download")
            status = gr.Markdown("Choose a narrator and click **Generate voice preview** to hear it.")
            audio = gr.Audio(label="Play voice audition / book excerpt", type="filepath", interactive=False)
            output = gr.File(label="Download MP3 or chapter-marked M4B")
            with gr.Accordion("Advanced book settings", open=False):
                first_page = gr.Number(value=1, precision=0, minimum=1, label="First PDF page")
                last_page = gr.Number(value=0, precision=0, minimum=0, label="Last PDF page (0 means end)")
                chapter_pages = gr.Slider(1, 30, value=10, step=1, label="PDF section size, pages")
                chunk_chars = gr.Slider(180, 500, value=320, step=20,
                                        label="Narration chunk size (smaller may be more reliable)")
                seed = gr.Number(value=42, precision=0, label="Random seed")
                output_format = gr.Radio(["M4B", "MP3"], value="M4B", label="Export format")
            gr.Markdown("### Compare previous voice auditions")
            saved = gr.Dropdown(choices=samples(), label="Previously generated samples", value=None)
            saved_player = gr.Audio(label="Play selected earlier voice", type="filepath", interactive=False)
            gr.Markdown("### Your saved library")
            library = gr.Markdown(recent_books())
            saved_book = gr.Dropdown(choices=completed_books(), label="Previously completed audiobooks")
            saved_download = gr.File(label="Download a saved audiobook")
            refresh = gr.Button("↻ Refresh", size="sm")
            gr.Markdown("*Everything is processed locally. Completed passages are cached so interrupted multi-hour books can resume. Scanned PDFs must be OCR-converted first.*")

    model_label.change(update_model, model_label, [voice, reference, tone_panel, model_help])
    style.change(set_style, style, instructions)
    book.change(inspect_chapters, [book, first_page, last_page, chapter_pages], [chapters, chapter_info])
    book.change(cover_preview, [book, cover_file], [cover_image, cover_info])
    cover_file.change(cover_preview, [book, cover_file], [cover_image, cover_info])
    for setting in [first_page, last_page, chapter_pages]:
        setting.change(inspect_chapters, [book, first_page, last_page, chapter_pages], [chapters, chapter_info])
    saved.change(select_saved_preview, saved, saved_player)
    saved_book.change(select_saved_preview, saved_book, saved_download)
    args = [book, cover_file, chapters, model_label, voice, reference, first_page, last_page,
            chapter_pages, chunk_chars, instructions, seed, output_format,
            audition_text, audition_from_book]
    outs = [status, audio, output, library, saved]
    audition_event = audition_button.click(audition, args, outs, concurrency_id="gpu", concurrency_limit=1)
    book_event = go_button.click(generate_book, args, outs, concurrency_id="gpu", concurrency_limit=1)
    stop_button.click(stop_job, outputs=status, cancels=[audition_event, book_event], queue=False)
    book_event.then(lambda: gr.update(choices=completed_books()), outputs=saved_book)
    refresh.click(
        lambda: (recent_books(), gr.update(choices=samples()), gr.update(choices=completed_books())),
        outputs=[library, saved, saved_book],
    )

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=7860,
        inbrowser=True, show_error=True, max_file_size="100mb",
        allowed_paths=[str(LIBRARY)], theme=gr.themes.Soft(), css=CSS,
    )
