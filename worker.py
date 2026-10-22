"""Isolated speech model worker. Reads tasks JSON, writes WAVs and tagged JSON progress.

Runs in .venv-qwen (official qwen-tts) or .venv-qwenfast (CUDA-graph engine); they pin different
Transformers versions, so they stay separate from the UI environment.

Speed design (Qwen):
* "fast"    - faster-qwen3-tts CUDA graphs (optional .venv-qwenfast install), one passage at a time.
* "batched" - official qwen-tts, several passages generated together on the GPU. The
              stock model is limited by per-step Python/kernel-launch overhead, so a batch
              of N passages costs little more than one passage.
* "single"  - one passage at a time (most compatible, slowest).
WAV writing runs on a separate thread so the GPU never waits for the disk.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
import zlib
from pathlib import Path

EVENT_LOCK = threading.Lock()
GB = 1024 ** 3


def event(**kwargs):
    with EVENT_LOCK:
        print("VOICEBOOK_EVENT:" + json.dumps(kwargs), flush=True)
    if kwargs.get("type") in ("device", "engine", "warning", "error"):
        # Also keep a readable record in worker.log for troubleshooting.
        print("[voicebook] " + ", ".join(f"{k}={v}" for k, v in kwargs.items() if k != "type"), file=sys.stderr, flush=True)


def heartbeat(stop):
    while not stop.wait(5):
        event(type="heartbeat")


REPOS = {
    "qwen17": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",      # Aiden, Ryan + style instructions
    "qwen17clone": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",        # library narrators / your recording
    "design17": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",    # create a narrator from a description
    "qwen06": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",      # older jobs only
    "qwen06clone": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",        # developer tests on CPU
}


def token_cap(texts):
    """Upper bound on 12 Hz codec frames. Stops runaway generations (the model default is 8192
    frames = 11 minutes of audio) from stalling a whole batch. ~2 frames per character is
    roughly 2.5x normal narration length, so real speech is never cut."""
    return min(4096, 96 + 2 * max(len(t) for t in texts))


def passage_seed(base, text):
    return (int(base) + zlib.crc32(text.encode("utf-8"))) % (2 ** 31)


class Writer:
    """Background WAV writer: fades, pads and saves while the GPU works on the next batch."""

    def __init__(self, total):
        self.q = queue.Queue(maxsize=64)
        self.total = total
        self.done = 0
        self.error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def put(self, item, audio, sr, generation_seconds, vram):
        if self.error:
            raise self.error
        self.q.put((item, audio, sr, generation_seconds, vram))

    def _run(self):
        import numpy as np
        import soundfile as sf
        while True:
            job = self.q.get()
            if job is None:
                return
            item, audio, sr, gen_s, vram = job
            try:
                audio = np.asarray(audio, dtype=np.float32).reshape(-1)
                fade = min(int(sr * 0.012), len(audio) // 4)
                if fade:
                    audio[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
                    audio[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
                if not item.get("raw"):
                    # Short pause prevents harsh cuts between passages.
                    audio = np.concatenate([audio, np.zeros(int(sr * 0.21), dtype=np.float32)])
                path = Path(item["wav"])
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_name(path.stem + ".pending.wav")
                sf.write(str(tmp), audio, sr, subtype="PCM_16")
                tmp.replace(path)
                self.done += 1
                event(type="chunk", done=self.done, total=self.total, index=item["index"],
                      chars=len(item["text"]), audio_seconds=len(audio) / sr,
                      generation_seconds=gen_s, vram_used_gb=vram)
            except Exception as exc:  # surfaced on the next put()/close()
                self.error = exc

    def close(self):
        self.q.put(None)
        self.thread.join()
        if self.error:
            raise self.error


def free_gpu(torch):
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def valid(audio):
    import numpy as np
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    return audio if len(audio) > 2400 and np.all(np.isfinite(audio)) else None


FISH_URL = os.environ.get("VOICEBOOK_FISH_URL", "http://127.0.0.1:8880")
# Installed by install-fish.ps1 outside OneDrive so the ~5 GB model is not uploaded to the cloud.
def _fish_dir():
    pointer = Path(__file__).resolve().parent / "fish-location.txt"   # written by install-fish.ps1
    if os.environ.get("VOICEBOOK_FISH_DIR"):
        return Path(os.environ["VOICEBOOK_FISH_DIR"])
    if pointer.is_file() and pointer.read_text(encoding="utf-8-sig").strip():
        return Path(pointer.read_text(encoding="utf-8-sig").strip())
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "VoicebookStudio" / "fish-speech"


FISH_DIR = _fish_dir()


def _http(method, path, body=None, timeout=30):
    import urllib.request
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(FISH_URL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def fish_ready():
    try:
        return _http("GET", "/v1/health", timeout=5)[0] == 200
    except Exception:
        return False


def fish_log_tail(lines=40):
    """Last lines of the Fish container log, so a crash shows its real cause in worker.log."""
    import subprocess
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        out = subprocess.run(["docker", "compose", "--profile", "server", "logs", "--no-color", "--tail", str(lines)],
                             cwd=str(FISH_DIR), capture_output=True, text=True, timeout=30, creationflags=flags)
        text = (out.stdout + out.stderr).strip()
        return "Fish server log (last lines):\n" + text[-4000:] if text else ""
    except Exception as exc:
        return f"(could not read the Fish log: {exc})"


FISH_OVERRIDE = """# Written by Voicebook Studio: keep compiled GPU kernels on disk so the slow one-time
# compile (10-20 min) is not repeated after Docker restarts.
services:
  server:
    environment:
      TORCHINDUCTOR_CACHE_DIR: /app/checkpoints/.cache/inductor
      TRITON_CACHE_DIR: /app/checkpoints/.cache/triton
"""


def fish_override():
    try:
        path = FISH_DIR / "compose.override.yml"
        if FISH_DIR.is_dir() and (not path.is_file() or path.read_text(encoding="utf-8") != FISH_OVERRIDE):
            path.write_text(FISH_OVERRIDE, encoding="utf-8")
    except OSError:
        pass


def fish_main(tasks):
    """Fish Audio S2 Pro (4-bit) through its local Docker server. No PyTorch in this process."""
    import base64
    import io
    import subprocess
    import soundfile as sf
    items = tasks["tasks"]
    event(type="device", device="Fish S2 Pro server (Docker, NVIDIA GPU)", cuda=True, vram_total_gb=None)
    if not fish_ready():
        compose = FISH_DIR / "compose.yml"
        fish_override()
        if not compose.is_file():
            raise RuntimeError("Fish S2 Pro is not installed. Double-click install-fish.bat first.")
        event(type="status", stage="loading",
              message="Starting the Fish S2 Pro server in Docker. The first start takes about 5 minutes…")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        result = subprocess.run(["docker", "compose", "--profile", "server", "up", "-d"], cwd=str(FISH_DIR),
                                capture_output=True, text=True, creationflags=flags)
        if result.returncode:
            raise RuntimeError("Could not start the Fish server. Is Docker Desktop running?\n" + result.stderr[-800:])
    deadline = time.monotonic() + 900
    while not fish_ready():
        if time.monotonic() > deadline:
            raise RuntimeError("The Fish server did not become ready in 15 minutes. Check Docker Desktop → fish-speech logs.")
        time.sleep(5)
    refs = {}

    def reference_for(it):
        path = it.get("reference") or tasks.get("reference")
        text = it.get("reference_text") or tasks.get("reference_text") or ""
        if not path or not text:
            raise RuntimeError("Fish S2 Pro needs a library narrator (with a reference recording).")
        if path not in refs:
            refs[path] = {"audio": base64.b64encode(Path(path).read_bytes()).decode("ascii"), "text": text}
        return refs[path]

    event(type="engine", engine="Fish S2 Pro 4-bit (Docker)", batch_size=1)
    event(type="status", stage="narrating",
          message="Fish S2 Pro is loading the model. The first run after a restart compiles GPU kernels "
                  "(10-20 min, one CPU core busy) — later passages are much faster.")
    first = True
    writer = Writer(len(items))
    base_seed = int(tasks.get("seed", 42))
    for it in items:
        event(type="chunk_start", index=it["index"], chapter=it.get("chapter", ""), text=it["text"],
              chars=len(it["text"]), batch=1)
        started = time.monotonic()
        body = {"text": it["text"], "references": [reference_for(it)], "format": "wav", "normalize": True,
                "seed": passage_seed(base_seed + 7919 * int(it.get("reseed") or 0), it["text"]),
                "use_memory_cache": "on", "max_new_tokens": min(2048, 120 + 4 * len(it["text"])),
                "temperature": 0.8, "top_p": 0.8, "repetition_penalty": 1.1}
        audio = None
        for attempt in range(2):
            try:
                status, data = _http("POST", "/v1/tts", body, timeout=3600 if first else 900)
                first = False
                audio, sr = sf.read(io.BytesIO(data), dtype="float32")
                audio = valid(audio if audio.ndim == 1 else audio.mean(axis=1))
                if audio is not None:
                    break
            except Exception as exc:
                if attempt:
                    raise RuntimeError(f"Fish server error on passage {it['index']}: {exc}\n"
                                       + fish_log_tail())
                time.sleep(10)  # the server may be restarting; give it a moment
                deadline = time.monotonic() + 600
                while not fish_ready() and time.monotonic() < deadline:
                    time.sleep(5)
            body["seed"] += 1
        if audio is None:
            raise RuntimeError(f"Fish returned no audio for passage {it['index']}: {it['text'][:80]}")
        writer.put(it, audio, sr, time.monotonic() - started, None)
    writer.close()
    event(type="done", message="All passages generated")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    args = ap.parse_args()
    event(type="status", stage="loading", message="Starting the speech engine and checking your hardware…")
    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    if tasks.get("model") == "fish_s2":
        return fish_main(tasks)
    if os.name == "nt":  # no symlinks without Developer Mode; avoid huggingface_hub's WinError 1314 race
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        try:
            from huggingface_hub import file_download
            file_download.are_symlinks_supported = lambda *a, **k: False
        except Exception:
            pass
    import torch

    model_id = tasks["model"]
    default_speaker = tasks.get("speaker", "Aiden")
    reference = tasks.get("reference") or None
    instruct = tasks.get("instruction") or ""
    base_seed = int(tasks.get("seed", 42))
    engine_pref = (tasks.get("engine") or "auto").lower()
    requested_batch = int(tasks.get("batch_size") or 0)
    items = tasks["tasks"]
    cuda = torch.cuda.is_available()
    device = "cuda" if cuda else "cpu"
    vram = lambda: torch.cuda.memory_reserved() / GB if cuda else None
    if cuda:
        props = torch.cuda.get_device_properties(0)
        free0, total0 = torch.cuda.mem_get_info()
        # Windows silently spills into (very slow) shared system RAM when VRAM is exceeded.
        # Cap PyTorch below physical free VRAM so we get a clean out-of-memory error instead,
        # which the batch loop handles by halving the batch.
        torch_limit = max(0.3, min(0.97, (free0 - 0.35 * GB) / total0)) * total0
        try:
            torch.cuda.set_per_process_memory_fraction(torch_limit / total0)
        except Exception:
            torch_limit = total0
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
        event(type="device", device=props.name, cuda=True, vram_total_gb=total0 / GB)
    else:
        torch.set_num_threads(max(1, os.cpu_count() or 1))
        event(type="device", device="CPU (no CUDA GPU detected — this will be very slow)", cuda=False, vram_total_gb=None)
        event(type="warning", message="PyTorch cannot see your NVIDIA GPU. Narration runs on the CPU and will be extremely slow. "
                                      "Update the NVIDIA driver, then re-run install.bat.")
    event(type="status", stage="loading", message=f"Loading {model_id} on {device}. Missing model files download automatically; download progress appears in the activity log.")

    engine_name = "single"
    batch_size = 1
    synth_batch = None   # callable(list[item]) -> list[np.ndarray|None], sr
    fallback = None      # engine to switch to if the fast engine fails while narrating

    if model_id not in REPOS:
        raise ValueError("Unknown model selection: " + model_id + ". This version only includes Qwen3-TTS.")
    repo = REPOS[model_id]
    kind = "clone" if model_id.endswith("clone") else "design" if model_id.startswith("design") else "custom"
    ins = instruct if model_id == "qwen17" else ""
    default_ref = reference
    default_ref_text = tasks.get("reference_text") or ""
    if kind == "clone" and not (default_ref or all(it.get("reference") for it in items)):
        raise ValueError("This narrator has no reference recording.")
    dtype = torch.bfloat16 if cuda or os.environ.get("VOICEBOOK_CPU_BF16") else torch.float32
    fast = None
    if cuda and engine_pref in ("auto", "fast"):
        try:
            from faster_qwen3_tts import FasterQwen3TTS
            event(type="status", stage="loading", message="Loading Qwen with CUDA graphs (fast engine)…")
            fast = FasterQwen3TTS.from_pretrained(repo, device="cuda", dtype=dtype, attn_implementation="sdpa", max_seq_len=2048)
            base = fast.model
        except ImportError:
            if engine_pref == "fast":
                event(type="warning", message="Fast engine is not installed (run install-qwen-fast.bat). Using batched GPU engine.")
        except Exception as exc:
            event(type="warning", message=f"Fast engine failed to start ({type(exc).__name__}: {exc}). Using batched GPU engine.")
            fast = None
            free_gpu(torch)
    if fast is None:
        from qwen_tts import Qwen3TTSModel
        base = Qwen3TTSModel.from_pretrained(repo, device_map="cuda:0" if cuda else "cpu", dtype=dtype,
                                             attn_implementation="sdpa")
    sr_holder = {"sr": 24000}

    def seed_of(it):
        return passage_seed(base_seed + 7919 * int(it.get("reseed") or 0), it["text"])

    def ref_of(it):
        return it.get("reference") or default_ref, it.get("reference_text") or default_ref_text

    def qwen_fast(batch):
        out = []
        for it in batch:
            torch.manual_seed(seed_of(it))
            cap = min(1500, token_cap([it["text"]]))
            if kind == "clone":
                ref, ref_text = ref_of(it)
                wavs, sr = fast.generate_voice_clone(text=it["text"], language="English", ref_audio=ref,
                                                     ref_text=ref_text, max_new_tokens=cap)
            elif kind == "design":
                wavs, sr = fast.generate_voice_design(text=it["text"], instruct=it["instruct"], language="English",
                                                      max_new_tokens=cap)
            else:
                wavs, sr = fast.generate_custom_voice(text=it["text"], speaker=it.get("speaker") or default_speaker,
                                                      language="English", instruct=ins or None, max_new_tokens=cap)
            sr_holder["sr"] = sr
            out.append(valid(wavs[0]) if wavs else None)
        return out, sr_holder["sr"]

    prompts = {}

    def qwen_batched(batch):
        texts = [it["text"] for it in batch]
        torch.manual_seed(seed_of(batch[0]))
        if cuda:
            torch.cuda.manual_seed_all(seed_of(batch[0]))
        cap = token_cap(texts)
        with torch.inference_mode():
            if kind == "clone":
                items_prompt = []
                for it in batch:
                    ref, ref_text = ref_of(it)
                    if ref not in prompts:
                        prompts[ref] = base.create_voice_clone_prompt(ref_audio=ref, ref_text=ref_text)[0]
                    items_prompt.append(prompts[ref])
                wavs, sr = base.generate_voice_clone(text=texts, language=["English"] * len(texts),
                                                     voice_clone_prompt=items_prompt, max_new_tokens=cap)
                return [valid(w) for w in wavs], sr
            if kind == "design":
                wavs, sr = base.generate_voice_design(text=texts, instruct=[it["instruct"] for it in batch],
                                                      language=["English"] * len(texts), max_new_tokens=cap)
                return [valid(w) for w in wavs], sr
            speakers = [it.get("speaker") or default_speaker for it in batch]
            input_ids = base._tokenize_texts([base._build_assistant_text(t) for t in texts])
            instruct_ids = [base._tokenize_texts([base._build_instruct_text(ins)])[0] if ins else None for _ in texts]
            kwargs = base._merge_generate_kwargs(max_new_tokens=cap)
            codes, _ = base.model.generate(input_ids=input_ids, instruct_ids=instruct_ids,
                                           languages=["English"] * len(texts), speakers=speakers,
                                           non_streaming_mode=True, **kwargs)
            out, sr = [], 24000
            # Decode one at a time: decoding a padded batch of long passages spikes VRAM.
            for c in codes:
                if c is None or len(c) < 2:
                    out.append(None)
                    continue
                wavs, sr = base.model.speech_tokenizer.decode([{"audio_codes": c}])
                out.append(valid(wavs[0]))
        return out, sr

    def batched_setup():
        if engine_pref == "single" or kind == "design":
            return "single passage", qwen_batched, 1
        if requested_batch > 0:
            size = requested_batch
        elif cuda:
            free, _total = torch.cuda.mem_get_info()
            room = min(free, torch_limit - torch.cuda.memory_reserved()) - 0.9 * GB
            # Cloning adds the ~12 s reference to every passage's context.
            per_passage = (0.34 if kind == "clone" else 0.24) * GB
            size = int(max(1, min(16, room // per_passage)))
        else:
            size = 2
        return ("batched GPU" if cuda else "batched CPU"), qwen_batched, size

    if fast is not None:
        engine_name, synth_batch, batch_size = "fast (CUDA graphs)", qwen_fast, 1
        fallback = batched_setup
    else:
        engine_name, synth_batch, batch_size = batched_setup()

    event(type="engine", engine=engine_name, batch_size=batch_size)
    event(type="status", stage="narrating",
          message=f"Voice model ready ({engine_name}, {batch_size} passage{'s' if batch_size != 1 else ''} at a time). Narrating…")

    writer = Writer(len(items))
    pos = 0
    retry_alone = []
    while pos < len(items):
        # Sort a window of upcoming passages by length so each batch finishes together,
        # while still progressing through the book roughly in order.
        window = sorted(items[pos:pos + batch_size * 4], key=lambda it: len(it["text"]))
        pos += len(window)
        k = 0
        while k < len(window):
            batch = window[k:k + batch_size]
            event(type="chunk_start", index=batch[0]["index"], chapter=batch[0].get("chapter", ""),
                  text=batch[0]["text"], chars=sum(len(it["text"]) for it in batch), batch=len(batch))
            started = time.monotonic()
            problem = None
            try:
                audio, sr = synth_batch(batch)
            except Exception as exc:
                oom = "out of memory" in str(exc).lower() or type(exc).__name__ == "OutOfMemoryError"
                if oom and batch_size > 1:
                    problem = "oom"
                elif fallback is not None:
                    problem = f"{type(exc).__name__}: {exc}"
                else:
                    raise
            if problem:
                free_gpu(torch)  # outside the except block so the failed batch's tensors are released
                if problem == "oom":
                    batch_size = max(1, batch_size // 2)
                    event(type="warning", message=f"GPU memory full; continuing with {batch_size} passage(s) at a time.")
                else:
                    engine_name, synth_batch, batch_size = fallback()
                    fallback = None
                    event(type="warning", message=f"Fast engine stopped ({problem[:200]}). Continuing with the batched GPU engine.")
                event(type="engine", engine=engine_name, batch_size=batch_size)
                continue  # retry the same passages
            elapsed = time.monotonic() - started
            for it, a in zip(batch, audio):
                if a is None:
                    retry_alone.append(it)
                else:
                    writer.put(it, a, sr, elapsed / len(batch), vram())
            k += len(batch)
    # Passages that came back empty/invalid get a second attempt on their own, new seed.
    for it in retry_alone:
        base_seed += 7919
        started = time.monotonic()
        audio, sr = synth_batch([it])
        if audio[0] is None:
            writer.close()
            raise RuntimeError(f"Invalid audio generated for passage {it['index']}: {it['text'][:80]}")
        writer.put(it, audio[0], sr, time.monotonic() - started, vram())
    writer.close()
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
