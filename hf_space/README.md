---
title: Voicebook Studio — Cloud Preview
emoji: 🎧
colorFrom: blue
colorTo: indigo
sdk: gradio
app_file: app.py
python_version: "3.12"
pinned: false
license: apache-2.0
short_description: Try premium-quality Qwen3-TTS voice narration on ZeroGPU.
---

# Voicebook Studio: Hugging Face ZeroGPU preview

This directory is a **standalone HF Space**; copy its `README.md`, `app.py`, and `requirements.txt` to the **root** of your own Space repository. It is intentionally a *short-preview app*, not a full-book cloud converter. It uses Qwen3-TTS 1.7B CustomVoice and supports Aiden and Ryan.

### Setup

1. Sign in at https://huggingface.co/spaces and create a **Gradio Space** in a personal account eligible for **ZeroGPU** (the current policy permits qualifying free accounts to host up to two ZeroGPU Spaces).
2. Choose **ZeroGPU** as the Space hardware in the hardware settings. The app won't run on CPU-only hardware because it explicitly loads the model onto CUDA.
3. Upload these three files to the root of the Space repository and allow the build to complete.
4. Visit your Space, optionally upload a *text-selectable* PDF, choose a page, generate one short WAV excerpt.
5. For privacy, create a **Private** Space if available; public Spaces expose their interface and uploaded content should be treated as hosted with a third party. Check HF security/privacy settings before using sensitive files.

The model loads once at Space startup and the `@spaces.GPU(duration=120)` decorator dynamically allocates the GPU. Expect queues, GPU quota errors, or version compatibility issues as HF infrastructure evolves. This deployment hasn't been tested on a live ZeroGPU Space.

**Quota (Oct 2026):** Hugging Face documentation lists 5 GPU-minutes per day for free signed-in accounts, with per-run limits and dynamic queues. The quota is for the user account, not 5 minutes per Space. This is deliberately not a full-book converter.

For whole books, the **local app** in the parent folder runs on your own laptop, handles PDF + EPUB + MP3/M4B, and lets you access it remotely through Tailscale Serve.
