"""Voicebook Studio Cloud Preview · Hugging Face ZeroGPU compatible.

Limited to one passage at a time because free accounts get ~5 GPU minutes/day.
Unlike the local app, this does not promise full-book generation or persistent storage.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import gradio as gr
import numpy as np
import soundfile as sf
import spaces
import torch
from qwen_tts import Qwen3TTSModel

MODEL_REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
# Load once at module scope in the ZeroGPU CUDA-emulation context, as recommended
# by https://huggingface.co/docs/hub/spaces-zerogpu.
model = Qwen3TTSModel.from_pretrained(
    MODEL_REPO,
    device_map="cuda:0",
    dtype=torch.bfloat16,
    attn_implementation="sdpa",
)


def prepare_passage(book: str | None, page: int, length: int) -> str:
    """Extract a short, editable text passage on CPU without spending GPU quota."""
    if not book:
        return ""
    path = Path(book)
    if path.suffix.lower() == ".pdf":
        import pymupdf
        with pymupdf.open(str(path)) as doc:
            if not (1 <= int(page) <= len(doc)):
                raise gr.Error(f"PDF contains {len(doc)} pages. Choose a valid page.")
            text = doc[int(page) - 1].get_text("text", sort=True)
    elif path.suffix.lower() in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    else:
        raise gr.Error("Cloud preview supports text-based PDF, TXT and MD. For EPUB use the local application.")
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise gr.Error("No selectable text on that page. Scanned PDFs require OCR first.")
    return text[:int(length)].rsplit(" ", 1)[0] or text[:int(length)]


@spaces.GPU(duration=120)
def generate_preview(text: str, speaker: str, instructions: str) -> tuple[str, str]:
    if not text or not text.strip():
        raise gr.Error("Extract a passage, or paste text, before generating.")
    if len(text) > 450:
        raise gr.Error("Cloud previews are limited to 450 characters to protect the free GPU quota.")
    if speaker not in {"Aiden", "Ryan"}:
        raise gr.Error("Invalid speaker selected.")
    with torch.inference_mode():
        waves, sample_rate = model.generate_custom_voice(
            text=text.strip(),
            language="English",
            speaker=speaker,
            instruct=instructions.strip()[:350],
        )
    wav = np.asarray(waves[0], dtype=np.float32).reshape(-1)
    if len(wav) == 0 or not np.all(np.isfinite(wav)):
        raise gr.Error("The model returned invalid audio. Try a shorter passage.")
    filename = Path(tempfile.mkdtemp(prefix="voicebook-preview-")) / "qwen-preview.wav"
    sf.write(str(filename), wav, int(sample_rate), subtype="PCM_16")
    return str(filename), str(filename)


with gr.Blocks(title="Voicebook Studio · Free Cloud Preview") as demo:
    gr.Markdown("# 🎧 Voicebook Studio — Cloud Preview")
    gr.Markdown(
        "Try **Qwen3-TTS 1.7B** on Hugging Face ZeroGPU without owning a GPU. "
        "Free accounts have a small daily GPU allowance, so **this app only generates short previews**. "
        "Use the local Voicebook Studio for complete PDF/EPUB audiobooks. "
        "Avoid uploading documents you are not authorized to share with this hosting provider."
    )
    with gr.Row():
        with gr.Column():
            book = gr.File(label="Optional text-based PDF, TXT or MD", file_types=[".pdf", ".txt", ".md"], type="filepath")
            with gr.Row():
                page = gr.Number(label="PDF page", value=1, minimum=1, precision=0)
                chars = gr.Slider(150, 450, value=350, step=25, label="Extract characters")
            extract = gr.Button("Extract passage from file")
            passage = gr.Textbox(label="Editable narration text (max 450 characters)", lines=5, max_lines=7,
                                 value="A good audiobook narrator doesn't simply read the words. They give every sentence space to breathe, without drawing attention away from the story itself.")
        with gr.Column():
            narrator = gr.Radio(["Aiden", "Ryan"], label="Narrator", value="Aiden")
            style = gr.Textbox(label="Delivery", value="Warm, professional audiobook narrator. Natural pauses, clear emphasis, and a steady pace.", lines=3)
            create = gr.Button("Generate free voice preview", variant="primary")
            audio = gr.Audio(label="Listen", type="filepath")
            file = gr.File(label="Download WAV")
    extract.click(prepare_passage, [book, page, chars], [passage])
    create.click(generate_preview, [passage, narrator, style], [audio, file], concurrency_limit=1)


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch(theme=gr.themes.Soft())
