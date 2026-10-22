"""Download the three Qwen 1.7B voice models into HF_HOME (run by download-models.bat).

Windows without Developer Mode cannot make symlinks, and huggingface_hub's parallel download has a
race that sometimes tries anyway (WinError 1314). no_symlinks() makes it copy files instead.
"""
import os
import sys

os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')

REPOS = ('Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice',
         'Qwen/Qwen3-TTS-12Hz-1.7B-Base',
         'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign')


def no_symlinks():
    if os.name != 'nt':
        return
    try:
        from huggingface_hub import file_download
        file_download.are_symlinks_supported = lambda *a, **k: False
    except Exception:
        pass


def main():
    no_symlinks()
    from huggingface_hub import snapshot_download
    failed = []
    for repo in REPOS:
        print('== ' + repo, flush=True)
        try:
            snapshot_download(repo)
        except Exception as exc:  # keep going so the other models still download
            print(f'   FAILED: {exc}', flush=True)
            failed.append(repo)
    if failed:
        print('\nNot finished: ' + ', '.join(failed))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
