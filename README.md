# 🎧 Voicebook Studio

**Free, private, laptop-first PDF and EPUB → AI audiobook converter.** Designed for long **fiction and nonfiction** books and a Windows laptop with an NVIDIA RTX 3070 (8 GB VRAM). No paid API, subscription, database, cloud deployment or account is needed to use it locally.

### Quick start — Windows

1. Install [Python 3.11](https://www.python.org/downloads/release/python-3119/) (with the Windows **Python launcher**, `py`).
2. Download this repository with **Code → Download ZIP**, extract it, and **double-click `install.bat`**. This installs the lightweight interface and Qwen3-TTS in separate environments, plus bundled FFmpeg. (First-time downloads can be large.)
3. **Double-click `start.bat`**. Your browser opens at **http://127.0.0.1:7860**.
4. Choose a model, then click **Create missing voice samples for this model** to save the same passage for its built-in voices. Switch narrators and replay saved samples instantly. You can also generate a custom preview; no book is required.
5. Upload a **PDF or EPUB**, tick or untick the chapters to convert, check the **book cover preview** (or upload custom artwork), select **Fiction** or **Nonfiction**, and set reading speed, and click **Create audiobook**. Follow the live monitor above the form.
6. Play the sample and download your final **M4B** (chapter markers) or **MP3**. Open **Library · books & previews** to play older files, rename them, edit their title/author/notes, or move them to recoverable Trash. Jobs are saved in the `audiobooks` folder; rerunning the same job resumes missing passages.

**More voices (optional):** Double-click `install-chatterbox.bat` for **Chatterbox Multilingual V3** and **Chatterbox Turbo**, or `install-kokoro.bat` for very fast **Kokoro-82M**. Chatterbox requires a **6–15-second voice-reference recording**, such as your own voice, or an authorized narrator's recording. You may need to install [Git for Windows](https://git-scm.com/downloads/win) for Chatterbox dependencies, and [espeak-ng](https://github.com/espeak-ng/espeak-ng/releases) for Kokoro.

**If Qwen3-TTS 1.7B exceeds 8 GB GPU memory**, use **Qwen3-TTS 0.6B** in the model dropdown; that backend is installed by the same `install.bat`. High-quality synthesis may be much slower than reading time. Your computer must remain on while generating a book.

## Updating your existing installation

1. Stop any conversion and close the app terminal.
2. Extract the new ZIP and copy the **contents of `VoicebookStudio`** into your existing app folder. Choose **Replace files** when asked. Keep the existing `audiobooks` folder and all `.venv-*` folders; do not delete the old app folder or nest another `VoicebookStudio` folder inside it.
3. Double-click your existing `start.bat`. **No model reinstall is needed for this update.** Your old exports and saved passages remain available. The complete steps are also in `UPDATE_WINDOWS.txt`.

## A clearer workspace

- **Live monitor:** named stages (prepare, load voice, narrate, export), measured passage/export progress, elapsed time, estimated narration time remaining, current chapter/text, saved passage counts, worker heartbeat, GPU information and an expandable log. Model loading has an indeterminate indicator because its progress is not measurable here. The estimate learns from generated passages and excludes loading/export time.
- **Background jobs:** refreshing the browser reconnects to the same running process. **Stop & keep progress** retains finished passages; **Resume / retry last job** uses the original settings. Keep the app terminal and computer running. After restarting the app, upload the same document and settings to resume from cached passages.
- **Listening controls:** export speed from **0.75× to 1.5×** with pitch preserved, extra passage and chapter pauses, consistent volume, 96/128/192 kbps, and M4B/MP3. Speed and export changes reuse saved speech. These do not change model inference speed.
- **Library:** search, filter and sort books/previews; select one to play an excerpt, jump to a different starting minute, and download the full file. Metadata edits preserve audio, cover and chapter markers. File edits wait until the current conversion finishes or is stopped. This is a metadata editor, not a waveform or narration-text editor.
- **Recoverable deletion:** Trash moves the selected export out of the library; Restore returns it. Other exports and cached narration stay intact. This does not reclaim all disk space; you can remove unneeded files from the local folder after checking backups.

## Friendly filenames and reusable voice samples

New downloads use readable book/chapter, narrator, model and speed names, for example:

- `The Quiet Valley - 03 A New Beginning - Aiden - Qwen 1.7B - 1x.m4b`
- `Preview - Voice sample - Ryan - Qwen 1.7B - 1x.mp3`

EPUB titles come from book metadata where available. PDFs/text use the source filename. Multiple selected chapters are labeled by chapter number. Different versions with otherwise identical names receive `(2)`, `(3)`, and so on. Internal cache folders retain their fingerprints so old narration still resumes. Older files are left intact and can be renamed in the library.

**Create missing voice samples** reads one shared passage for every built-in voice in the selected installed model, at 1× using the current tone, seed and export quality. The first run needs local speech generation; later runs reuse matching saved files without loading a model. Switch narrators and select a saved sample to compare voices. Chatterbox uses your reference recording through **Generate voice preview** instead. No fabricated or third-party recordings are bundled.

The separate **Voice preview text** box lets you audition your own passage, or select **Use selected book excerpt instead**. Previews are saved automatically. If you change the text, voice, tone, reference recording or seed, that is a new sample. The library keeps previous versions for comparison.

The progress layout follows [Nielsen Norman Group guidance on progress indicators](https://www.nngroup.com/articles/progress-indicators/) and [response times](https://www.nngroup.com/articles/response-times-3-important-limits/): keep system status visible, distinguish unknown waits from measured progress, and provide useful feedback for long tasks. Polling uses [Gradio Timer](https://www.gradio.app/docs/gradio/timer); export tempo uses [FFmpeg audio filters](https://ffmpeg.org/ffmpeg-filters.html#atempo).

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
| Search, play, rename and edit old generations | ✅ |
| Recoverable Trash and Restore | ✅ |
| Reusable voice sample bank | ✅ |
| Live conversion stages, heartbeat, Stop/Resume | ✅ |
| Pitch-preserving reading speed and pause controls | ✅ |
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
- This update was tested with actual FFmpeg encoding, metadata/cover/chapter preservation, cached export, sample reuse, job cancellation/resume, and Gradio event/API calls. Model lifecycle tests use a small test worker; this update was not run against a real GPU or Windows installation here. Browser visual review was unavailable in the build environment. Your installed model backends remain independent.

## Technical layout

```text
voicebook_studio/
├── app.py                       # Easy local Gradio interface
├── core.py                      # PDF/EPUB chapters, cover art, cache, M4B/MP3
├── worker.py                    # Isolated local GPU model inference
├── jobs.py                      # Background jobs, stop/resume, saved voice samples
├── dashboard.py                 # Accessible live status
├── export_audio.py              # Streaming speed/pause/cover/chapter export
├── library_store.py             # Playback, metadata editing, Trash/restore
├── naming.py                    # Readable Windows-safe output names
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
python -m compileall -q app.py core.py worker.py jobs.py dashboard.py export_audio.py library_store.py naming.py
python tests/smoke_ui.py
```
