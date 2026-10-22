"""One local background job; browser polling never blocks model inference."""
from __future__ import annotations

import copy
import hashlib
import shutil
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

import voices as narrators
from core import (Piece, LIBRARY, ROOT, assemble, ffmpeg_binary, generate_tasks,
                  get_duration, plan_job, save_book_cover)
from export_audio import ExportCancelled
from naming import book_info, clean_name, export_name, unique_path, MODEL_NAMES
from export_audio import split_chapters


ENGINES = ('auto', 'fast', 'batched', 'single')


def model_python(model, engine='auto'):
    """Pick the Python environment for a model. Qwen prefers the optional CUDA-graph
    environment (.venv-qwenfast) when installed, unless a standard engine was chosen."""
    if model == 'fish_s2':
        # Fish runs in Docker; the worker only sends HTTP requests, so the app's own Python is enough.
        import sys
        return Path(sys.executable)
    exe = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    if engine in ('auto', 'fast'):
        fast = ROOT / '.venv-qwenfast' / exe
        if fast.is_file():
            return fast
    path = ROOT / '.venv-qwen' / exe
    if not path.is_file():
        raise RuntimeError('Qwen is not installed. Run install.bat, then retry.')
    return path


def worker_environment():
    """Quieter, faster worker: hide harmless warnings that filled the activity log."""
    env = dict(os.environ)
    env.update(HF_HUB_DISABLE_SYMLINKS_WARNING='1', TRANSFORMERS_VERBOSITY='error',
               TOKENIZERS_PARALLELISM='false', PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
               HF_HUB_DISABLE_PROGRESS_BARS=env.get('HF_HUB_DISABLE_PROGRESS_BARS', '0'),
               PYTHONWARNINGS='ignore::UserWarning,ignore::FutureWarning')
    return env


class JobManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.process = None
        self.thread = None
        self.last_options = None
        self.maintenance = False
        self.state = dict(status='idle', stage='prepare', message='Upload a book or try a voice preview.',
                          job_id='', chapters=[], log_path='', audio=None, output=None,
                          total=0, completed=0, cached=0, started_at=0, finished_at=0,
                          device='Checking when a job starts', heartbeat_at=0, last_progress_at=0)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def update(self, **values):
        with self.lock:
            if 'stage' in values and values['stage'] != self.state.get('stage'):
                values['stage_started_at'] = time.monotonic()
            self.state.update(values)

    def start(self, options):
        with self.lock:
            if self.maintenance:
                raise RuntimeError('A library edit is being saved. Wait for it to finish before starting a job.')
            if self.state['status'] in ('running', 'stopping') or (self.thread is not None and self.thread.is_alive()):
                raise RuntimeError('A job is already running. Stop it before starting another.')
            self.cancel = threading.Event()
            self.last_options = copy.deepcopy(options)
            now = time.monotonic()
            self.state = dict(status='running', stage='prepare', message='Reading your settings and document…',
                              job_id=uuid.uuid4().hex, chapters=[], log_path='', audio=None, output=None,
                              total=0, completed=0, cached=0, started_at=now, finished_at=0,
                              stage_started_at=now, last_progress_at=now, heartbeat_at=0,
                              title='Voice preview' if options['preview'] else Path(options.get('book') or 'Audiobook').stem,
                              model='fish_s2' if options.get('tts') == 'fish' else options['model'], voice=options['voice'],
                              speed=float(options['speed']),
                              kind='Voice preview' if options['preview'] else 'Audiobook',
                              generated_seconds=0., generated_chars=0, generated_count=0,
                              total_chars=0, completed_chars=0, audio_seconds=0., export_fraction=0.,
                              current_index=0, current_chapter='', excerpt='', current_started_at=now,
                              device='Checking when the model starts', error='', folder='')
            self.thread = threading.Thread(target=self._run, args=(copy.deepcopy(options),), daemon=True)
            self.thread.start()
            return self.state['job_id']

    def retry(self):
        if not self.last_options:
            raise RuntimeError('No previous job to resume.')
        return self.start(self.last_options)

    def begin_library_edit(self):
        with self.lock:
            if self.maintenance or self.state['status'] in ('running', 'stopping') or (self.thread is not None and self.thread.is_alive()):
                raise RuntimeError('Wait for the current operation to finish, or stop the conversion before editing files.')
            self.maintenance = True

    def end_library_edit(self):
        with self.lock:
            self.maintenance = False

    def invalidate_output(self, path):
        # Do not keep exposing stale paths after a completed file is renamed or trashed.
        with self.lock:
            if self.state.get('output') == str(path):
                self.state.update(status='idle', audio=None, output=None, job_id=uuid.uuid4().hex,
                                  message='The saved file was updated. Open it in the library.')

    def stop(self):
        with self.lock:
            if self.state['status'] not in ('running', 'stopping'):
                return
            self.cancel.set()
            self.state.update(status='stopping', message='Stopping safely. Finished passages are kept…')
            proc = self.process
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
                # Never hold the UI response while waiting for a native process.
                threading.Thread(target=self._kill_if_needed, args=(proc,), daemon=True).start()

    @staticmethod
    def _kill_if_needed(proc):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass

    def set_process(self, process):
        with self.lock:
            self.process = process
            if process is not None and self.cancel.is_set() and process.poll() is None:
                process.terminate()

    def check_stop(self):
        if self.cancel.is_set():
            raise ExportCancelled('Stopped. Finished passages are saved; Resume continues this job.')

    def handle_event(self, event, by_index, done):
        """by_index maps worker task index -> Piece, or -> (Piece, chapter-row title)."""
        now = time.monotonic()
        kind = event.get('type')
        with self.lock:
            s = self.state
            s['heartbeat_at'] = now
            if kind == 'heartbeat':
                return
            s['last_progress_at'] = now
            if kind == 'status':
                self.update(stage=event.get('stage', s['stage']), message=event.get('message', ''))
            elif kind == 'device':
                s.update(device=event['device'], cuda=event.get('cuda'), vram_total_gb=event.get('vram_total_gb'))
            elif kind == 'engine':
                s.update(engine=event.get('engine', ''), batch_size=int(event.get('batch_size') or 1))
            elif kind == 'warning':
                s['warning'] = event.get('message', '')
                s['message'] = s['warning']
            elif kind == 'chunk_start':
                entry = by_index.get(int(event['index']))
                chapter = entry[1] if isinstance(entry, tuple) else event.get('chapter', '')
                s.update(current_index=event['index'], current_chapter=chapter,
                         excerpt=event.get('text', ''), current_started_at=now,
                         current_batch=int(event.get('batch') or 1))
            elif kind == 'chunk':
                index = int(event['index'])
                if index in done or index not in by_index:
                    return
                entry = by_index[index]
                piece, row_title = entry if isinstance(entry, tuple) else (entry, entry.chapter)
                done.add(index)
                s['completed'] += 1
                s['completed_chars'] += len(piece.text)
                s['generated_count'] += 1
                s['generated_chars'] += len(piece.text)
                s['generated_seconds'] += float(event.get('generation_seconds', 0))
                s['generated_audio_seconds'] = s.get('generated_audio_seconds', 0.) + float(event.get('audio_seconds', 0))
                s['audio_seconds'] += float(event.get('audio_seconds', 0))
                s['vram_used_gb'] = event.get('vram_used_gb')
                s['message'] = f"Saved passage {s['completed']} of {s['total']}."
                for row in s['chapters']:
                    if row['title'] == row_title:
                        row['done'] += 1
                        break
            elif kind == 'error':
                s['error'] = event.get('message', 'Speech generation failed.')

    def _run(self, options):
        try:
            if options.get('design'):
                self._design(options)
                return
            voices = options.get('sample_voices') or [options['voice']]
            plans = []
            for index, voice in enumerate(voices, 1):
                self.check_stop()
                self.update(voice=narrators.display_name(voice), sample_index=index, sample_total=len(voices), stage='prepare')
                plans.append(self._prepare({**options, 'voice': voice}))
            # One model load for everything that still needs speech (e.g. all voices of a sample bank).
            self._narrate([p for p in plans if not p['reuse']], options)
            for index, plan in enumerate(plans, 1):
                self.check_stop()
                self.update(voice=plan['voice'], sample_index=index, sample_total=len(plans))
                self._export(plan, batch_pending=index < len(plans))
            if len(voices) > 1:
                self.update(status='done', message=f'{len(voices)} voice samples are saved. Replay them in the voice sample list.')
        except Exception as exc:
            stopped = self.cancel.is_set() or isinstance(exc, ExportCancelled)
            message = ('Stopped. Finished passages are saved. Resume uses the same book and settings.'
                       if stopped else str(exc))
            self.update(status='stopped' if stopped else 'failed', message=message,
                        error='' if stopped else str(exc), finished_at=time.monotonic())
        finally:
            self.set_process(None)

    def _prepare(self, o):
        # The Narrator value decides the Qwen model: built-in speaker or a cloned library narrator.
        model, speaker, ref, ref_text = narrators.resolve(o['voice'])
        if o.get('tts') == 'fish':
            if not ref:
                raise ValueError('Fish S2 Pro reads with library narrators (Arthur, Eleanor, … or your own). '
                                 'Pick one of those instead of Aiden or Ryan.')
            model = 'fish_s2'
        preview = o['preview']
        ffmpeg_binary()
        if preview and not o['from_book']:
            text = (o.get('audition_text') or '').strip()
            if not 20 <= len(text) <= 1800:
                raise ValueError('Enter 20 to 1,800 characters for the voice preview.')
            source_dir = LIBRARY / '_audition-inputs'
            source_dir.mkdir(exist_ok=True)
            source = source_dir / ('voice-audition-' + hashlib.sha256(text.encode()).hexdigest()[:16] + '.txt')
            source.write_text(text, encoding='utf-8')
            selection = None
        else:
            if not o.get('book'):
                raise ValueError('Upload a book first, or turn off “Use selected book excerpt” for a voice preview.')
            if not o.get('chapters'):
                raise ValueError('Select at least one chapter.')
            source = Path(o['book'])
            if not source.is_file():
                raise ValueError('The uploaded book is no longer available (the app was restarted). Upload it again; saved passages are reused.')
            selection = [int(x) for x in o['chapters']]
        self.check_stop()
        is_pdf = source.suffix.lower() == '.pdf'
        folder, all_pieces, title = plan_job(
            source, model, speaker, o.get('instructions') or '', ref,
            as_int(o.get('first_page'), 1) if is_pdf else 1,
            as_int(o.get('last_page'), 0) if is_pdf else 0,
            as_int(o.get('chapter_pages'), 10), as_int(o.get('chunk_chars'), 320), as_int(o.get('seed'), 42), selection)
        if source.suffix.lower() in ('.pdf', '.epub') or o.get('cover'):
            save_book_cover(source, folder, Path(o['cover']) if o.get('cover') else None)
        # A book excerpt is one short passage; a custom preview reads all entered text.
        pieces = all_pieces[:1] if preview and o['from_book'] else all_pieces
        title, author = book_info(source, preview and not o['from_book'])
        try:
            manifest = json.loads((folder / 'book.json').read_text(encoding='utf-8'))
            full_book = len(manifest.get('selected_chapters', [])) == int(manifest.get('total_chapters', -1))
        except (OSError, ValueError, TypeError):
            full_book = False
        export_options = dict(speed=float(o['speed']), passage_gap=float(o['passage_gap']),
                              chapter_gap=float(o['chapter_gap']), normalize=bool(o['normalize']), bitrate=int(o['bitrate']))
        extension = 'mp3' if preview else str(o.get('format') or 'M4B').lower()
        export_key = hashlib.sha256(json.dumps({**export_options, 'kind': 'preview' if preview else 'book',
                                                'extension': extension}, sort_keys=True).encode()).hexdigest()
        index_file = folder / 'export-index.json'
        try:
            export_index = json.loads(index_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            export_index = {}
        previous = export_index.get(export_key, '')
        existing = folder / previous if previous and Path(previous).name == previous else None
        if ref:
            ref = folder / ('reference' + ref.suffix.lower())
        plan = dict(o=o, model=model, voice=speaker, ref_text=ref_text, preview=preview, folder=folder, pieces=pieces, title=title,
                    author=author, full_book=full_book and not preview,
                    ref=ref, export_options=export_options, extension=extension, export_key=export_key,
                    export_index=export_index, index_file=index_file, existing=existing,
                    reuse=bool(preview and existing and existing.is_file()))
        self.update(title=title, folder=str(folder))
        return plan

    def _narrate(self, plans, o):
        """Validate cached passages, then generate all missing ones with a single worker process."""
        done = set()
        by_index = {}
        rows = {}
        tasks = []
        cached = 0
        audio_seconds = 0.
        total_chars = completed_chars = 0
        multi = len(plans) > 1
        for plan in plans:
            for p in plan['pieces']:
                self.check_stop()
                row_title = f"{plan['voice']} — {p.chapter}" if multi else p.chapter
                row = rows.setdefault(row_title, dict(title=row_title, total=0, done=0))
                row['total'] += 1
                total_chars += len(p.text)
                ok = False
                if p.wav.is_file() and p.wav.stat().st_size > 256:
                    try:
                        duration = get_duration(p.wav)
                        if duration <= 0:
                            raise ValueError('empty audio')
                        ok = True
                        audio_seconds += duration
                    except Exception:
                        # Only this generated, unusable cache item is discarded.
                        p.wav.unlink(missing_ok=True)
                if ok:
                    cached += 1
                    row['done'] += 1
                    completed_chars += len(p.text)
                else:
                    gid = len(tasks) + 1
                    by_index[gid] = (p, row_title)
                    tasks.append({'index': gid, 'text': p.text, 'wav': str(p.wav), 'chapter': row_title,
                                  'speaker': plan['voice'], 'reseed': p.reseed, 'model': plan['model'],
                                  'reference': str(plan['ref']) if plan['ref'] else '',
                                  'reference_text': plan.get('ref_text') or ''})
        total = sum(len(p['pieces']) for p in plans)
        self.update(total=total, completed=cached, cached=cached, total_chars=total_chars,
                    completed_chars=completed_chars, audio_seconds=audio_seconds, chapters=list(rows.values()))
        for plan in plans:  # keep a per-folder record of the passages (also used for reuse by older code)
            generate_tasks(plan['folder'], plan['pieces'], plan['model'], plan['voice'], plan['o'].get('instructions') or '',
                           as_int(plan['o'].get('seed'), 42), plan['ref'])
        if not tasks:
            return
        engine = str(o.get('engine') or 'auto').lower()
        engine = engine if engine in ENGINES else 'auto'
        # One worker (one model load) per Qwen model type, e.g. built-in voices then cloned narrators.
        for model in dict.fromkeys(t['model'] for t in tasks):
            group = [t for t in tasks if t['model'] == model]
            lead = next(p for p in plans if p['model'] == model)
            payload = {'model': model, 'speaker': lead['voice'], 'instruction': lead['o'].get('instructions') or '',
                       'seed': as_int(lead['o'].get('seed'), 42), 'reference': str(lead['ref']) if lead['ref'] else '',
                       'reference_text': lead.get('ref_text') or '',
                       'engine': engine, 'batch_size': as_int(o.get('batch_size'), 0), 'tasks': group}
            self._run_worker(payload, lead['folder'], by_index, done)

    def _organize(self, plan, destination, tags):
        """audiobooks/Finished/<Title - Author>/ with cover.jpg, About.txt, 'Full book' and 'Chapters'."""
        o, title, author = plan['o'], plan['title'], plan['author']
        layout = str(o.get('layout') or 'both')
        book_dir = LIBRARY / 'Finished' / clean_name(f'{title} - {author}' if author else title, 120)
        book_dir.mkdir(parents=True, exist_ok=True)
        cover = plan['folder'] / 'cover.jpg'
        if cover.is_file():
            shutil.copyfile(cover, book_dir / 'cover.jpg')
        record_file = book_dir / '.voicebook.json'
        try:
            record = json.loads(record_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            record = {}
        if layout in ('both', 'full'):
            full_dir = book_dir / 'Full book'
            full_dir.mkdir(exist_ok=True)
            link_or_copy(destination, full_dir / destination.name)
        chapter_files = []
        if layout in ('both', 'chapters'):
            self.update(stage='sample', message='Making one file per chapter…')
            chapters_dir = book_dir / 'Chapters'
            for old in record.get('chapter_files', []):   # replace the previous set we made
                (chapters_dir / Path(old).name).unlink(missing_ok=True)
            fmt = str(o.get('chapter_format') or 'm4b').lower()
            if fmt == destination.suffix.lower().lstrip('.'):
                fmt = 'same'   # same format as the full book: split without re-encoding (instant)
            chapter_files = split_chapters(destination, chapters_dir, title=title, author=author,
                                           comment=tags.get('comment', ''), cover=cover if cover.is_file() else None,
                                           fmt=None if fmt == 'same' else fmt, bitrate=int(o.get('bitrate') or 128),
                                           on_process=self.set_process, cancel_event=self.cancel)
        record.update(title=title, author=author, narrator=plan['voice'], full_book=destination.name)
        if layout != 'full':
            record['chapter_files'] = [p.name for p in chapter_files]
        record_file.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding='utf-8')
        try:
            marks = json.loads(destination.with_suffix('.chapters.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            marks = []
        lines = [f'Title: {title}', f'Author: {author or "not stated"}',
                 f"Narrator: {plan['voice']} ({MODEL_NAMES.get(plan['model'], plan['model'])}, Voicebook Studio)",
                 f"Speed: {float(o.get('speed') or 1):g}x", f'Made: {time.strftime("%Y-%m-%d %H:%M")}', '', 'Chapters:']
        for n, m in enumerate(marks, 1):
            length = int(float(m['end']) - float(m['start']))
            lines.append(f"{n:02d}. {m['title']}  ({length // 3600}:{length % 3600 // 60:02d}:{length % 60:02d})")
        total = int(marks[-1]['end']) if marks else 0
        lines += ['', f'Total length: {total // 3600}h {total % 3600 // 60:02d}m']
        (book_dir / 'About.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return book_dir

    def _run_worker(self, payload, folder, by_index, done):
        tasks_file = folder / 'worker-tasks.json'
        tasks_file.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
        py = model_python(payload['model'], payload.get('engine', 'auto'))
        log_path = folder / 'worker.log'
        self.update(stage='loading', log_path=str(log_path), engine='', batch_size=0,
                    message='Starting the voice model. First use downloads it (about 4.5 GB)…')
        self.check_stop()
        with log_path.open('w', encoding='utf-8') as log:
            log.write(f'Python: {py}\n(SoX / flash-attn notices below are harmless.)\n')
            log.flush()
            creation = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            process = subprocess.Popen([str(py), '-u', str(ROOT / 'worker.py'), '--tasks', str(tasks_file)],
                                       cwd=str(ROOT), stdout=subprocess.PIPE, stderr=log, env=worker_environment(),
                                       text=True, encoding='utf-8', errors='replace', bufsize=1,
                                       creationflags=creation)
            self.set_process(process)
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    self.check_stop()
                    if line.startswith('VOICEBOOK_EVENT:'):
                        try:
                            event = json.loads(line[len('VOICEBOOK_EVENT:'):])
                        except json.JSONDecodeError:
                            continue
                        self.handle_event(event, by_index, done)
                    else:
                        log.write(line)
                        log.flush()
                code = process.wait()
                self.check_stop()
                if code:
                    error = self.snapshot().get('error') or read_log(str(log_path))[-1800:] or 'Speech worker exited unexpectedly.'
                    hint = ('Finished passages are saved. Retry to resume.' if payload.get('model') == 'fish_s2' else
                            'Finished passages are saved. Retry to resume; for GPU memory errors '
                            'lower “Passages per GPU batch”.')
                    raise RuntimeError(error + '\n' + hint)
            finally:
                if process.poll() is None:
                    process.terminate()
                    self._kill_if_needed(process)
                process.stdout.close()
                self.set_process(None)

    def _design(self, o):
        """Create a new narrator from a written description (Qwen VoiceDesign), then save it."""
        name = ' '.join(str(o.get('design_name') or '').split())[:40]
        description = ' '.join(str(o.get('design_description') or '').split())
        if not name:
            raise ValueError('Give the new narrator a name.')
        if not 15 <= len(description) <= 600:
            raise ValueError('Describe the voice in 15–600 characters (age, gender, accent, tone).')
        folder = narrators.new_custom_folder(name)
        try:
            wav = folder / 'reference.wav'
            item = {'index': 1, 'text': narrators.REFERENCE_TEXT, 'wav': str(wav), 'chapter': 'Narrator design',
                    'instruct': description, 'raw': True}
            self.update(title=f'New narrator: {name}', voice=name, model='design17', total=1, completed=0, cached=0, folder=str(folder),
                        total_chars=len(item['text']), completed_chars=0,
                        chapters=[dict(title='Narrator design', total=1, done=0)])
            piece = Piece('Narrator design', item['text'], 1, wav)
            payload = {'model': 'design17', 'seed': as_int(o.get('seed'), 42), 'engine': str(o.get('engine') or 'auto'),
                       'batch_size': 1, 'tasks': [item]}
            self._run_worker(payload, folder, {1: piece}, set())
            if not wav.is_file():
                raise RuntimeError('The narrator recording was not created. Try again.')
            value = narrators.save_custom(folder, name, description[:70], narrators.REFERENCE_TEXT, description)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        self.update(status='done', stage='export', export_fraction=1., finished_at=time.monotonic(),
                    message=f'Narrator “{name}” is ready. It is selected in the Narrator list — generate a preview to hear it read your book.',
                    audio=str(wav), output=str(wav), new_voice=value)

    def _export(self, plan, batch_pending=False):
        o, preview, folder, pieces, title = plan['o'], plan['preview'], plan['folder'], plan['pieces'], plan['title']
        existing, export_options, export_key = plan['existing'], plan['export_options'], plan['export_key']
        if plan['reuse']:
            self.update(title=title, folder=str(folder), status='running' if batch_pending else 'done',
                        stage='export', message='Playing your saved sample. No new speech was generated.',
                        output=str(existing), audio=str(existing), finished_at=time.monotonic(), export_fraction=1.)
            return
        self.check_stop()
        if any(not p.wav.is_file() for p in pieces):
            raise RuntimeError('Some passages are missing. Retry to continue from the saved audio.')
        stem = export_name(title, pieces, plan['model'], plan['voice'], float(o['speed']), preview,
                           preview and not o['from_book'], author=plan['author'], full_book=plan['full_book'])
        tags = dict(author=plan['author'],
                    comment=f"Narrated by {plan['voice']} ({MODEL_NAMES.get(plan['model'], plan['model'])}) with Voicebook Studio")
        destination = existing if existing and existing.is_file() else unique_path(folder, stem, plan['extension'])
        self.update(title=title, folder=str(folder), stage='export', export_fraction=0.,
                    log_path=str(destination.with_suffix('.export.log')),
                    message='Encoding audio, matching chapter times and embedding the cover…')

        def exported(fraction, seconds):
            self.update(export_fraction=fraction, export_seconds=seconds, last_progress_at=time.monotonic())

        assemble(folder, pieces, destination, title, **export_options, **tags, on_progress=exported,
                 on_process=self.set_process, cancel_event=self.cancel)
        listening = destination
        if not preview:
            self.update(stage='sample', message='Audiobook exported. Preparing the short listening sample…')
            listening = folder / f'listening-sample-{export_key[:7]}.mp3'
            self.update(log_path=str(listening.with_suffix('.export.log')))
            assemble(folder, pieces[:min(3, len(pieces))], listening, title + ' — excerpt', **export_options, **tags,
                     on_process=self.set_process, cancel_event=self.cancel)
        self.check_stop()
        if not preview:
            plan['finished_dir'] = str(self._organize(plan, destination, tags))
        export_index = plan['export_index']
        export_index[export_key] = destination.name
        plan['index_file'].write_text(json.dumps(export_index, indent=2), encoding='utf-8')
        from library_store import record_export
        chapter_names = list(dict.fromkeys(p.chapter for p in pieces))
        record_export(destination, title=title, author=plan['author'], kind='Voice preview' if preview else 'Audiobook',
                      finished_dir=plan.get('finished_dir', ''),
                      excerpt=' '.join(p.text for p in pieces) if preview else '', chapter_names=chapter_names,
                      settings=export_options)
        (folder / 'latest-export.json').write_text(json.dumps({'output': str(destination), **export_options}, indent=2), encoding='utf-8')
        self.update(status='running' if batch_pending else 'done',
                    message='Your voice preview is ready.' if preview else
                    f'Your audiobook is ready in audiobooks\\Finished\\{Path(plan["finished_dir"]).name}',
                    output_folder=plan.get('finished_dir', ''),
                    output=str(destination), audio=str(listening), finished_at=time.monotonic(), export_fraction=1.)


def link_or_copy(source, target):
    """Hard link when possible (no extra disk space), otherwise copy."""
    target = Path(target)
    temp = target.with_name(target.name + '.partial')
    temp.unlink(missing_ok=True)
    try:
        os.link(source, temp)
    except OSError:
        shutil.copyfile(source, temp)
    temp.replace(target)


def as_int(value, default=0):
    """Gradio sends None for cleared number boxes."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_log(path, limit=6000):
    if not path:
        return ''
    try:
        with Path(path).open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-limit))
            return stream.read().decode('utf-8', errors='replace').replace('\r', '\n')
    except OSError:
        return ''


MANAGER = JobManager()
