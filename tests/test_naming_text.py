"""Book/author naming, full-book labels, text cleanup and protection of saved passages."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core
from naming import book_info, export_name
from test_progress import tone


class TestNames(unittest.TestCase):
    def test_title_and_author_from_filename(self):
        with tempfile.TemporaryDirectory() as d:
            pdf = Path(d) / 'The_Psychedelic_Handbook_-_Rick_Strassman.txt'
            pdf.write_text('x')
            self.assertEqual(book_info(pdf), ('The Psychedelic Handbook', 'Rick Strassman'))
            plain = Path(d) / 'Just A Title.txt'
            plain.write_text('x')
            self.assertEqual(book_info(plain), ('Just A Title', ''))

    def test_full_book_label_and_author(self):
        pieces = [core.Piece('01 · A', 't', 1, Path('a.wav')), core.Piece('02 · B', 't', 2, Path('b.wav'))]
        name = export_name('The Psychedelic Handbook', pieces, 'qwen17', 'Ryan', 1.0,
                           author='Rick Strassman', full_book=True)
        self.assertEqual(name, 'The Psychedelic Handbook - Rick Strassman - Full book - Ryan - Qwen 1.7B - 1x')
        partial = export_name('Book', pieces, 'qwen17', 'Ryan', 1.0)
        self.assertEqual(partial, 'Book - Chapters 01-02 - Ryan - Qwen 1.7B - 1x')


class TestTextCleanup(unittest.TestCase):
    def test_url_only_lines(self):
        self.assertTrue(core.is_noise_line('OceanofPDF.com'))
        self.assertTrue(core.is_noise_line(' www.example.org/books '))
        for keep in ('U.S.A', '3.14', 'e.g.', 'He visited example.com last year.', 'CHEMISTRY'):
            self.assertFalse(core.is_noise_line(keep), keep)

    def test_pdf_running_headers_and_watermarks_removed(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'book.pdf'
            doc = pymupdf.open()
            for i in range(12):
                page = doc.new_page()
                page.insert_text((72, 40), 'THE RUNNING HEADER')
                page.insert_text((72, 100), f'Body text of page {i} talks about CHEMISTRY in detail.')
                if i % 5 == 0:
                    page.insert_text((72, 700), 'OceanofPDF.com')
            doc.save(str(path))
            doc.close()
            new = ' '.join(c.text for c in core.extract_document(path))
            old = ' '.join(c.text for c in core.extract_document(path, text_version=1))
            self.assertNotIn('OceanofPDF', new)
            self.assertNotIn('RUNNING HEADER', new)
            self.assertIn('CHEMISTRY', new)
            self.assertIn('OceanofPDF', old)   # version 1 is kept for already-narrated folders


class TestSavedPassagesStayAligned(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / 'audiobooks'
        self.library.mkdir()
        self.patch = patch('core.LIBRARY', self.library)
        self.patch.start()
        self.book = self.root / 'Aligned.txt'
        self.book.write_text('Chapter 1 Start\n' + 'A sentence that keeps going here. ' * 30, encoding='utf-8')

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_old_folder_keeps_version_1_and_mismatches_are_dropped(self):
        folder, pieces, _ = core.plan_job(self.book, 'qwen17', 'Ryan', '', None, 1, 0, 10, 320, 42, [0])
        for p in pieces:
            tone(p.wav, .1)
        manifest = json.loads((folder / 'book.json').read_text())
        manifest.pop('text_version')          # emulate a folder made before this update
        (folder / 'book.json').write_text(json.dumps(manifest))
        again, pieces2, _ = core.plan_job(self.book, 'qwen17', 'Ryan', '', None, 1, 0, 10, 320, 42, [0])
        self.assertEqual(json.loads((again / 'book.json').read_text())['text_version'], 1)
        self.assertTrue(all(p.wav.exists() for p in pieces2))
        # A recorded passage whose text no longer matches its position must not be exported.
        record = json.loads((folder / 'passages.json').read_text())
        record['passages'][pieces2[0].wav.name] = 'different-text-hash'
        (folder / 'passages.json').write_text(json.dumps(record))
        _f, pieces3, _ = core.plan_job(self.book, 'qwen17', 'Ryan', '', None, 1, 0, 10, 320, 42, [0])
        self.assertFalse(pieces3[0].wav.exists())
        self.assertTrue(pieces3[1].wav.exists())

    def test_full_selection_is_recorded(self):
        folder, _p, _t = core.plan_job(self.book, 'qwen17', 'Ryan', '', None, 1, 0, 10, 320, 42, [0])
        manifest = json.loads((folder / 'book.json').read_text())
        self.assertEqual(manifest['total_chapters'], 1)
        self.assertEqual(manifest['text_version'], core.TEXT_VERSION)


@unittest.skipUnless(shutil.which('ffprobe'), 'FFmpeg required')
class TestExportTags(unittest.TestCase):
    def test_author_tags_and_44k_output(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            wav = folder / 'a.wav'
            tone(wav, 1)
            out = core.assemble(folder, [core.Piece('01 · A', 'x', 1, wav)], folder / 'b.m4b', 'Book',
                                author='Rick Strassman', comment='Narrated by Ryan')
            data = json.loads(subprocess.check_output(['ffprobe', '-v', 'quiet', '-of', 'json', '-show_format',
                                                       '-show_streams', str(out)]))
            tags = data['format']['tags']
            self.assertEqual(tags['artist'], 'Rick Strassman')
            self.assertEqual(tags['album'], 'Book')
            audio = [s for s in data['streams'] if s['codec_type'] == 'audio'][0]
            self.assertEqual(audio['sample_rate'], '44100')


if __name__ == '__main__':
    unittest.main()


class TestTextFixes(unittest.TestCase):
    def test_replace_drop_and_reseed_keep_positions(self):
        with tempfile.TemporaryDirectory() as d:
            library = Path(d) / 'audiobooks'
            library.mkdir()
            book = Path(d) / 'Fixes.txt'
            book.write_text(' '.join(f'Sentence number {i} is here.' for i in range(30)) + ' OceanofPDF.com '
                            + ' '.join(f'Later sentence {i} follows.' for i in range(20)), encoding='utf-8')
            with patch('core.LIBRARY', library):
                folder, pieces, title = core.plan_job(book, 'qwen17', 'Ryan', '', None, 1, 0, 10, 180, 42, [0])
                for p in pieces:
                    tone(p.wav, .1)
                marked = next(p for p in pieces if 'OceanofPDF' in p.text)
                self.assertNotEqual(marked.index, 1)
                fixes = {'replace': {core.text_key(pieces[0].text): '',
                                     core.text_key(marked.text): marked.text.replace('OceanofPDF.com', '')},
                         'reseed': {core.text_key(pieces[2].text): 1}}
                (library / '_text-fixes').mkdir()
                (library / '_text-fixes' / f'{title}.json').write_text(json.dumps(fixes))
                _f, fixed, _t = core.plan_job(book, 'qwen17', 'Ryan', '', None, 1, 0, 10, 180, 42, [0])
                self.assertEqual([p.index for p in fixed], [p.index for p in pieces[1:]])   # no shifting
                by_index = {p.index: p for p in fixed}
                self.assertNotIn('OceanofPDF', by_index[marked.index].text)
                self.assertFalse(by_index[marked.index].wav.exists())   # old audio for changed text removed
                self.assertEqual(by_index[pieces[2].index].reseed, 1 if pieces[2].index != marked.index else 0)
                untouched = [p for p in fixed if p.index not in (marked.index,)]
                self.assertTrue(all(p.wav.exists() for p in untouched))
