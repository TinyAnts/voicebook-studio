import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import core
import library_store as catalog
from naming import clean_name,export_name,unique_path
from test_progress import tone
import test_progress


class TestNames(unittest.TestCase):
    def test_names_include_book_chapter_voice_and_preview_without_hash(self):
        pieces=[core.Piece('03 · A New Beginning','hello',1,Path('x.wav'))]
        name=export_name('The Quiet Valley',pieces,'qwen17','Aiden',1.1,True)
        self.assertEqual(name,'Preview - The Quiet Valley - 03 A New Beginning - Aiden - Qwen 1.7B - 1.1x')
        self.assertEqual(clean_name('CON'),'Book CON')
        self.assertEqual(clean_name('A: Book / Chapter?'),'A Book Chapter')
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);(folder/'Title.mp3').touch()
            self.assertEqual(unique_path(folder,'Title','mp3').name,'Title (2).mp3')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.patch=patch('library_store.LIBRARY',self.root);self.patch.start()
        self.folder=self.root/'book-cache';self.folder.mkdir()
        (self.folder/'book.json').write_text(json.dumps(dict(original='Original Book.epub',model='qwen17',speaker='Aiden',chapters=2)))
        Image.new('RGB',(64,64),'blue').save(self.folder/'cover.jpg')
        self.wav=self.folder/'raw.wav';tone(self.wav,1)
        pieces=[core.Piece('01 · Opening','text',1,self.wav),core.Piece('02 · Ending','text',2,self.wav)]
        self.book=core.assemble(self.folder,pieces,self.folder/'old-generation.m4b','Original Book',normalize=False)
        self.other=self.folder/'preview.mp3';core.assemble(self.folder,pieces[:1],self.other,'Preview',normalize=False)

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def test_unset_or_cleared_filters_show_saved_files(self):
        self.assertEqual(catalog.choices(None,None,None),catalog.choices())
        self.assertEqual(catalog.choices('   '),catalog.choices())
        self.assertEqual(len(catalog.entries('  ORIGINAL BOOK  ')),2)

    def test_old_generation_plays_and_metadata_rename_preserves_chapters_cover_audio(self):
        self.assertEqual(len(catalog.entries()),2)
        self.assertEqual(catalog.detail(self.book)['title'],'Original Book')
        sample=catalog.preview(self.book)
        self.assertTrue(Path(sample).is_file())
        self.assertEqual(catalog.preview(self.book),sample)
        edited=Path(catalog.edit(self.book,'A Friendly Title','A. Writer','Read again','Friendly Book - Aiden'))
        self.assertFalse(self.book.exists());self.assertTrue(edited.exists())
        data=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-of','json','-show_chapters','-show_format','-show_streams',str(edited)]))
        self.assertEqual(data['format']['tags']['title'],'A Friendly Title')
        self.assertEqual(data['format']['tags']['artist'],'A. Writer')
        self.assertEqual(len(data['chapters']),2)
        self.assertTrue(any(x['disposition'].get('attached_pic') for x in data['streams']))
        self.assertEqual(catalog.detail(edited)['notes'],'Read again')
        self.assertEqual(len(catalog.entries('friendly','Audiobook')),1)

    def test_trash_restore_keeps_other_outputs_and_narration(self):
        old=self.book.read_bytes();identifier=catalog.trash(self.book)
        self.assertFalse(self.book.exists());self.assertTrue(self.other.exists());self.assertTrue(self.wav.exists())
        self.assertEqual(len(catalog.trash_choices()),1)
        restored=Path(catalog.restore(identifier));self.assertEqual(restored.read_bytes(),old)
        self.assertEqual(catalog.trash_choices(),[])

    def test_invalid_paths_collisions_and_trash_traversal_are_rejected(self):
        with self.assertRaises(ValueError):catalog.resolve_entry(self.root/'outside.mp3')
        for name in ('../other','CON','bad:filename'):
            with self.assertRaises(ValueError):catalog.edit(self.book,'Title','','',name)
        collision=self.book.with_name('exists.m4b');collision.write_bytes(b'keep')
        with self.assertRaises(ValueError):catalog.edit(self.book,'Title','','','exists')
        self.assertEqual(collision.read_bytes(),b'keep')
        identifier=catalog.trash(self.book)
        record=self.root/'_trash'/identifier/'record.json';data=json.loads(record.read_text());data['original_folder']='..';record.write_text(json.dumps(data))
        with self.assertRaises(ValueError):catalog.restore(identifier)


class TestSampleBank(unittest.TestCase):
    setUp=test_progress.TestJobLifecycle.setUp
    tearDown=test_progress.TestJobLifecycle.tearDown
    wait_until=test_progress.TestJobLifecycle.wait_until
    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_batch_samples_are_saved_and_replayed_without_model(self):
        options={**self.options,'preview':True,'audition_text':'The same passage is read by each voice. '*4,
                 'sample_voices':['Aiden','Ryan']}
        self.manager.start(options);self.manager.thread.join(15)
        s=self.manager.snapshot();self.assertEqual(s['status'],'done',s)
        self.assertEqual(len(list(self.library.glob('*/Preview*.mp3'))),2)
        first=Path(s['output']);stamp=first.stat().st_mtime_ns
        with patch('jobs.model_python',side_effect=AssertionError('Saved samples must not load a model')):
            self.manager.start(options);self.manager.thread.join(10)
        s=self.manager.snapshot();self.assertEqual(s['status'],'done',s)
        self.assertEqual(first.stat().st_mtime_ns,stamp)
