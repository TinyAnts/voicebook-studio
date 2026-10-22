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


def speech_gain_db(paths, target_db=-20.0):
    """Gain (dB) that brings the book's speech level to about -20 dBFS RMS (~ -18 LUFS for speech).

    Reads each WAV once with NumPy; ignores pauses (frames quieter than -45 dBFS).
    """
    import soundfile as sf
    power, count = 0.0, 0
    for path in dict.fromkeys(str(p) for p in paths):
        try:
            data, sr = sf.read(path, dtype='float32', always_2d=True)
        except Exception:
            continue
        mono = data.mean(axis=1)
        frame = max(1, int(sr * 0.05))
        usable = len(mono) // frame * frame
        if not usable:
            continue
        frames = (mono[:usable].reshape(-1, frame) ** 2).mean(axis=1)
        voiced = frames[frames > 10 ** (-45 / 10)]
        power += float(voiced.sum())
        count += int(voiced.size)
    if not count:
        return 0.0
    level = 10 * math.log10(power / count)
    return max(-12.0, min(12.0, target_db - level))


def split_chapters(book, out_dir, *, title, author='', comment='', cover=None, fmt=None, bitrate=128,
                   on_process=None, cancel_event=None):
    """Cut one file per chapter from a finished M4B/MP3 using stream copy (seconds, not minutes).

    Uses the chapter times saved next to the book. Returns the created paths in order.
    """
    import json
    import re
    from core import ffmpeg_binary
    book = Path(book)
    marks = json.loads(book.with_suffix('.chapters.json').read_text(encoding='utf-8'))
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = '.' + (fmt or book.suffix.lstrip('.')).lower()
    copy = ext == book.suffix.lower()   # same format: no re-encoding, takes seconds
    created = []
    total = len(marks)
    for n, mark in enumerate(marks, 1):
        if cancel_event is not None and cancel_event.is_set():
            raise ExportCancelled('Stopped; completed narration is saved.')
        name = re.sub(r'^\d+\s*·\s*', '', str(mark['title'])).strip() or f'Chapter {n}'
        from naming import clean_name
        target = out_dir / f'{n:02d} - {clean_name(name, 80)}{ext}'
        partial = target.with_name(target.stem + '.partial' + ext)
        length = max(0.05, float(mark['end']) - float(mark['start']))
        cmd = [ffmpeg_binary(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
               '-ss', f"{float(mark['start']):.3f}", '-t', f'{length:.3f}', '-i', str(book)]
        art = cover if cover and Path(cover).is_file() else None
        if art:
            cmd += ['-i', str(art)]
        codec = ['copy'] if copy else (['aac', '-b:a', f'{int(bitrate)}k'] if ext == '.m4b'
                                        else ['libmp3lame', '-b:a', f'{int(bitrate)}k'])
        cmd += ['-map', '0:a:0', '-c:a', *codec, '-map_metadata', '-1', '-map_chapters', '-1']
        if art:
            cmd += ['-map', '1:v:0', '-c:v', 'mjpeg', '-disposition:v:0', 'attached_pic']
        for key, value in (('title', name), ('album', title), ('artist', author or 'Voicebook Studio'),
                           ('album_artist', author or 'Voicebook Studio'), ('track', f'{n}/{total}'),
                           ('genre', 'Audiobook'), ('comment', comment)):
            if value:
                cmd += ['-metadata', f'{key}={value}']
        cmd += (['-f', 'ipod'] if ext == '.m4b' else ['-id3v2_version', '3', '-f', 'mp3']) + [str(partial)]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                encoding='utf-8', errors='replace')
        if on_process:
            on_process(proc)
        try:
            _out, err = proc.communicate()
        finally:
            if on_process:
                on_process(None)
        if proc.returncode or not partial.is_file():
            partial.unlink(missing_ok=True)
            raise RuntimeError(f'Could not create chapter file {target.name}: {err[-500:]}')
        partial.replace(target)
        created.append(target)
    return created


def export_audio(folder, pieces, destination, title, cover=None, *, speed=1.0,
                 passage_gap=0.0, chapter_gap=0.0, normalize=True, bitrate=128,
                 on_progress=None, on_process=None, cancel_event=None, author='', comment=''):
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
    # Chapter times are kept so chapter files can be cut from the finished book without re-encoding.
    import json
    destination.with_suffix('.chapters.json').write_text(
        json.dumps([{'title': t, 'start': a, 'end': b} for t, a, b in markers], ensure_ascii=False, indent=1),
        encoding='utf-8')
    # Distinct files keep the main export and short listening sample auditable.
    list_file = destination.with_suffix('.ffconcat')
    list_file.write_text('\n'.join(concat) + '\n', encoding='utf-8')
    metadata = [';FFMETADATA1', f'title={_escape(title)}', f'album={_escape(title)}',
                f'artist={_escape(author or "Voicebook Studio")}', f'album_artist={_escape(author or "Voicebook Studio")}',
                'genre=Audiobook', f'comment={_escape(comment or "Narrated with Voicebook Studio")}']
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
    filters = [f'atempo={speed:.6f}'] if abs(speed - 1) > 1e-6 else []
    if normalize:
        # One measured gain for the whole book plus a peak limiter. Same listening level as the
        # old single-pass loudnorm filter at about a third of the encoding time (loudnorm
        # resamples everything to 192 kHz internally).
        gain = speech_gain_db([p.wav for p in pieces])
        filters.extend([f'volume={gain:.2f}dB', 'alimiter=limit=0.89:level=false'])
    if not filters:
        filters.append('anull')
    cmd.extend(['-map_metadata', '1', '-map_chapters', '1', '-af', ','.join(filters), '-ar', '44100'])
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
