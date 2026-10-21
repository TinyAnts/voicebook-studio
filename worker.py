"""Isolated speech model worker. Reads tasks JSON, writes WAVs and tagged JSON progress.

Run in the corresponding .venv-qwen, .venv-chatterbox or .venv-kokoro.
This separation is necessary: Qwen and Chatterbox pin incompatible Transformers versions.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

EVENT_LOCK = threading.Lock()

def event(**kwargs):
    with EVENT_LOCK:
        print("VOICEBOOK_EVENT:" + json.dumps(kwargs), flush=True)


def heartbeat(stop):
    while not stop.wait(5):
        event(type="heartbeat")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    args = ap.parse_args()
    event(type="status", stage="loading", message="Starting the speech engine and checking your hardware…")
    import numpy as np
    import soundfile as sf
    import torch

    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    model_id = tasks["model"]
    speaker = tasks.get("speaker", "Aiden")
    reference = tasks.get("reference") or None
    instruct = tasks.get("instruction") or ""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    event(type="device", device=torch.cuda.get_device_name(0) if device == "cuda" else "CPU",
          cuda=device == "cuda", vram_total_gb=(torch.cuda.get_device_properties(0).total_memory / 1024**3 if device == "cuda" else None))
    event(type="status", stage="loading", message=f"Loading {model_id} on {device}. Missing model files download automatically; download progress appears in the activity log.")
    if model_id in {"qwen17", "qwen06"}:
        from qwen_tts import Qwen3TTSModel
        repo = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice" if model_id == "qwen17" else "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
        model = Qwen3TTSModel.from_pretrained(
            repo, device_map="cuda:0" if device == "cuda" else "cpu",
            dtype=torch.bfloat16 if device == "cuda" else torch.float32,
            attn_implementation="sdpa")

        def speak(text):
            with torch.inference_mode():
                voice_args = {"text": text, "language": "English", "speaker": speaker}
                if model_id == "qwen17":
                    voice_args["instruct"] = instruct
                wavs, sr = model.generate_custom_voice(**voice_args)
            return np.asarray(wavs[0]).reshape(-1), sr

    elif model_id in {"chatter_v3", "chatter_turbo"}:
        if model_id == "chatter_v3":
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
            if not reference:
                raise ValueError("Provide an authorized narrator reference audio recording.")
            with torch.inference_mode():
                model.prepare_conditionals(reference)
            def speak(text):
                with torch.inference_mode():
                    audio = model.generate(text, language_id="en", temperature=0.7)
                return audio.detach().cpu().numpy().reshape(-1), model.sr
        else:
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            model = ChatterboxTurboTTS.from_pretrained(device=device)
            if not reference:
                raise ValueError("Provide an authorized narrator reference audio recording.")
            with torch.inference_mode():
                model.prepare_conditionals(reference)
            def speak(text):
                with torch.inference_mode():
                    audio = model.generate(text, temperature=0.7)
                return audio.detach().cpu().numpy().reshape(-1), model.sr
    elif model_id == "kokoro":
        from kokoro import KPipeline
        model = KPipeline(lang_code="a", device=device)
        def speak(text):
            segments = [np.asarray(audio, dtype=np.float32).reshape(-1)
                        for _graphemes, _phonemes, audio in model(text, voice=speaker, speed=1)]
            if not segments:
                raise RuntimeError("Kokoro returned no audio for this passage")
            return np.concatenate(segments), 24000
    else:
        raise ValueError("Unknown model selection: " + model_id)
    event(type="status", stage="narrating", message="Voice model ready. Narrating passages…")
    for n, item in enumerate(tasks["tasks"], 1):
        path = Path(item["wav"])
        path.parent.mkdir(parents=True, exist_ok=True)
        # Deterministic seed per passage; cached outputs are reused on retry.
        torch.manual_seed(int(tasks.get("seed", 42)) + int(item["index"]))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(tasks.get("seed", 42)) + int(item["index"]))
        event(type="chunk_start", index=item["index"], chapter=item.get("chapter", ""),
              text=item["text"], chars=len(item["text"]))
        started = time.monotonic()
        audio, sr = speak(item["text"])
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if not len(audio) or not np.all(np.isfinite(audio)):
            raise RuntimeError(f"Invalid audio generated for chunk {item['index']}")
        # Soft transitions and a short pause prevent harsh cuts between passages.
        fade = min(int(sr * 0.012), len(audio) // 4)
        if fade:
            audio[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
            audio[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        audio = np.concatenate([audio, np.zeros(int(sr * 0.21), dtype=np.float32)])
        tmp = path.with_name(path.stem + ".pending.wav")
        sf.write(str(tmp), audio, sr, subtype="PCM_16")
        tmp.replace(path)
        event(type="chunk", done=n, total=len(tasks["tasks"]), index=item["index"],
              chars=len(item["text"]), audio_seconds=len(audio)/sr,
              generation_seconds=time.monotonic()-started,
              vram_used_gb=(torch.cuda.memory_reserved()/1024**3 if device == "cuda" else None))
    event(type="done", message="All passages generated")


if __name__ == "__main__":
    stop_heartbeat = threading.Event()
    threading.Thread(target=heartbeat, args=(stop_heartbeat,), daemon=True).start()
    try:
        main()
    except Exception as exc:
        event(type="error", message=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        stop_heartbeat.set()
