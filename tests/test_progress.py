import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import core
from dashboard import narration_eta, render_status
from jobs import JobManager
from export_audio import ExportCancelled


def tone(path, seconds=1.0, rate=24000):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b''.join(struct.pack('<h', int(4000*math.sin(2*math.pi*600*i/rate))) for i in range(int(seconds*rate))))


class TestProgress(unittest.TestCase):
    def test_eta_uses_generated_work_not_cached_passages_or_model_loading(self):
        s=dict(stage='narrating',generated_count=2,generated_chars=400,
               generated_seconds=20,total_chars=1400,completed_chars=1000,current_started_at=98)
        self.assertEqual(narration_eta(s,100),18)
        self.assertIsNone(narration_eta({**s,'generated_count':1},100))
        self.assertIsNone(narration_eta({**s,'stage':'loading'},100))

    def test_loading_is_indeterminate_and_book_text_is_escaped(self):
        s=JobManager().snapshot()
        s.update(status='running',stage='loading',title='<script>alert(1)</script>',started_at=10,
                 message='<img onerror=alert(1)>',speed=1,kind='Audiobook')
        markup=render_status(s,20)
        self.assertIn('&lt;script&gt;',markup)
        self.assertNotIn('<script>',markup)
        self.assertNotIn('max="100"',markup)
        self.assertIn('Loading or downloading',markup)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_speed_and_pauses_preserve_pitch_and_chapter_timing(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            pieces=[]
            for i in range(3):
                wav=folder/f'{i}.wav'
                tone(wav)
                pieces.append(core.Piece('A' if i<2 else 'B','hello',i+1,wav))
            progress=[]
            output=core.assemble(folder,pieces,folder/'book.m4b','Title; = #',speed=1.25,
                                 passage_gap=.2,chapter_gap=1,normalize=False,
                                 on_progress=lambda fraction,seconds:progress.append(fraction))
            metadata=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-of','json','-show_chapters','-show_format',str(output)]))
            self.assertAlmostEqual(float(metadata['chapters'][1]['start_time']),2.8,delta=.015)
            self.assertAlmostEqual(float(metadata['format']['duration']),3.6,delta=.10)
            self.assertEqual(metadata['format']['tags']['title'],'Title; = #')
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-t','0.5','-f','f32le','-ac','1','-ar','24000','pipe:1'])
            samples=np.frombuffer(raw,dtype=np.float32)
            peak=np.fft.rfftfreq(len(samples),1/24000)[np.argmax(abs(np.fft.rfft(samples)))]
            self.assertAlmostEqual(peak,600,delta=10)
            self.assertEqual(progress[-1],1)

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_silent_passages_do_not_break_normalization(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);wav=folder/'silence.wav'
            with wave.open(str(wav),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000);out.writeframes(b'\0'*24000)
            pieces=[core.Piece('A','silent',1,wav),core.Piece('A','silent',2,wav)]
            result=core.assemble(folder,pieces,folder/'silence.m4b','Silence',speed=1.1,passage_gap=.1,normalize=True)
            self.assertGreater(result.stat().st_size,500)

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_cancel_export_keeps_existing_output_and_wavs(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            wav=folder/'voice.wav';tone(wav,2)
            destination=folder/'book.mp3';destination.write_bytes(b'existing completed book')
            cancel=threading.Event()
            def cancel_on_launch(proc):
                if proc is not None:
                    cancel.set();proc.terminate()
            with self.assertRaises(ExportCancelled):
                core.assemble(folder,[core.Piece('A','hello',1,wav)],destination,'book',
                              on_process=cancel_on_launch,cancel_event=cancel)
            self.assertEqual(destination.read_bytes(),b'existing completed book')
            self.assertTrue(wav.exists())
            self.assertFalse((folder/'book.partial.mp3').exists())


FAKE_WORKER = '''import json,sys,time,wave
from pathlib import Path
t=json.loads(Path(sys.argv[-1]).read_text())
def event(**data): print('VOICEBOOK_EVENT:'+json.dumps(data),flush=True)
event(type='status',stage='narrating',message='Test model ready')
for i,item in enumerate(t['tasks'],1):
 event(type='chunk_start',index=item['index'],text=item['text'],chapter=item['chapter'])
 time.sleep(.3)
 p=Path(item['wav']);p.parent.mkdir(parents=True,exist_ok=True)
 with wave.open(str(p),'wb') as f:
  f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b'\\0'*4800)
 event(type='chunk',done=i,index=item['index'],audio_seconds=.1,generation_seconds=.3)
'''


class TestJobLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.library=self.folder/'audiobooks';self.library.mkdir()
        (self.folder/'worker.py').write_text(FAKE_WORKER)
        self.book=self.folder/'test.txt'
        self.book.write_text('A clear sentence for this test story. '*25)
        self.patches=[patch('core.LIBRARY',self.library),patch('jobs.LIBRARY',self.library),
                      patch('jobs.ROOT',self.folder),patch('jobs.model_python',return_value=Path(sys.executable))]
        for p in self.patches:p.start()
        self.manager=JobManager()
        self.options=dict(preview=False,book=str(self.book),cover=None,chapters=['0'],model='qwen17',voice='Aiden',
                          reference=None,first_page=1,last_page=0,chapter_pages=10,chunk_chars=320,
                          instructions='',seed=42,format='M4B',audition_text='',from_book=False,
                          speed=1.0,passage_gap=0,chapter_gap=1,normalize=False,bitrate=128)

    def tearDown(self):
        self.manager.stop()
        if self.manager.thread:self.manager.thread.join(10)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def wait_until(self,predicate,seconds=10):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.02)
        self.fail(str(self.manager.snapshot()))

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_stop_resume_and_speed_reexport_use_saved_chunks(self):
        self.manager.start(self.options)
        with self.assertRaises(RuntimeError):self.manager.start(self.options)
        self.wait_until(lambda:self.manager.snapshot()['completed']>=1)
        self.manager.stop();self.manager.thread.join(10)
        s=self.manager.snapshot();self.assertEqual(s['status'],'stopped')
        folder=Path(s['folder']);cached=next((folder/'chunks').glob('*.wav'))
        modified=cached.stat().st_mtime_ns
        self.manager.retry();self.manager.thread.join(10)
        s=self.manager.snapshot();self.assertEqual(s['status'],'done',s)
        self.assertGreaterEqual(s['cached'],1)
        self.assertEqual(cached.stat().st_mtime_ns,modified)
        self.assertTrue(Path(s['output']).is_file())
        self.assertEqual(sum(r['done'] for r in s['chapters']),s['total'])
        self.manager.start({**self.options,'speed':1.25});self.manager.thread.join(10)
        s=self.manager.snapshot();self.assertEqual(s['status'],'done',s)
        self.assertEqual(s['cached'],s['total'])
        self.assertEqual(s['generated_count'],0)
        self.assertIn('1.25x',s['output'])

    def test_errors_are_persistent_and_can_retry(self):
        self.manager.start({**self.options,'chapters':[]});self.manager.thread.join(5)
        self.assertEqual(self.manager.snapshot()['status'],'failed')
        self.assertIn('Select at least one',self.manager.snapshot()['message'])


if __name__=='__main__':unittest.main()
