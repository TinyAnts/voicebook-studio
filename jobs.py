"""One local background job; browser polling never blocks model inference."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from core import (LIBRARY, ROOT, assemble, ffmpeg_binary, generate_tasks,
                  get_duration, plan_job, save_book_cover)
from export_audio import ExportCancelled
from naming import display_title, export_name, unique_path


def model_python(model):
    env = 'qwen' if model.startswith('qwen') else 'chatterbox' if model.startswith('chatter') else 'kokoro'
    path = ROOT / ('.venv-' + env) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not path.is_file():
        installer = 'install.bat' if env == 'qwen' else f'install-{env}.bat'
        raise RuntimeError(f'{env} is not installed. Run {installer}, then retry.')
    return path


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
                              model=options['model'], voice=options['voice'], speed=float(options['speed']),
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
            elif kind == 'chunk_start':
                s.update(current_index=event['index'], current_chapter=event.get('chapter', ''),
                         excerpt=event.get('text', ''), current_started_at=now)
            elif kind == 'chunk':
                index = int(event['index'])
                if index in done or index not in by_index:
                    return
                piece = by_index[index]
                done.add(index)
                s['completed'] += 1
                s['completed_chars'] += len(piece.text)
                s['generated_count'] += 1
                s['generated_chars'] += len(piece.text)
                s['generated_seconds'] += float(event.get('generation_seconds', 0))
                s['audio_seconds'] += float(event.get('audio_seconds', 0))
                s['vram_used_gb'] = event.get('vram_used_gb')
                s['message'] = f"Saved passage {s['completed']} of {s['total']}."
                for row in s['chapters']:
                    if row['title'] == piece.chapter:
                        row['done'] += 1
                        break
            elif kind == 'error':
                s['error'] = event.get('message', 'Speech generation failed.')

    def _run(self, options):
        try:
            voices=options.get('sample_voices') or [options['voice']]
            for index, voice in enumerate(voices,1):
                self.check_stop()
                self.update(voice=voice, sample_index=index, sample_total=len(voices),
                            generated_seconds=0., generated_chars=0, generated_count=0,
                            current_chapter='', excerpt='', export_fraction=0., finished_at=0, stage='prepare')
                self._convert({**options,'voice':voice,'batch_pending':index<len(voices)})
            if len(voices)>1:
                self.update(message=f'{len(voices)} voice samples are saved. Replay them in the voice sample list.')
        except Exception as exc:
            stopped = self.cancel.is_set() or isinstance(exc, ExportCancelled)
            message = ('Stopped. Finished passages are saved. Resume uses the same book and settings.'
                       if stopped else str(exc))
            self.update(status='stopped' if stopped else 'failed', message=message,
                        error='' if stopped else str(exc), finished_at=time.monotonic())
        finally:
            self.set_process(None)

    def _convert(self, o):
        model = o['model']
        preview = o['preview']
        ref = Path(o['reference']) if o.get('reference') and model.startswith('chatter') else None
        if model.startswith('chatter') and not ref:
            raise ValueError('Upload a clean 6–15 second narrator reference recording for Chatterbox.')
        ffmpeg_binary()
        if preview and not o['from_book']:
            text = o['audition_text'].strip()
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
            selection = [int(x) for x in o['chapters']]
        self.check_stop()
        folder, all_pieces, title = plan_job(
            source, model, o['voice'], o['instructions'], ref,
            int(o['first_page']) if source.suffix.lower() == '.pdf' else 1,
            int(o['last_page']) if source.suffix.lower() == '.pdf' else 0,
            int(o['chapter_pages']), int(o['chunk_chars']), int(o['seed']), selection)
        if source.suffix.lower() in ('.pdf', '.epub') or o.get('cover'):
            save_book_cover(source, folder, Path(o['cover']) if o.get('cover') else None)
        # A book excerpt is one short passage; a custom preview reads all entered text.
        pieces = all_pieces[:1] if preview and o['from_book'] else all_pieces
        title = display_title(source, preview and not o['from_book'])
        export_options = dict(speed=float(o['speed']), passage_gap=float(o['passage_gap']),
                              chapter_gap=float(o['chapter_gap']), normalize=bool(o['normalize']), bitrate=int(o['bitrate']))
        extension = 'mp3' if preview else o['format'].lower()
        export_key = hashlib.sha256(json.dumps({**export_options, 'kind':'preview' if preview else 'book',
                                               'extension':extension},sort_keys=True).encode()).hexdigest()
        index_file=folder/'export-index.json'
        try: export_index=json.loads(index_file.read_text(encoding='utf-8'))
        except (OSError,ValueError): export_index={}
        previous=export_index.get(export_key,'')
        existing=folder/previous if previous and Path(previous).name==previous else None
        if preview and existing and existing.is_file():
            self.update(title=title,folder=str(folder),status='running' if o.get('batch_pending') else 'done',
                        stage='export',message='Playing your saved sample. No new speech was generated.',
                        output=str(existing),audio=str(existing),finished_at=time.monotonic(),export_fraction=1.)
            return
        stem=export_name(title,pieces,model,o['voice'],float(o['speed']),preview,preview and not o['from_book'])
        destination=existing if existing and existing.is_file() else unique_path(folder,stem,extension)
        self.update(title=title)
        done = set()
        audio_seconds = 0.
        for p in pieces:
            self.check_stop()
            if p.wav.is_file() and p.wav.stat().st_size > 256:
                try:
                    duration = get_duration(p.wav)
                    if duration <= 0:
                        raise ValueError('empty audio')
                    done.add(p.index)
                    audio_seconds += duration
                except Exception:
                    # Only this generated, unusable cache item is discarded.
                    p.wav.unlink(missing_ok=True)
        rows = {}
        for p in pieces:
            row = rows.setdefault(p.chapter, dict(title=p.chapter, total=0, done=0))
            row['total'] += 1
            row['done'] += int(p.index in done)
        self.update(folder=str(folder), total=len(pieces), completed=len(done), cached=len(done),
                    total_chars=sum(len(p.text) for p in pieces),
                    completed_chars=sum(len(p.text) for p in pieces if p.index in done),
                    audio_seconds=audio_seconds, chapters=list(rows.values()))
        if ref:
            ref = folder / ('reference' + ref.suffix.lower())
        tasks_file = generate_tasks(folder, pieces, model, o['voice'], o['instructions'], int(o['seed']), ref)
        if len(done) < len(pieces):
            py = model_python(model)
            log_path = folder / 'worker.log'
            self.update(stage='loading', log_path=str(log_path), message='Starting the voice model. First use may download files…')
            self.check_stop()
            with log_path.open('w', encoding='utf-8') as log:
                process = subprocess.Popen([str(py), '-u', str(ROOT / 'worker.py'), '--tasks', str(tasks_file)],
                                           cwd=str(ROOT), stdout=subprocess.PIPE, stderr=log,
                                           text=True, encoding='utf-8', errors='replace', bufsize=1)
                self.set_process(process)
                by_index = {p.index: p for p in pieces}
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
                        raise RuntimeError(error + '\nFinished passages are saved. Retry to resume; for GPU memory errors try Qwen 0.6B.')
                finally:
                    if process.poll() is None:
                        process.terminate()
                        self._kill_if_needed(process)
                    process.stdout.close()
                    self.set_process(None)
        self.check_stop()
        if any(not p.wav.is_file() for p in pieces):
            raise RuntimeError('Some passages are missing. Retry to continue from the saved audio.')
        self.update(stage='export', export_fraction=0., log_path=str(destination.with_suffix('.export.log')),
                    message='Encoding audio, matching chapter times and embedding the cover…')

        def exported(fraction, seconds):
            self.update(export_fraction=fraction, export_seconds=seconds, last_progress_at=time.monotonic())

        assemble(folder, pieces, destination, title, **export_options, on_progress=exported,
                 on_process=self.set_process, cancel_event=self.cancel)
        listening = destination
        if not preview:
            self.update(stage='sample', message='Audiobook exported. Preparing the short listening sample…')
            listening = folder / f'listening-sample-{export_key[:7]}.mp3'
            self.update(log_path=str(listening.with_suffix('.export.log')))
            assemble(folder, pieces[:min(3, len(pieces))], listening, title + ' — excerpt', **export_options,
                     on_process=self.set_process, cancel_event=self.cancel)
        self.check_stop()
        export_index[export_key]=destination.name
        index_file.write_text(json.dumps(export_index,indent=2),encoding='utf-8')
        from library_store import record_export
        record_export(destination,title=title,kind='Voice preview' if preview else 'Audiobook',
                      excerpt=' '.join(p.text for p in pieces) if preview else '',chapter_names=list(rows),settings=export_options)
        (folder / 'latest-export.json').write_text(json.dumps({'output':str(destination), **export_options}, indent=2), encoding='utf-8')
        self.update(status='running' if o.get('batch_pending') else 'done', message='Your voice preview is ready.' if preview else 'Your audiobook is ready to download.',
                    output=str(destination), audio=str(listening), finished_at=time.monotonic(), export_fraction=1.)


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
