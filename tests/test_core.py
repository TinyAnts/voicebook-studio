import json
import shutil
import sys
import tempfile
import zipfile
import io
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core

class TestVoicebookCore(unittest.TestCase):
    def test_split_preserves_content_and_limits(self):
        text = 'A natural paragraph. Then another sentence! One more? ' * 90
        chunks = core.split_text(text, 320)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(p) <= 320 for p in chunks))
        self.assertEqual(' '.join(chunks), ' '.join(text.split()))

    def test_text_input_and_cache_key(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'test book.txt'
            source.write_text(('Chapter 1\nGreat story. More words. ' * 30), encoding='utf8')
            chapters = core.extract_document(source)
            self.assertTrue(chapters)
            self.assertTrue('Great story' in chapters[0].text)
            folder, pieces, title = core.plan_job(source, 'qwen17', 'Aiden', 'calm', None,
                                                  1, 0, 10, 250, 42)
            self.assertGreater(len(pieces), 0)
            self.assertEqual(title, 'test-book')
            self.assertEqual(pieces[0].index, 1)
            self.assertTrue(folder.is_dir())
            tasks_file = core.generate_tasks(folder, pieces, 'qwen17', 'Aiden', 'calm', 42, None)
            data = json.loads(tasks_file.read_text())
            self.assertEqual(len(data['tasks']), len(pieces))
            self.assertEqual(data['model'], 'qwen17')
            shutil.rmtree(folder)

    def test_select_one_chapter_and_unique_cache(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'chapters.txt'
            source.write_text(
                'Chapter 1\nThe first story had an interesting beginning. ' * 8 +
                '\nChapter 2\nThe second story had another engaging ending. ' * 8,
                encoding='utf-8')
            all_chapters = core.extract_document(source)
            self.assertGreaterEqual(len(all_chapters), 2)
            folder1, pieces1, _ = core.plan_job(
                source, 'qwen17', 'Aiden', 'Fiction', None, 1, 0, 10, 240, 42,
                selected_chapters=[0])
            folder2, pieces2, _ = core.plan_job(
                source, 'qwen17', 'Aiden', 'Fiction', None, 1, 0, 10, 240, 42,
                selected_chapters=[1])
            self.assertNotEqual(folder1, folder2)
            self.assertTrue(pieces1)
            self.assertTrue(pieces2)
            self.assertNotEqual(pieces1[0].chapter, pieces2[0].chapter)
            shutil.rmtree(folder1)
            shutil.rmtree(folder2)

    def test_pdf_embedded_chapter_bookmarks(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as d:
            filename = Path(d) / 'bookmarked.pdf'
            doc = pymupdf.open()
            for n in range(4):
                page = doc.new_page()
                page.insert_text((72, 72), f'Book page {n+1} with substantive readable content here.')
            doc.set_toc([[1, 'Prologue', 1], [1, 'Chapter One', 2], [1, 'Chapter Two', 4]])
            doc.save(filename)
            doc.close()
            chapters = core.extract_document(filename, pdf_group_pages=2)
            self.assertEqual([c.title for c in chapters], ['Prologue', 'Chapter One', 'Chapter Two'])
            self.assertIn('page 3', chapters[1].text.lower())

    def test_pdf_extract(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as d:
            filename = Path(d) / 'book.pdf'
            doc = pymupdf.open()
            for n in range(3):
                page = doc.new_page()
                page.insert_text((72, 72), f'Page {n + 1} with a story and quite enough book text to narrate.')
            doc.save(filename)
            doc.close()
            chapters = core.extract_document(filename, pdf_group_pages=2)
            self.assertEqual(len(chapters), 2)
            self.assertEqual(chapters[0].title, 'Pages 1-2')
            self.assertEqual(chapters[-1].title, 'Page 3')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe unavailable')
    def test_real_m4b_mp3_and_chapters(self):
        import numpy as np
        import soundfile as sf
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            pieces = []
            for i in range(3):
                p = folder / f'{i}.wav'
                sample_rate = 24000
                t = np.arange(0, int(sample_rate * .4)) / sample_rate
                sf.write(p, (0.12 * np.sin(2 * np.pi * 440 * t)).astype('float32'), sample_rate)
                pieces.append(core.Piece('Chapter A' if i < 2 else 'Chapter B', 'hi', i + 1, p))
            from PIL import Image
            Image.new('RGB', (300, 460), '#c85522').save(folder / 'source-cover.png')
            core.extract_book_cover(folder / 'book.txt', folder / 'cover.jpg', folder / 'source-cover.png')
            m4b = core.assemble(folder, pieces, folder / 'book.m4b', 'My Book')
            mp3 = core.assemble(folder, pieces, folder / 'book.mp3', 'My Book')
            self.assertGreater(m4b.stat().st_size, 1000)
            self.assertGreater(mp3.stat().st_size, 1000)
            out = subprocess.check_output(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_chapters', str(m4b)])
            chapters = json.loads(out)['chapters']
            self.assertEqual(len(chapters), 2)
            self.assertEqual(chapters[0]['tags']['title'], 'Chapter A')
            self.assertEqual(chapters[1]['tags']['title'], 'Chapter B')
            for media in (m4b, mp3):
                info = json.loads(subprocess.check_output([
                    'ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', str(media)
                ]))
                covers = [x for x in info['streams'] if x['codec_type'] == 'video'
                          and x.get('disposition', {}).get('attached_pic') == 1]
                self.assertEqual(len(covers), 1, f'Missing embedded album art: {media}')
                self.assertEqual(covers[0]['width'], 1200)
                self.assertEqual(covers[0]['height'], 1200)


    def test_pdf_first_page_cover_and_override(self):
        from PIL import Image
        import pymupdf
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            pdf = home / 'book.pdf'
            doc = pymupdf.open()
            page = doc.new_page(width=360, height=550)
            page.draw_rect(page.rect, color=(0, 0, 1), fill=(0, 0, 1))
            page.insert_text((45, 100), 'The Original Book Cover')
            doc.save(pdf)
            doc.close()
            cover = home / 'cover.jpg'
            self.assertEqual(core.extract_book_cover(pdf, cover), cover)
            with Image.open(cover) as img:
                self.assertEqual(img.size, (1200, 1200))
                self.assertGreater(img.getpixel((600, 600))[2], 200)
            custom = home / 'custom.png'
            Image.new('RGB', (256, 256), (240, 20, 60)).save(custom)
            core.extract_book_cover(pdf, cover, override=custom)
            with Image.open(cover) as img:
                a,b,c = img.getpixel((600, 600))
                self.assertGreater(a, 230)
                self.assertLess(b, 30)
                self.assertLess(c, 70)

    def test_epub_embedded_cover(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            epub_path = home / 'title.epub'
            cover_data = io.BytesIO()
            Image.new('RGB', (180, 270), (20, 135, 55)).save(cover_data, format='PNG')
            container = '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
            opf = '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata><meta name="cover" content="front"/></metadata><manifest><item id="front" href="pictures/cover.png" media-type="image/png" properties="cover-image"/></manifest></package>'
            with zipfile.ZipFile(epub_path, 'w') as arch:
                arch.writestr('META-INF/container.xml', container)
                arch.writestr('OPS/book.opf', opf)
                arch.writestr('OPS/pictures/cover.png', cover_data.getvalue())
            output = home / 'output.jpg'
            self.assertEqual(core.extract_book_cover(epub_path, output), output)
            with Image.open(output) as image:
                self.assertEqual(image.size, (1200, 1200))
                self.assertGreater(image.getpixel((600, 600))[1], 100)

if __name__ == '__main__':
    unittest.main()
