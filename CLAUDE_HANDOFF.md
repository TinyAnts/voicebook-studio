# Voicebook Studio — handoff for Claude

Updated: 21 October 2026. Read this file together with `README.md` and the actual source before making changes. This is a working local application, not a design-only prototype.

## Project and user priorities

- Private repository: https://github.com/TinyAnts/voicebook-studio (branch `main`). Keep the repository private.
- Main use: turn long fiction and nonfiction PDF/EPUB books into audiobooks on a Windows laptop with an NVIDIA RTX 3070 (8 GB VRAM) and 32 GB RAM. TXT/MD are also supported.
- Priorities: simple double-click operation, chapter selection, embedded book cover, understandable conversion progress, playable voice previews, and easy management of old generations.
- Local use is primary. Occasional remote access is secondary. There is no need to redesign this as a hosted service or add accounts, a database or paid speech APIs.
- The user wants complete runnable code and a full ZIP, not isolated snippets or instructions to push code themselves. Updates should preserve installed models, environments and existing audio.
- Latest visual preference: a Claude-inspired warm dark theme. Cream text must stay readable on charcoal backgrounds. The user explicitly requested screenshots and visual verification.

## Current delivery

This folder contains the full application, installation scripts, automated tests, optional browser-review script, and update instructions. `UPDATE_WINDOWS.txt` is the short installation/update guide.

The last published commit before this theme/bug-fix handoff was `a56db0fd2f6b3ba6b6c00dd4f2e6940fd507e498` (the UI/library revamp). The theme and handoff are delivered in a subsequent commit; inspect the current branch head instead of assuming the preceding SHA is current.

## Latest changes and why they were needed

### Narrator picker revamp + ready samples (22 Oct 2026, Claude)

- Step 2 is now: Speech engine radio · narrator grid (Radio, men then women, `voices.choices()`) · narrator card with a ready sample (`voices.ready_sample`: `voices/_builtin/aiden.mp3`, `voices/<id>/sample-qwen.mp3`, else the reference) · "Hear it read your own text" · "Add a narrator" (Describe / Recording tabs). The old saved-samples dropdown is gone (`saved_voice` kept hidden). With Fish selected the card shows a saved Fish preview (Library) or offers "Make Fish samples for all narrators" (sample bank, library narrators only).
- Qwen samples were generated on CPU in the cloud (bf16, seed 42) reading `voices.SAMPLE_TEXT`; Aiden/Ryan used the default Nonfiction style.
- `download-models.bat` pre-downloads CustomVoice, Base and VoiceDesign 1.7B into `HF_HOME` (D:\hf-cache on Hj's laptop, set by cleanup-and-setup).

### Fish S2 Pro 4-bit engine (22 Oct 2026, Claude)

- Optional second engine `fish_s2`: community NF4 build of Fish Audio S2 Pro served by the Docker `server` profile of https://github.com/scarxity/fish-speech-int4-patch (pinned 3fd7da6a), installed by `install-fish.ps1` to `%LOCALAPPDATA%\VoicebookStudio\fish-speech` (outside OneDrive). `.env`: ENABLE_LAZY_LOAD=1 (model loads on first request, unloads after 300 s idle, so Qwen can use the GPU).
- `worker.fish_main` (no torch; runs under the UI Python): health check, auto `docker compose --profile server up -d`, then POST `/v1/tts` per passage with the narrator's reference clip inline (base64 + transcript), `seed`, `max_new_tokens`. Fish needs a library narrator (Aiden/Ryan are Qwen CustomVoice only).
- UI: Speech engine dropdown in step 2 (`tts` option → `jobs._prepare` sets model `fish_s2`). Tested only against a stand-in HTTP server (`TestFishEngine`); real Docker/GPU behaviour, speed and 8 GB VRAM fit are NOT verified. Licence: Fish Audio Research License.

### Finished folder and chapter files (22 Oct 2026, Claude)

- Every audiobook export also builds `audiobooks/Finished/<Title - Author>/`: `cover.jpg`, `About.txt` (title, author, narrator, chapter list with lengths), `Full book/` (hard link to the job-folder export, copy if linking fails) and `Chapters/NN - <chapter>.<ext>`. Option "Files to make": both / full / chapters; "Chapter file format": same (stream copy, seconds) / MP3 / M4B (re-encode). Previous chapter files listed in `.voicebook.json` are replaced on re-export.
- `export_audio` writes `<export>.chapters.json` (chapter start/end) used by `split_chapters`. Chapter files get title/album/artist/album_artist/track/genre tags and the cover.
- Volume: `loudnorm` replaced by one measured gain (`speech_gain_db`, NumPy RMS of voiced frames → -20 dBFS) + `alimiter`; ~3× faster encode. `atempo` skipped at 1.0×.
- TXT chapters use their "Chapter N …" heading as the title.
- The job folder stays the cache and the Library's source; `Finished` is excluded from the Library scan.

### Narrator library and Qwen-only (22 Oct 2026, Claude)

- Removed Qwen 0.6B, Chatterbox and Kokoro from the UI, worker and installers (user's choice). Worker `REPOS`: `qwen17` (CustomVoice: Aiden/Ryan + style), `qwen17clone` (Base: voice clone), `design17` (VoiceDesign). `qwen06`/`qwen06clone` remain only for old jobs and CPU tests.
- `voices.py`: Narrator values are `Aiden`, `Ryan` or `voice:<id>`. `resolve()` → (model, speaker name, reference wav, reference text). Presets ship in `voices/<id>/{reference.wav,voice.json}`; user narrators live in `audiobooks/_voices/` (design from description, or import a recording + transcript). All presets read the same `REFERENCE_TEXT`.
- Presets were designed on CPU in the cloud with VoiceDesign 1.7B (bf16), two takes each; the take was picked by Whisper transcript match and pitch range. Nobody has listened to them yet — ask the user for feedback and redesign any that sound wrong.
- `jobs._narrate` runs one worker per model group (sample bank spans built-in and cloned narrators). `_design` creates a narrator. Per-task `reference`/`reference_text`/`reseed`.
- Repair mechanism: `audiobooks/_text-fixes/<title>.json` (`replace` text_key → new text or '' to drop; `reseed` text_key → n). Positions never shift. Used to remove the OceanofPDF watermark from the first book.
- `update-github.ps1/.bat`: clones TinyAnts/voicebook-studio to %TEMP%, mirrors source with robocopy (excludes audiobooks, venvs, backups, logs), commits and pushes with the user's own GitHub login. This cloud session had no push access.

### Naming, tags and text cleanup (22 Oct 2026, Claude)

First full book finished with the fast engine: 1,277 passages, 6.8 h audio, 11 chapters, ~1.6× real time on the RTX 3070 Laptop GPU.
- `naming.book_info()` → (title, author): EPUB metadata; PDF/TXT "Title - Author" filename split, else PDF author metadata. `export_name(..., author, full_book)` → e.g. `The Psychedelic Handbook - Rick Strassman - Full book - Ryan - Qwen 1.7B - 1x.m4b`. `book.json` now has `total_chapters` and `text_version`.
- Export tags: artist/album_artist = author, album = title, genre Audiobook, comment "Narrated by …". Output resampled to 44.1 kHz (`loudnorm` had produced 96 kHz AAC).
- Text cleanup v2 (`core.TEXT_VERSION`): drops URL-only lines (e.g. download-site watermarks read aloud 25× in the first book) and PDF running headers (same short line on ≥30% and ≥8 pages). Folders that already have audio and no `text_version` keep v1 extraction so cached passages still align.
- `discard_mismatched_passages`: WAVs are stored by position; if `passages.json` (or legacy `tasks.json`) says the position held different text, the WAV is deleted before narration so stale audio is never exported.
- Library and result panel: "Show in folder" (opens Explorer) and the folder location.
- Known: ~6 of 1,277 passages had unusually long audio for their text (possible repeated words). There is no single-passage re-narrate feature yet.

### Speed and log-driven fixes (21 Oct 2026, Claude)

The user's logs showed Qwen 1.7B taking ~170–210 s for ~20–26 s of audio per passage (~7–8× slower than real time) on the RTX 3070, with 1,275 passages queued (~60+ hours). Stock `qwen-tts` is bound by per-step Python/kernel-launch overhead (one talker step plus 15 code-predictor steps per 12 Hz frame), so the GPU sits mostly idle.

- `worker.py` rewritten: engines `fast` (optional `faster-qwen3-tts==0.5.4` CUDA graphs in `.venv-qwenfast`, pinned `transformers==5.15.1` because 5.20 breaks `qwen-tts-hf` with a `MimiConfig.rope_theta` error), `batched` (official qwen-tts 0.1.1 batch generate via the same private helpers `generate_custom_voice` uses; decode one passage at a time to limit VRAM), `single`. Auto batch size from free VRAM (~0.24 GB/passage for 1.7B); `set_per_process_memory_fraction` keeps PyTorch below physical VRAM so Windows does not silently spill to shared memory; OOM halves the batch and retries; fast-engine failure falls back to batched with the already-loaded base model. Windows of 4×batch upcoming passages are length-sorted. `max_new_tokens` capped at `96 + 2×chars` (model default 8192 frames). Per-passage seed = seed + crc32(text) (position-independent). Background writer thread for WAVs. Device/engine/warnings also go to `worker.log` as `[voicebook] …` lines.
- Verified in Linux CPU containers with the real Qwen3-TTS 0.6B weights: batched output transcribed correctly with Whisper, both voices of a sample bank in one worker, OOM back-off with a fake model, fast-env fallback path under transformers 5.15.1. Not verified: CUDA, CUDA graphs, real 1.7B speed on the RTX 3070, Windows.
- `jobs.py`: `_run` → `_prepare` per voice, one `_narrate` worker for everything missing (sample bank no longer reloads the model per voice), `_export` per plan. Worker task indices are global; `by_index` maps to `(Piece, row title)`. `model_python(model, engine)` prefers `.venv-qwenfast` for auto/fast. Worker env silences transformers/HF symlink warnings. `as_int` guards None from cleared Gradio numbers.
- `core.py`: `passages.json` per folder (voice key + text hash per WAV). `reuse_saved_passages` copies identical passages from other folders of the same book/voice settings (new chapter selection or PDF section size no longer regenerates everything). Legacy folders are read from `book.json` + `tasks.json`. The folder cache key is unchanged.
- UI layout (second pass): Create tab is a two-column layout — left: numbered step cards 1 Book, 2 Narrator (+ preview, saved samples), 3 Listening & export, 4 Advanced (GPU speed, generation settings); right (`#side`, sticky): Create button, Stop/Resume, live status card, result, chapter table + log. `.gradio-container` overflow is switched to `clip` so `position:sticky` works; `#side` must not scroll internally (Chromium did not paint it). Library uses the same card style. GPU speed: engine + passages per batch. Dashboard: narration speed (× real time), engine/batch, warnings, stall warning threshold scales with batch.
- `install-qwen-fast.bat` / `setup.ps1 -Model qwenfast`. New tests: `tests/test_speed.py`.

### Readability and theme

The previous interface mixed hard-coded light-theme navy/green foregrounds with Gradio's dark backgrounds. The header and status labels were nearly invisible in the user's screenshot.

`theme.py` now owns a shared Gradio `THEME` and custom `CSS`:

- Page `#262624`, panels `#30302c`, raised surfaces `#35342f`.
- Primary text `#f2efe8`, secondary text `#c8c1b7`.
- Terracotta accent `#e3a187`; primary buttons use dark text on a light terracotta fill.
- Green completed steps, pale red error states, visible focus and disabled states.
- Both normal and `_dark` Gradio theme variables use the same dark palette. A browser/system preference change cannot turn the foreground dark while leaving the background dark.
- Dropdowns have opaque surfaces; small-screen columns and action buttons wrap. Completed output uses a styled column rather than the former Group with harsh default borders.
- Local system fonts are used. No paid font or theme dependency is required.

The theme parameters were checked against the Gradio 6.5 method signature; newer checkbox-shadow parameters were removed. Full browser verification used Gradio 6.30.0, not a separate 6.5 runtime.

### Repeated `NoneType.casefold` error

The user supplied a Windows traceback ending in `library_store.entries()` at `query.casefold()`. Gradio sometimes sends `None` for an untouched or cleared textbox. The one-second polling timer then repeated the exception after a generation finished.

Fix: `entries()` normalizes query with `str(query or '').casefold().strip()` and defaults missing kind/sort values. The search component also starts with `value=''`. Regression checks cover missing filters and a fresh UI client polling with `query=None`. This was a library/status refresh error; the fix does not rewrite generated narration.

## Architecture and file map

| File | Responsibility |
|---|---|
| `app.py` | Gradio components and event handlers; Create and Library tabs; one-second status polling; connects UI to job manager and catalog. |
| `theme.py` | All theme tokens and custom CSS. Use the same `THEME`/`CSS` for normal launch and tests. |
| `dashboard.py` | Escaped HTML for stage status, progress, elapsed time, narration estimate and chapter table. |
| `jobs.py` | Thread-safe `JobManager`, one background job, worker subprocess lifecycle, Stop/Resume, sample-bank sequence and export coordination. |
| `worker.py` | Runs speech inference in the selected model environment, writes WAV passages and emits tagged JSON events. |
| `core.py` | Document extraction, chapter selection, cover processing, stable narration cache planning and export wrapper. |
| `export_audio.py` | Streaming FFmpeg assembly, tempo/pause/volume settings, chapter timing, artwork, progress and cancellation. |
| `library_store.py` | Catalog/search, bounded playback excerpts, tag/filename edits, recoverable Trash and restore. |
| `naming.py` | Readable Windows-safe names and collision suffixes. |
| `setup.ps1`, `install*.bat` | Separate UI/model environment installation. |
| `start.bat` | Starts `app.py` through the existing `.venv-ui` environment. |
| `tests/test_core.py` | Extraction, selection/cache, covers and actual audio export tests. |
| `tests/test_progress.py` | Progress/estimate, export pitch/timing, cancellation, errors, resume and silent normalization. |
| `tests/test_library.py` | Old-file playback, metadata/cover/chapter preservation, Trash, path/collision guards, naming, missing filters and sample reuse. |
| `tests/smoke_ui.py` | Real Gradio client/API flow using temporary cached audio, including an untouched search value. |
| `tests/visual_review.py` | Optional real Chromium screenshots and optional axe-core contrast checks, using temporary synthetic fixtures. |
| `hf_space/` | Separate experimental short-preview Hugging Face project. Not the local app or a validated full-book hosting solution. |

### Job and progress flow

1. UI collects settings and calls `MANAGER.start()`. A background thread allows the browser to keep responding.
2. `plan_job()` extracts the selected chapters and locates the stable narration cache. Valid saved passages are reused.
3. Missing speech runs in a subprocess using the chosen model's Python environment.
4. Worker stdout messages begin with `VOICEBOOK_EVENT:`. Events include status, device, heartbeat, chunk start, completed chunk and errors. Other backend output goes to the log.
5. FFmpeg assembles audio with export settings and reports measured export progress. Files are written to `.partial` paths before successful replacement.
6. UI polls a snapshot every second with `queue=False`. Change tokens prevent resetting audio players every tick. A completed job adds its output to the library.

The heartbeat signals that the worker process is responsive; it does not prove that a speech chunk is advancing. Loading/downloading is indeterminate. Narration progress measures saved passages, and export progress uses FFmpeg timestamps. The estimate starts after enough generated work and covers narration only, not loading/export.

Stop terminates the active subprocess and keeps completed WAV passages. Resume/retry uses the last settings. Browser refresh reconnects while the same app process lives. After the app restarts, upload the same source and select the same settings to resume through the disk cache; the in-memory last-job state is not durable.

### Speech environments

Do not combine the UI and model environments: model dependencies conflict.

| Environment | Current installer configuration / use |
|---|---|
| `.venv-ui` | Gradio `>=6.5,<7`, document/audio/image libraries in `requirements-ui.txt`. |
| `.venv-qwen` | PyTorch/torchaudio 2.6.0 CUDA 12.4; `qwen-tts==0.1.1`; Qwen 1.7B and 0.6B CustomVoice. |
| `.venv-chatterbox` | PyTorch/torchaudio 2.6.0 CUDA 12.4; `chatterbox-tts==0.1.7`; multilingual V3 or Turbo. |
| `.venv-kokoro` | PyTorch/torchaudio 2.6.0 CUDA 12.4; `kokoro>=0.9.4`; Windows may also need espeak-ng. |

These are the repository's configured versions, not a claim that they are the latest upstream releases. Recheck official compatibility before changing them.

Qwen exposes Aiden/Ryan here; custom tone instructions apply only to the 1.7B backend. Chatterbox requires an authorized reference recording. Kokoro offers the predefined voices listed in `app.py`. Models are downloaded on first use.

### Files, caching and preservation

Everything user-generated lives under `audiobooks/` (excluded from Git and the source ZIP). A job folder typically holds:

- `book.json`: source/model/voice/cache manifest.
- `chunks/*.wav`: raw reusable speech; keep these for resume/re-export.
- Task JSON, worker/export logs, FFmpeg concat/metadata files and cover artwork.
- Completed `.m4b` / `.mp3` files with readable book/chapter/voice/model/speed names.
- `export-index.json`: export settings signature to filename mapping.
- `library.json`: per-file edited title, author, notes, type, sample passage and settings.
- `latest-export.json`: latest export information.

Special subdirectories include `_audition-inputs`, `_cover-previews`, `_library-previews` and `_trash`. They are not ordinary library entries.

Narration cache keys include source bytes, model, voice, applicable instructions/reference, page/chapter selection, chunk size and seed. Speed, pauses, normalization and bitrate are export settings, so they reuse speech. Preserve the existing cache-key logic when possible; changing it can silently force expensive regeneration.

Library playback decodes a bounded excerpt for long M4B files, not the whole book into memory. Tag edits remux audio without re-encoding; audio/video streams are mapped explicitly and chapters are copied separately to avoid copying an incompatible chapter-data stream into M4B. The catalog constrains paths to its own output folders. File edits are blocked while conversion is active.

Trash moves the selected export into a recoverable folder and records its original location. It intentionally retains other exports and raw narration. It does not reclaim all disk space.

### Voice samples

The sample-bank button reads the same built-in passage for all predefined voices of the selected model at 1×, using the selected tone/seed/export settings. First setup requires synthesis. Matching saved preview files are reused without loading a model, even if the raw cache is not needed for replay.

Custom text or a selected book excerpt can also be previewed and saved. Chatterbox uses the single-preview flow with the user's recording. No real model samples are bundled in the source ZIP. Browser review audio is synthetic test data only.

## Run, update and test

### Existing user installation

1. Stop the conversion and close the old terminal.
2. Copy the contents of the new `VoicebookStudio` folder into the existing app folder, replacing source files.
3. Keep `audiobooks`, all `.venv-*` folders and downloaded model caches. Do not delete the old folder or nest another app folder inside it.
4. Double-click `start.bat`. Press Ctrl+F5 in the old browser tab if needed.

This theme/refresh fix needs no model reinstall. First-time installation uses Python 3.11 and `install.bat`; additional model installers are optional.

### Developer verification

From the app folder, using a Python environment with the UI requirements and NumPy:

```sh
python -m unittest discover -s tests -v
python tests/smoke_ui.py
python -m compileall -q app.py core.py worker.py jobs.py dashboard.py export_audio.py library_store.py naming.py theme.py
```

On Windows, substitute `.venv-ui\Scripts\python.exe` for `python` if necessary.

Browser review is optional developer tooling:

```sh
python -m pip install playwright
python -m playwright install chromium
python tests/visual_review.py
```

Set `VOICEBOOK_AXE_SCRIPT` to a local axe-core `axe.min.js` to enable the six text-contrast scans. `VOICEBOOK_SCREENSHOT_DIR` changes the screenshot output folder; default is `visual-review/` (ignored by Git). Fixtures are isolated in a temporary directory; no user book or model is required. Port 7861 is used by the API smoke script, 7863 by browser review; normal launch uses 7860.

For this update, 21 unit/integration tests and the API smoke flow were exercised. Chromium screenshot review covers running conversion, details, finished output, library, open menu, mobile, loading and errors. Text-contrast scans reported no violations on the six audited states; icon-only markers were reviewed visually. Browser/system light preference still renders the intended dark palette.

The build environment is Linux. Real GPU inference and native Windows launch were not rerun for this update. The user has previously confirmed conversion works on their laptop. Do not claim new GPU/Windows validation from the fake-worker tests or browser fixture screenshots.

## Remaining work and limitations

Prioritize reported user problems; these are possible follow-ups, not instructions to redesign the app:

1. Validate the update on the user's Windows/OneDrive installation: file locks, longer paths, actual GPU stop/resume and model loading. Do not reinstall working environments as a first troubleshooting step.
2. Preserve user-edited metadata during a same-settings full-book re-export. Currently the mapped export can be overwritten and regenerated tags/title can supersede edits. Consider explicit versioning or carrying edited metadata forward.
3. Sample-bank creation currently starts a worker per voice, so first-time generation may reload the model. Sharing a worker across voices could speed setup while retaining cancellation and dependency isolation.
4. File names are readable, but internal cache folder names remain fingerprinted for compatibility. Older exports are not automatically renamed.
5. Editing currently means title/author/notes/filename, not waveform editing or replacing narration text. Adding passage repair needs explicit cache invalidation and chapter-time rebuilding.
6. Original scanned PDFs need OCR. Complex extraction, footnotes, headers and EPUB section boundaries may need cleanup; the UI provides an extraction preview.
7. Jobs/queue state is not persisted across app restarts. Raw audio resume survives through matching cache settings.
8. Trash is recoverable and cache-preserving. A future disk-cleanup feature should explain what will be permanently removed.
9. Preview export signatures currently focus on audio/export settings; changing only cover artwork may require attention when deciding whether a saved preview is reusable.
10. The optional remote/ZeroGPU project has not been validated as a full-book service. Keep local laptop use working before expanding hosting.

## How to continue with Claude

Open this folder/repository, share this file plus the new error/screenshot or feature request, and ask Claude to inspect the relevant source before editing. A useful starting request is:

> Continue Voicebook Studio from CLAUDE_HANDOFF.md. Preserve my existing audiobooks, narration cache and model environments. Make the requested change in the complete app, verify the affected flow, inspect browser screenshots for UI changes, and provide a complete updated ZIP with clear update instructions.

Before publishing, inspect the current remote branch head and preserve unrelated changes. Package source/scripts/docs/tests only—never user books, recordings, model weights, virtual environments, credentials or temporary browser-review output.
