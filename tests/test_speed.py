"""Passage reuse across chapter selections, single-worker sample bank and worker helpers."""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import core
from jobs import JobManager
from test_progress import tone

BOOK = ('Chapter 1 The start\n' + 'The first chapter has a clear sentence. ' * 12 +
        '\nChapter 2 The middle\n' + 'The second chapter says something new. ' * 12 +
        '\nChapter 3 The end\n' + 'The third chapter closes the story. ' * 12)

COUNTING_WORKER = '''import json,sys,wave
from pathlib import Path
t=json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
with open(Path(__file__).with_name("runs.jsonl"),"a") as f: f.write(json.dumps(t)+"\\n")
def event(**d): print("VOICEBOOK_EVENT:"+json.dumps(d),flush=True)
event(type="engine",engine="test",batch_size=4)
event(type="status",stage="narrating",message="ready")
for i,item in enumerate(t["tasks"],1):
    event(type="chunk_start",index=item["index"],text=item["text"],chapter=item["chapter"],batch=1)
    p=Path(item["wav"]);p.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(p),"wb") as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b"\\0"*4800)
    event(type="chunk",done=i,index=item["index"],audio_seconds=.2,generation_seconds=.1)
'''


class TestPassageReuse(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / 'audiobooks'
        self.library.mkdir()
        self.patch = patch('core.LIBRARY', self.library)
        self.patch.start()
        self.book = self.root / 'Reuse Book.txt'
        self.book.write_text(BOOK, encoding='utf-8')

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def plan(self, selection, speaker='Aiden', seed=42):
        return core.plan_job(self.book, 'qwen17', speaker, 'calm', None, 1, 0, 10, 320, seed, selection)

    def test_new_chapter_selection_reuses_identical_passages(self):
        folder, pieces, _ = self.plan([0, 1, 2])
        for p in pieces:
            tone(p.wav, .2)
        other, subset, _ = self.plan([1, 2])
        self.assertNotEqual(folder, other)
        self.assertTrue(all(p.wav.is_file() for p in subset))
        # Different voice or seed must never reuse audio.
        _f, ryan, _ = self.plan([1], speaker='Ryan')
        self.assertFalse(any(p.wav.is_file() for p in ryan))
        _f, seeded, _ = self.plan([1], seed=7)
        self.assertFalse(any(p.wav.is_file() for p in seeded))

    def test_folders_from_older_versions_are_reused(self):
        folder, pieces, title = self.plan([0, 1, 2])
        (folder / 'passages.json').unlink()   # emulate an old job folder
        legacy = {'model': 'qwen17', 'speaker': 'Aiden', 'instruction': 'calm', 'seed': 42, 'reference': '',
                  'tasks': [{'index': p.index, 'text': p.text, 'chapter': p.chapter,
                             'wav': 'C:\\Users\\x\\VoicebookStudio\\audiobooks\\' + folder.name + '\\chunks\\' + p.wav.name}
                            for p in pieces]}
        (folder / 'tasks.json').write_text(json.dumps(legacy), encoding='utf-8')
        for p in pieces[:2]:
            tone(p.wav, .2)
        _other, subset, _ = self.plan([0])
        self.assertTrue(subset[0].wav.is_file())


class TestSampleBankUsesOneWorker(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / 'audiobooks'
        self.library.mkdir()
        (self.root / 'worker.py').write_text(COUNTING_WORKER, encoding='utf-8')
        self.patches = [patch('core.LIBRARY', self.library), patch('jobs.LIBRARY', self.library),
                        patch('jobs.ROOT', self.root), patch('jobs.model_python', return_value=Path(sys.executable))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_all_voices_generated_in_one_model_load(self):
        manager = JobManager()
        options = dict(preview=True, book=None, cover=None, chapters=[], model='qwen17', voice='Aiden',
                       reference=None, first_page=None, last_page=None, chapter_pages=10, chunk_chars=320,
                       instructions='calm', seed=42, format='M4B',
                       audition_text='A short shared passage for every narrator voice.', from_book=False,
                       speed=1.0, passage_gap=0, chapter_gap=1, normalize=False, bitrate=128,
                       sample_voices=['Aiden', 'Ryan'], engine='batched', batch_size=0)
        manager.start(options)
        manager.thread.join(30)
        s = manager.snapshot()
        self.assertEqual(s['status'], 'done', s)
        runs = [json.loads(x) for x in (self.root / 'runs.jsonl').read_text().splitlines()]
        self.assertEqual(len(runs), 1)
        self.assertEqual({t['speaker'] for t in runs[0]['tasks']}, {'Aiden', 'Ryan'})
        self.assertEqual(runs[0]['engine'], 'batched')
        self.assertEqual(len(list(self.library.glob('*/Preview - Voice sample - *.mp3'))), 2)
        # Second request reuses both saved samples without starting a worker.
        manager.start(options)
        manager.thread.join(30)
        self.assertEqual(manager.snapshot()['status'], 'done')
        self.assertEqual(len((self.root / 'runs.jsonl').read_text().splitlines()), 1)


class TestWorkerHelpers(unittest.TestCase):
    def test_token_cap_limits_runaway_generation(self):
        import worker
        self.assertEqual(worker.token_cap(['x' * 320]), 736)
        self.assertEqual(worker.token_cap(['x' * 5000]), 4096)
        self.assertEqual(worker.passage_seed(42, 'abc'), worker.passage_seed(42, 'abc'))

    def test_writer_thread_saves_wav_and_reports(self):
        import numpy as np
        import soundfile as sf
        import worker
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with redirect_stdout(out):
                w = worker.Writer(1)
                w.put({'index': 3, 'text': 'hello', 'wav': str(Path(d) / 'a.wav')},
                      np.ones(24000, dtype=np.float32) * .1, 24000, 1.5, None)
                w.close()
            data, sr = sf.read(str(Path(d) / 'a.wav'))
            self.assertEqual(sr, 24000)
            self.assertGreater(len(data), 24000)   # passage plus short pause
            self.assertIn('"type": "chunk"', out.getvalue())
            self.assertFalse((Path(d) / 'a.pending.wav').exists())


if __name__ == '__main__':
    unittest.main()


class TestNarratorLibrary(unittest.TestCase):
    def test_presets_resolve_to_clone_model(self):
        import voices
        values = [v for _l, v in voices.choices()]
        self.assertIn('Aiden', values)
        self.assertGreaterEqual(len([v for v in values if v.startswith('voice:')]), 10)
        model, name, ref, text = voices.resolve('voice:arthur')
        self.assertEqual((model, name), ('qwen17clone', 'Arthur'))
        self.assertTrue(Path(ref).is_file())
        self.assertEqual(text, voices.REFERENCE_TEXT)
        self.assertEqual(voices.resolve('Ryan')[:2], ('qwen17', 'Ryan'))


class TestMixedNarratorSampleBank(TestSampleBankUsesOneWorker):
    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_all_voices_generated_in_one_model_load(self):
        manager = JobManager()
        options = dict(preview=True, book=None, cover=None, chapters=[], model='qwen17', voice='Aiden',
                       reference=None, first_page=None, last_page=None, chapter_pages=10, chunk_chars=320,
                       instructions='calm', seed=42, format='M4B',
                       audition_text='A short shared passage for every narrator voice.', from_book=False,
                       speed=1.0, passage_gap=0, chapter_gap=1, normalize=False, bitrate=128,
                       sample_voices=['Aiden', 'voice:arthur', 'voice:sophie'], engine='auto', batch_size=0)
        manager.start(options)
        manager.thread.join(30)
        self.assertEqual(manager.snapshot()['status'], 'done', manager.snapshot())
        runs = [json.loads(x) for x in (self.root / 'runs.jsonl').read_text().splitlines()]
        self.assertEqual([r['model'] for r in runs], ['qwen17', 'qwen17clone'])   # one load per model type
        clone = runs[1]['tasks']
        self.assertEqual({t['speaker'] for t in clone}, {'Arthur', 'Sophie'})
        self.assertTrue(all(Path(t['reference']).is_file() and t['reference_text'] for t in clone))
        names = sorted(p.name for p in self.library.glob('*/Preview - Voice sample - *.mp3'))
        self.assertEqual(len(names), 3)
        self.assertTrue(any('Arthur' in n for n in names))


class TestFinishedFolder(TestSampleBankUsesOneWorker):
    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_all_voices_generated_in_one_model_load(self):
        """Full book + chapter files land in Finished/<Title - Author>/ with cover and tags."""
        import subprocess
        from PIL import Image
        book = self.root / 'The_Quiet_Valley_-_Ann_Writer.txt'
        book.write_text('Chapter 1 Morning\n' + 'The valley woke slowly under the sun. ' * 10 +
                        '\nChapter 2 Evening\n' + 'Night came and the lamps were lit. ' * 10, encoding='utf-8')
        cover = self.root / 'cover.png'
        Image.new('RGB', (64, 64), 'green').save(cover)
        options = dict(preview=False, book=str(book), cover=str(cover), chapters=['0', '1'], model='qwen17',
                       voice='Ryan', reference=None, first_page=1, last_page=0, chapter_pages=10, chunk_chars=320,
                       instructions='', seed=42, format='M4B', audition_text='', from_book=False,
                       speed=1.0, passage_gap=0, chapter_gap=1, normalize=True, bitrate=128,
                       engine='auto', batch_size=0, layout='both', chapter_format='mp3')
        manager = JobManager()
        manager.start(options)
        manager.thread.join(60)
        s = manager.snapshot()
        self.assertEqual(s['status'], 'done', s)
        folder = self.library / 'Finished' / 'The Quiet Valley - Ann Writer'
        self.assertTrue((folder / 'cover.jpg').is_file())
        self.assertIn('Author: Ann Writer', (folder / 'About.txt').read_text(encoding='utf-8'))
        full = list((folder / 'Full book').glob('*.m4b'))
        self.assertEqual([p.name for p in full], ['The Quiet Valley - Ann Writer - Full book - Ryan - Qwen 1.7B - 1x.m4b'])
        chapters = sorted((folder / 'Chapters').glob('*.mp3'))
        self.assertEqual([p.name for p in chapters], ['01 - Chapter 1 Morning.mp3', '02 - Chapter 2 Evening.mp3'])
        info = json.loads(subprocess.check_output(['ffprobe', '-v', 'quiet', '-of', 'json', '-show_format',
                                                   '-show_streams', str(chapters[1])]))
        tags = {k.lower(): v for k, v in info['format']['tags'].items()}
        self.assertEqual((tags['title'], tags['album'], tags['artist'], tags['track']), ('Chapter 2 Evening', 'The Quiet Valley', 'Ann Writer', '2/2'))
        self.assertTrue(any(st['codec_type'] == 'video' for st in info['streams']))   # embedded cover
        self.assertEqual(s['output_folder'], str(folder))
        # Library still lists the book once (the Finished folder is not a second entry).
        import library_store
        with patch('library_store.LIBRARY', self.library):
            self.assertEqual(len(library_store.entries(kind='Audiobook')), 1)


class TestFishEngine(unittest.TestCase):
    """The real worker talks to a stand-in Fish server over HTTP (no Docker or GPU needed)."""

    def setUp(self):
        import http.server
        import threading
        import io as _io
        import numpy as np
        import soundfile as sf
        self.requests = []
        test = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200 if self.path == '/v1/health' else 404)
                self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                test.requests.append(body)
                buf = _io.BytesIO()
                sf.write(buf, (np.sin(np.arange(44100) / 20) * .2).astype('float32'), 44100, format='WAV')
                data = buf.getvalue()
                self.send_response(200)
                self.send_header('Content-Type', 'audio/wav')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.temp = tempfile.TemporaryDirectory()
        self.library = Path(self.temp.name) / 'audiobooks'
        self.library.mkdir()
        self.patches = [patch('core.LIBRARY', self.library), patch('jobs.LIBRARY', self.library),
                        patch.dict('os.environ', {'VOICEBOOK_FISH_URL': f'http://127.0.0.1:{self.server.server_port}'})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.server.shutdown()
        self.temp.cleanup()

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_fish_preview_uses_narrator_reference(self):
        manager = JobManager()
        base = dict(preview=True, book=None, cover=None, chapters=[], model='qwen17', voice='voice:arthur',
                    reference=None, first_page=1, last_page=0, chapter_pages=10, chunk_chars=320, instructions='',
                    seed=42, format='M4B', audition_text='A short passage read by Fish for this test.', from_book=False,
                    speed=1.0, passage_gap=0, chapter_gap=1, normalize=True, bitrate=128, tts='fish')
        manager.start(base)
        manager.thread.join(60)
        s = manager.snapshot()
        self.assertEqual(s['status'], 'done', s)
        self.assertEqual(len(self.requests), 1)
        ref = self.requests[0]['references'][0]
        self.assertGreater(len(ref['audio']), 1000)        # base64 reference clip
        self.assertIn('old house', ref['text'])
        self.assertIn('Fish S2 Pro', s['output'])
        manager.start({**base, 'voice': 'Aiden'})            # built-in Qwen voices are refused for Fish
        manager.thread.join(30)
        self.assertEqual(manager.snapshot()['status'], 'failed')
        self.assertIn('library narrators', manager.snapshot()['message'])
