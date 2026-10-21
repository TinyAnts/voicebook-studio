# 🎧 Voicebook Studio

**Free, private, laptop-first PDF and EPUB → AI audiobook converter.** Designed for long **fiction and nonfiction** books and a Windows laptop with an NVIDIA RTX 3070 (8 GB VRAM). No paid API, subscription, database, cloud deployment or account is needed to use it locally.

### Quick start — Windows

1. Install [Python 3.11](https://www.python.org/downloads/release/python-3119/) (with the Windows **Python launcher**, `py`).
2. Download this repository with **Code → Download ZIP**, extract it, and **double-click `install.bat`**. This installs the lightweight interface and Qwen3-TTS in separate environments, plus bundled FFmpeg. (First-time downloads can be large.)
3. **Double-click `start.bat`**. Your browser opens at **http://127.0.0.1:7860**.
4. Click **Generate voice preview** to listen to **Aiden** or **Ryan** and decide which you prefer. No PDF is required just to audition a voice.
5. Upload a **PDF or EPUB**, tick or untick the chapters to convert, check the **book cover preview** (or upload custom artwork), select **Fiction** or **Nonfiction**, and click **Generate selected chapters**.
6. Play the sample and download your final **M4B** (chapter markers) or **MP3**. Jobs are saved in the `audiobooks` folder; rerunning the same job resumes missing passages.

**More voices (optional):** Double-click `install-chatterbox.bat` for **Chatterbox Multilingual V3** and **Chatterbox Turbo**, or `install-kokoro.bat` for very fast **Kokoro-82M**. Chatterbox requires a **6–15-second voice-reference recording**, such as your own voice, or an authorized narrator's recording. You may need to install [Git for Windows](https://git-scm.com/downloads/win) for Chatterbox dependencies, and [espeak-ng](https://github.com/espeak-ng/espeak-ng/releases) for Kokoro.

**If Qwen3-TTS 1.7B exceeds 8 GB GPU memory**, use **Qwen3-TTS 0.6B** in the model dropdown; that backend is installed by the same `install.bat`. High-quality synthesis may be much slower than reading time. Your computer must remain on while generating a book.

## What it does

| Feature | Included |
|---|---|
| PDF, EPUB, TXT, MD | ✅ |
| Automatic EPUB artwork / PDF first-page cover | ✅ |
| Cover preview and custom JPG/PNG/WEBP replacement | ✅ |
| Embedded album art in M4B and MP3 (1200px square, no cropping) | ✅ |
| EPUB chapter selection | ✅ (reading-spine sections) |
| PDF chapter selection | ✅ (PDF bookmarks when present; otherwise groups of pages) |
| Fiction / nonfiction style presets | ✅ (Qwen 1.7B prompt instructions) |
| **Listen before deciding on a voice** | ✅ (generate and play a short sample) |
| Compare previously generated voice previews | ✅ |
| Qwen3-TTS 1.7B and 0.6B, Aiden/Ryan | ✅ |
| Chatterbox Multilingual V3 / Turbo with voice cloning | ✅ optional install |
| Kokoro 82M predefined voices | ✅ optional install |
| Long-book cache / resume | ✅ |
| Regenerate one chapter without other chapters | ✅ (select one chapter) |
| MP3 and M4B with navigable chapters | ✅ |
| List and redownload completed audiobooks | ✅ |
| Paid API calls | **None** |

### GitHub repository

The complete application source is maintained at [TinyAnts/voicebook-studio](https://github.com/TinyAnts/voicebook-studio). Download it with **Code → Download ZIP**; you do not need to run the included publisher to use this repository.

The optional `publish-github.bat` / `.ps1` scripts are retained for creating a separate repository from a local copy.

Books, generated audio, model environments and secrets are excluded from Git by `.gitignore`. GitHub Actions runs document-processing and audio-export tests on code changes; model inference still runs on your laptop.

## Optional remote access / hosting

You normally need **no hosting**: the program runs at `127.0.0.1:7860` in your laptop's browser. GitHub Pages and Cloudflare Pages can serve a website but **cannot execute GPU-powered Qwen or Chatterbox inference**. You would need to connect a separate running GPU backend.

If you occasionally want to access the laptop from your phone, install [Tailscale](https://tailscale.com/download) on both devices. With the app running, on the laptop run:

```powershell
tailscale serve --bg 7860
tailscale serve status
```

Use the private HTTPS URL given by Tailscale from your connected phone; the laptop must stay online. Avoid exposing unauthenticated Gradio to the public internet. To stop sharing within your tailnet: `tailscale serve off`.

`hf_space/` contains an **optional experimental short Qwen voice-preview Space** for Hugging Face ZeroGPU. It is not needed for your local app and is **not** an always-on free full-book GPU host. Its remote deployment and actual GPU inference have not been validated.

## Important limitations

- **Cover artwork** is automatically extracted from EPUB book metadata or rendered from the PDF first page. A custom JPG/PNG/WEBP overrides it. Art is letterboxed instead of cropped, then embedded as a cover image in MP3/M4B. Different audiobook players may display cover art differently.
- **Scanned/image-only PDFs require OCR** before importing. Text extraction from complex layouts, equations, footnotes and tables may require manual cleanup.
- PDF bookmarks are used when available; otherwise the app creates user-selectable **page-group sections**, which may not exactly align with actual chapters. EPUB internal spine sections can likewise differ from editorial chapters.
- The models generate speech in ~320-character chunks and cache WAV output. Very long books need substantial disk space, and occasional mispronunciations/repeated words can require rerunning a passage/chapter.
- Each Chatterbox recording should be a **clean, authorized** 6–15 second clip. Voice cloning should not impersonate someone without consent.
- DRM removal is not supported. Only narrate books you are permitted to process; personal listening does not automatically authorize redistributing generated audiobooks.
- Local source and M4B encoding were tested, but the actual GPU model inference and Windows one-click installers have **not yet been executed on your laptop**. If an upstream model install fails, other backends remain independent.

## Technical layout

```text
voicebook_studio/
├── app.py                       # Easy local Gradio interface
├── core.py                      # PDF/EPUB chapters, cover art, cache, M4B/MP3
├── worker.py                    # Isolated local GPU model inference
├── requirements-ui.txt
├── install.bat / start.bat      # Double-click install / launch
├── install-chatterbox.bat       # Optional custom narrator backend
├── install-kokoro.bat           # Optional fast backend
├── setup.ps1                    # Model environments and dependencies
├── publish-github.bat / .ps1   # One-click private GitHub repo publisher
├── .github/workflows/tests.yml # Automated unit tests
├── tests/test_core.py
└── hf_space/                    # Optional separate Hugging Face voice preview
```

Model sources and licenses: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) (Apache 2.0), [Chatterbox](https://github.com/resemble-ai/chatterbox) (MIT), [Kokoro](https://github.com/hexgrad/kokoro) (Apache 2.0). All can run without per-character API costs after downloading their weights. Third-party components retain their own license terms.

### Developer tests

```sh
python -m pip install -r requirements-ui.txt
python -m unittest discover -s tests -v
python -m compileall -q app.py core.py worker.py
```
