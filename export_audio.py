"""Streaming, cancellable audio export with correctly timed chapter markers."""
from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path


class ExportCancelled(RuntimeError):
    pass


def _escape(value):
    return str(value).replace('\\', '\\\\').replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\n', ' ')


def export_audio(folder, pieces, destination, title, cover=None, *, speed=1.0,
                 passage_gap=0.0, chapter_gap=0.0, normalize=True, bitrate=128,
                 on_progress=None, on_process=None, cancel_event=None):
    from core import _ffconcat_path, ffmpeg_binary
    import soundfile as sf

    speed, passage_gap, chapter_gap = map(float, (speed, passage_gap, chapter_gap))
    if not all(math.isfinite(v) for v in (speed, passage_gap, chapter_gap)):
        raise ValueError('Export settings must be finite numbers.')
    if not .75 <= speed <= 1.5 or not 0 <= passage_gap <= 1 or not 0 <= chapter_gap <= 5:
        raise ValueError('Speed must be 0.75–1.5×; passage pause 0–1 s; chapter pause 0–5 s.')
    if int(bitrate) not in (96, 128, 192):
        raise ValueError('Choose 96, 128 or 192 kbps.')
    if not pieces:
        raise ValueError('Nothing to export.')

    def check_stop():
        if cancel_event is not None and cancel_event.is_set():
            raise ExportCancelled('Stopped; completed narration is saved.')

    check_stop()
    silence_dir = folder / '_export-silence'
    silence_dir.mkdir(exist_ok=True)
    concat = ['ffconcat version 1.0']
    markers = []
    seconds = 0.0
    for i, piece in enumerate(pieces):
        check_stop()
        info = sf.info(str(piece.wav))
        if not info.frames:
            raise ValueError('An audio passage is empty. Regenerate it before exporting.')
        if not markers or markers[-1][0] != piece.chapter:
            if markers:
                markers[-1][2] = seconds
            markers.append([piece.chapter, seconds, seconds])
        concat.append(f'file {_ffconcat_path(piece.wav)}')
        seconds += info.frames / info.samplerate / speed
        if i + 1 < len(pieces):
            gap = chapter_gap if pieces[i + 1].chapter != piece.chapter else passage_gap
            # Atempo also affects silence. Compensate so the selected pause is
            # the duration heard in the exported file at any narration speed.
            frames = round(gap * speed * info.samplerate)
            if frames:
                silence = silence_dir / f'{info.samplerate}-{info.channels}-{frames}.wav'
                if not silence.exists():
                    with wave.open(str(silence), 'wb') as wav:
                        wav.setnchannels(info.channels)
                        wav.setsampwidth(2)
                        wav.setframerate(info.samplerate)
                        wav.writeframes(b'\0' * frames * info.channels * 2)
                concat.append(f'file {_ffconcat_path(silence)}')
                seconds += frames / info.samplerate / speed
    markers[-1][2] = seconds
    # Distinct files keep the main export and short listening sample auditable.
    list_file = destination.with_suffix('.ffconcat')
    list_file.write_text('\n'.join(concat) + '\n', encoding='utf-8')
    metadata = [';FFMETADATA1', f'title={_escape(title)}', 'artist=Voicebook Studio']
    for heading, start, end in markers:
        metadata.extend(['[CHAPTER]', 'TIMEBASE=1/1000', f'START={round(start*1000)}',
                         f'END={round(end*1000)}', f'title={_escape(heading)}'])
    meta_file = destination.with_suffix('.ffmeta')
    meta_file.write_text('\n'.join(metadata) + '\n', encoding='utf-8')
    output = destination.with_name(destination.stem + '.partial' + destination.suffix)
    cmd = [ffmpeg_binary(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
           '-safe', '0', '-f', 'concat', '-i', str(list_file),
           '-f', 'ffmetadata', '-i', str(meta_file)]
    artwork = cover or folder / 'cover.jpg'
    if artwork.is_file():
        cmd.extend(['-i', str(artwork)])
    cmd.extend(['-map', '0:a:0'])
    if artwork.is_file():
        cmd.extend(['-map', '2:v:0', '-c:v', 'mjpeg', '-disposition:v:0', 'attached_pic',
                    '-metadata:s:v:0', 'title=Album cover', '-metadata:s:v:0', 'comment=Cover (front)'])
    filters = [f'atempo={speed:.6f}']
    if normalize:
        filters.append('loudnorm=I=-18:TP=-2:LRA=11')
        # Some FFmpeg builds emit NaNs for an entirely silent, very short input.
        filters.append("aeval=exprs='if(isnan(val(ch)),0,clip(val(ch),-1,1))':c=same")
    cmd.extend(['-map_metadata', '1', '-map_chapters', '1', '-af', ','.join(filters)])
    if destination.suffix.lower() == '.m4b':
        cmd.extend(['-c:a', 'aac', '-b:a', f'{int(bitrate)}k', '-f', 'ipod'])
    else:
        cmd.extend(['-c:a', 'libmp3lame', '-b:a', f'{int(bitrate)}k', '-id3v2_version', '3', '-f', 'mp3'])
    cmd.extend(['-progress', 'pipe:1', '-nostats', str(output)])
    proc = None
    log_path = destination.with_suffix('.export.log')
    try:
        with log_path.open('w', encoding='utf-8') as log:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log,
                                    text=True, encoding='utf-8', errors='replace', bufsize=1)
            if on_process:
                on_process(proc)
            assert proc.stdout is not None
            for line in proc.stdout:
                check_stop()
                if line.startswith('out_time_us=') and on_progress:
                    try:
                        done = int(line.partition('=')[2]) / 1_000_000
                    except ValueError:
                        continue
                    on_progress(min(.999, max(0.0, done / seconds)), done)
            code = proc.wait()
        check_stop()
        if code:
            raise RuntimeError('Audio export failed: ' + log_path.read_text(encoding='utf-8', errors='replace')[-1800:])
        output.replace(destination)
        if on_progress:
            on_progress(1.0, seconds)
        return destination
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            if proc.stdout is not None:
                proc.stdout.close()
        if on_process:
            on_process(None)
        output.unlink(missing_ok=True)
