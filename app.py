"""Voicebook Studio: local audiobook workspace with a live background-job monitor."""
from __future__ import annotations

import hashlib
import html
from datetime import datetime
import json
from pathlib import Path

import gradio as gr

from core import LIBRARY, extract_book_cover, extract_document
from dashboard import render_chapters, render_status
from jobs import MANAGER, as_int, read_log
import library_store as catalog
from naming import MODEL_NAMES
import voices as narrators
from theme import CSS, THEME

# Only Qwen3-TTS 1.7B is kept: built-in Aiden/Ryan plus cloned library narrators (voices.py).
MODELS = {'Qwen3-TTS 1.7B': 'qwen17'}
STYLES = {
    'Nonfiction — clear and warm': 'Read in a natural, calm, warm professional nonfiction audiobook voice. Steady pace, subtle emphasis, clear diction, and comfortable pauses; no theatrics.',
    'Fiction — immersive storytelling': 'Read like an engaging, emotionally nuanced fiction audiobook narrator. Natural pacing, vivid but restrained expression, consistent narrator identity.',
    'Calm bedtime listening': 'Read slowly, gently and softly, with clear diction and a relaxed, soothing rhythm.',
}
ENGINES = {
    'Auto — fastest installed engine': 'auto',
    'Fast — CUDA graphs (needs install-qwen-fast.bat)': 'fast',
    'Batched GPU — standard install': 'batched',
    'One passage at a time — most compatible': 'single',
}
TTS_ENGINES = {'Qwen3-TTS 1.7B (default)': 'qwen', 'Fish S2 Pro 4-bit (Docker, research licence)': 'fish'}
LAYOUTS = {'Full book + one file per chapter': 'both', 'Full book only': 'full', 'Chapter files only': 'chapters'}
CHAPTER_FORMATS = {'M4B': 'm4b', 'MP3': 'mp3'}
BATCH_SIZES = [('Auto (fit GPU memory)', 0), ('1', 1), ('2', 2), ('4', 4), ('6', 6), ('8', 8), ('12', 12), ('16', 16)]
DEMO_TEXT = ('The farmhouse stood at the edge of a quiet valley. By morning, the clouds '
             'had cleared, and the first light moved across the hills. There was work to be '
             'done, but for a moment, everything was still.')


def narrator_intro(voice):
    name, text, kind = narrators.describe(voice)
    tag = {'builtin': 'Built-in Qwen voice', 'preset': 'Library narrator', 'custom': 'Your narrator'}.get(kind, '')
    return f'### {name}\n{text}\n\n<span class="narrator-tag">{tag}</span>'


def sample_value(voice, engine):
    """Ready sample for the card: a saved Fish sample when Fish is chosen, else the Qwen sample."""
    if engine == 'fish':
        try:
            _m, name, _r, _t = narrators.resolve(voice)
        except ValueError:
            return None
        saved = catalog.voice_choices('fish_s2', name)
        return saved[0][1] if saved else None
    path = narrators.ready_sample(voice)
    return str(path) if path else None


def narrator_card(voice, engine_label):
    engine = TTS_ENGINES.get(engine_label, 'qwen')
    name, _text, kind = narrators.describe(voice)
    sample = sample_value(voice, engine)
    if engine == 'fish' and kind == 'builtin':
        note = 'Aiden and Ryan are Qwen-only voices. Pick a library narrator for Fish.'
    elif engine == 'fish':
        note = 'Fish sample saved earlier.' if sample else 'No Fish sample yet — click **Make Fish samples for all narrators** (≈1 min each).'
    else:
        note = 'Reads the farmhouse passage. Ready-made — no waiting.' if sample else 'No sample yet.'
    return (narrator_intro(voice), sample, note, gr.update(visible=kind == 'builtin' and engine == 'qwen'),
            gr.update(visible=kind == 'custom'), gr.update(visible=engine == 'fish'))


def engine_help(label):
    if TTS_ENGINES.get(label) != 'fish':
        return gr.update(visible=False)
    return gr.update(visible=True, value=(
        '**Fish S2 Pro** (4-bit) runs in Docker on your GPU. Install once with `install-fish.bat`; the app starts '
        'the server itself (first start ≈ 5 min). Use a library narrator — Aiden and Ryan are Qwen-only. '
        'Narration style does not apply. Research / non-commercial licence.'))


def narrator_list(value=None):
    values = [v for _l, v in narrators.choices()]
    return gr.update(choices=narrators.choices(), value=value if value in values else 'Aiden')


def design_narrator(name, description, seed, engine):
    try:
        MANAGER.start(dict(design=True, preview=True, book=None, model='qwen17', voice='Aiden', speed=1.0,
                           design_name=name, design_description=description, seed=seed,
                           engine=ENGINES.get(engine, 'auto')))
    except Exception as exc:
        raise gr.Error(str(exc)) from exc


def add_recording(path, name, transcript):
    try:
        if not path:
            raise ValueError('Upload a recording first.')
        value = narrators.import_recording(path, name or 'My voice', transcript)
        return narrator_list(value), 'Added. Your narrator is selected — generate a preview to hear it.'
    except Exception as exc:
        raise gr.Error(str(exc)) from exc


def remove_narrator(voice):
    try:
        narrators.delete_custom(voice)
        return narrator_list('Aiden'), 'Narrator removed. Audio you already made with it is kept.'
    except Exception as exc:
        raise gr.Error(str(exc)) from exc


def inspect_chapters(book, first_page, last_page, chapter_pages):
    if not book:
        return gr.update(choices=[], value=[]), [], 'Upload a book to choose chapters.'
    try:
        chapters = extract_document(Path(book), as_int(first_page, 1) or 1, as_int(last_page, 0) or None, as_int(chapter_pages, 10) or 10)
        choices = [(f'{i+1:02d} · {c.title} · {len(c.text.split()):,} words', str(i)) for i,c in enumerate(chapters)]
        data = [{'id':str(i), 'title':c.title, 'words':len(c.text.split()), 'excerpt':c.text[:1600]} for i,c in enumerate(chapters)]
        return gr.update(choices=choices, value=[x['id'] for x in data]), data, selection_summary(data, [x['id'] for x in data])
    except Exception as exc:
        return gr.update(choices=[], value=[]), [], f'Unable to read document: {exc}'


def selection_summary(data, selected):
    chosen = [x for x in data if x['id'] in (selected or [])]
    words = sum(x['words'] for x in chosen)
    return f'**{len(chosen)} of {len(data)} sections selected · {words:,} words.** EPUB follows reading sections; PDF uses bookmarks where available, otherwise page groups.'


def selection_changed(data, selected):
    chosen = [x for x in data if x['id'] in (selected or [])]
    return selection_summary(data, selected), chosen[0]['excerpt'] if chosen else ''


def cover_preview(book, override):
    if not book:
        return None, 'Cover detected after upload.'
    try:
        source = Path(book)
        uploaded = Path(override) if override else None
        stamp = f'{source.resolve()}:{source.stat().st_mtime_ns}:{source.stat().st_size}'
        if uploaded:
            stamp += f':{uploaded.resolve()}:{uploaded.stat().st_mtime_ns}'
        target = LIBRARY / '_cover-previews' / (hashlib.sha256(stamp.encode()).hexdigest()[:16]+'.jpg')
        result = target if target.is_file() else extract_book_cover(source, target, uploaded)
        return (str(result), 'Cover will be embedded in your audiobook.') if result else (None, 'No cover found. You can add one below.')
    except Exception as exc:
        return None, f'Cover unavailable: {exc}'


def library_choices(query='', kind='All', sort='Newest first'):
    return gr.update(choices=catalog.choices(query,kind,sort),value=None)


def library_select(value):
    if not value:
        return (None,'Select a saved generation to listen, download or edit.',None,None,'','','','','',0)
    try:
        item=catalog.detail(value)
        esc=lambda x:html.escape(str(x))
        settings=item['settings']
        text=f'<h3>{esc(item["title"])}</h3><p>{esc(item["kind"])} · {esc(MODEL_NAMES.get(item["model"],item["model"]))} · {esc(item["voice"])} · {esc(item["format"])} · {item["size_mb"]:.1f} MB</p>'
        text+=f'<p>Saved {datetime.fromtimestamp(item["modified"]).strftime("%d %b %Y, %H:%M")} · {esc(item["filename"])}.{item["format"].lower()}</p>'
        if settings:text+=f'<p>Speed {settings.get("speed",1):g}× · {settings.get("bitrate",128)} kbps</p>'
        if item['author']:text+=f'<p>By {esc(item["author"])}</p>'
        if item['chapter_names']:text+='<p>'+esc(' / '.join(item['chapter_names']))+'</p>'
        where=f'audiobooks\\Finished\\{Path(item["finished_dir"]).name}' if item.get('finished_dir') else f'audiobooks\\{Path(item["path"]).parent.name}'
        text+=f'<p class="file-location">Location: {esc(where)}</p>'
        return (item['cover'],text,catalog.preview(value),value,item['title'],item['author'],
                item['filename'],item['notes'],item['excerpt'],0)
    except Exception as exc:raise gr.Error(str(exc)) from exc


def reveal_file(path):
    """Open the file's folder in Explorer (this app runs on your own computer)."""
    import os, subprocess, sys
    target=Path(path)
    if os.name=='nt':
        subprocess.Popen(f'explorer /select,"{target}"')
    elif sys.platform=='darwin':
        subprocess.Popen(['open','-R',str(target)])
    else:
        subprocess.Popen(['xdg-open',str(target.parent)])
    return f'Opened the folder: `{target.parent}`'


def show_library_file(value):
    try:
        item=catalog.detail(value)
        finished=Path(item.get('finished_dir') or '')
        if item.get('finished_dir') and finished.is_dir():
            return reveal_file(next(iter(sorted(finished.glob('Full book/*'))), finished / 'About.txt'))
        return reveal_file(catalog.resolve_entry(value))
    except Exception as exc:raise gr.Error(str(exc)) from exc


def show_result_file():
    s=MANAGER.snapshot()
    if s.get('output_folder') and Path(s['output_folder']).is_dir():
        return reveal_file(Path(s['output_folder'])/'About.txt')
    output=s.get('output')
    if not output or not Path(output).is_file():
        raise gr.Error('No finished file yet.')
    return reveal_file(output)


def play_excerpt(value,start,length):
    try:return catalog.preview(value,float(start)*60,int(length))
    except Exception as exc:raise gr.Error(str(exc)) from exc


def save_library(value,title,author,filename,notes,query,kind,sort):
    try:
        MANAGER.begin_library_edit()
        try:
            updated=catalog.edit(value,title,author,notes,filename)
            MANAGER.invalidate_output(value)
        finally:MANAGER.end_library_edit()
        options=catalog.choices(query,kind,sort)
        return gr.update(choices=options,value=updated if updated in dict(options).values() else None),'Saved title, author, notes and filename.'
    except Exception as exc:raise gr.Error(str(exc)) from exc


def trash_library(value,query,kind,sort):
    try:
        MANAGER.begin_library_edit()
        try:
            catalog.trash(value);MANAGER.invalidate_output(value)
        finally:MANAGER.end_library_edit()
        return library_choices(query,kind,sort),gr.update(choices=catalog.trash_choices(),value=None),'Moved to Trash. You can restore it below; narration passages are kept.'
    except Exception as exc:raise gr.Error(str(exc)) from exc


def restore_library(value,query,kind,sort):
    try:
        MANAGER.begin_library_edit()
        try:catalog.restore(value)
        finally:MANAGER.end_library_edit()
        return library_choices(query,kind,sort),gr.update(choices=catalog.trash_choices(),value=None),'Restored. Select the generation in the library to play it.'
    except Exception as exc:raise gr.Error(str(exc)) from exc


def saved_voices(model,voice):
    try:
        model_id, name, _r, _t = narrators.resolve(voice)
    except ValueError:
        return gr.update(choices=[], value=None)
    values=catalog.voice_choices(model_id,name)
    return gr.update(choices=values,value=values[0][1] if values else None)


def saved_voice_audio(value):
    if not value:return None,''
    try:return catalog.preview(value),catalog.detail(value)['excerpt']
    except Exception as exc:raise gr.Error(str(exc)) from exc


def launch_job(preview, book, cover, chapters, model, voice, reference, first_page, last_page,
               chapter_pages, chunk_chars, instructions, seed, output_format, audition_text,
               from_book, speed, passage_gap, chapter_gap, normalize, bitrate, engine=None, batch_size=0,
               layout=None, chapter_format=None, tts=None, sample_voices=None):
    try:
        MANAGER.start(dict(preview=preview, book=book, cover=cover, chapters=chapters,
                           model=MODELS.get(model, 'qwen17'), voice=voice, reference=reference,
                           first_page=first_page, last_page=last_page, chapter_pages=chapter_pages,
                           chunk_chars=chunk_chars, instructions=instructions, seed=seed,
                           format=output_format, audition_text=audition_text, from_book=from_book,
                           speed=float(speed), passage_gap=float(passage_gap), chapter_gap=float(chapter_gap),
                           normalize=normalize, bitrate=int(bitrate or 128), sample_voices=sample_voices,
                           engine=ENGINES.get(engine, 'auto'), batch_size=as_int(batch_size, 0),
                           layout=LAYOUTS.get(layout, 'both'), chapter_format=CHAPTER_FORMATS.get(chapter_format, 'm4b'),
                           tts=TTS_ENGINES.get(tts, 'qwen')))
    except Exception as exc:
        raise gr.Error(str(exc)) from exc


def start_book(*args):
    launch_job(False, *args)


def start_preview(*args):
    launch_job(True, *args)


def build_samples(*args):
    values=list(args)
    values[13]=DEMO_TEXT
    values[14]=False
    values[15]=1.0
    fish=TTS_ENGINES.get(values[-1])=='fish'
    launch_job(True,*values,sample_voices=[v for _label, v in narrators.choices() if not (fish and not v.startswith('voice:'))])


def resume_job():
    try:
        MANAGER.retry()
    except Exception as exc:
        raise gr.Error(str(exc)) from exc


def poll_ui(seen,query="",kind="All",sort="Newest first",model=list(MODELS)[0],voice="Aiden",engine_label=None):
    s = MANAGER.snapshot()
    seen=seen or {}
    busy = s['status'] in ('running', 'stopping')
    token = f'{s["job_id"]}:{s["status"]}'
    changed = token != seen.get('token')
    catalog_token=(s["job_id"],s.get("sample_index"),s["status"])
    catalog_changed=seen.get("catalog_token")!=catalog_token
    finished = s['status']=='done'
    is_preview = s.get('kind')=='Voice preview'
    log = read_log(s.get('log_path')) or 'Backend messages appear here while a job is running.'
    chapter_token = (s['job_id'], s.get('completed'), s.get('total'), s.get('current_chapter'), s['status'])
    skip = gr.skip
    return (
        render_status(s), render_chapters(s) if seen.get('chapter_token')!=chapter_token else skip(),
        log if log!=seen.get('log') else skip(),
        gr.update(interactive=not busy) if changed else skip(),
        gr.update(interactive=not busy) if changed else skip(),
        gr.update(interactive=s['status']=='running') if changed else skip(),
        gr.update(interactive=s['status'] in ('stopped','failed')) if changed else skip(),
        gr.update(visible=finished and not is_preview) if changed else skip(),
        s.get('audio') if changed and finished and not is_preview else (None if changed else skip()),
        s.get('output') if changed and finished else (None if changed else skip()),
        s.get('audio') if changed and finished and is_preview else (None if changed and not finished else skip()),
        gr.update(choices=catalog.choices(query,kind,sort)) if catalog_changed and (finished or s.get('sample_index',1)>1) else skip(),
        sample_value(voice, TTS_ENGINES.get(engine_label,'qwen')) if catalog_changed and finished and s.get('kind')=='Voice preview' else skip(),
        gr.update(interactive=not busy) if changed else skip(),
        narrator_list(s.get('new_voice')) if catalog_changed and finished and s.get('new_voice') else skip(),
        {'token':token, 'chapter_token':chapter_token, 'log':log,'catalog_token':catalog_token},
    )



def step_header(number, title, hint):
    return gr.HTML(f'<div class="step-head"><span class="step-num">{number}</span>'
                   f'<div><h3>{title}</h3><p>{hint}</p></div></div>', elem_classes='step-head-wrap')


with gr.Blocks(title='Voicebook Studio') as demo:
    gr.HTML('<header id="masthead"><div><h1>Voicebook Studio</h1><p>Your books. Your narrator. At your pace.</p></div><span class="local-badge">Runs on your computer</span></header>')
    with gr.Tabs():
        with gr.Tab('Create audiobook'):
            with gr.Row(elem_id='create-layout', equal_height=False):
                # ---------- Left: the steps, in the order you do them ----------
                with gr.Column(scale=7, min_width=340, elem_id='steps'):
                    with gr.Column(elem_classes='step-card'):
                        step_header(1, 'Choose your book', 'Upload a PDF, EPUB, TXT or MD file, then pick the chapters to narrate.')
                        with gr.Row(equal_height=False):
                            book = gr.File(label='Book file', file_types=['.pdf','.epub','.txt','.md'], type='filepath', scale=3, min_width=220)
                            with gr.Column(scale=2, min_width=180, elem_id='cover-column'):
                                cover_image = gr.Image(label='Book cover', type='filepath', interactive=False, height=190)
                                cover_info = gr.Markdown('Cover detected after upload.', elem_classes='muted')
                                with gr.Accordion('Replace cover', open=False):
                                    cover = gr.File(label='Custom JPG / PNG / WEBP', file_types=['.jpg','.jpeg','.png','.webp'], type='filepath')
                        chapter_info = gr.Markdown('Upload a book to choose chapters.')
                        chapters = gr.CheckboxGroup(choices=[], value=[], label='Chapters to narrate', elem_id='chapter-selector')
                        with gr.Row(elem_classes='compact-row'):
                            select_all = gr.Button('Select all', size='sm')
                            select_none = gr.Button('Clear selection', size='sm')
                        chapter_data = gr.State([])
                        with gr.Accordion('Check extracted text', open=False):
                            extracted = gr.Textbox(label='Beginning of the first selected chapter', lines=6, interactive=False)
                            gr.Markdown('Check the reading order before a long conversion. Scanned PDFs need OCR first.', elem_classes='muted')
                        with gr.Accordion('PDF page range & section size', open=False):
                            with gr.Row():
                                first_page = gr.Number(value=1, minimum=1, precision=0, label='First page')
                                last_page = gr.Number(value=0, minimum=0, precision=0, label='Last page · 0 = end')
                            chapter_pages = gr.Slider(1,30,value=10,step=1,label='Pages per section when PDF bookmarks are unavailable')

                    with gr.Column(elem_classes='step-card'):
                        step_header(2, 'Choose a narrator', 'Click a narrator to hear a ready sample instantly. Every voice can read a whole book.')
                        model = gr.Dropdown(choices=list(MODELS), value=list(MODELS)[0], label='Voice model', visible=False)
                        reference = gr.File(visible=False, type='filepath')
                        tts = gr.Radio(list(TTS_ENGINES), value=list(TTS_ENGINES)[0], label='Speech engine', elem_id='engine-pick')
                        tts_help = gr.Markdown(visible=False, elem_classes='muted')
                        with gr.Row(equal_height=False, elem_id='narrator-row'):
                            with gr.Column(scale=3, min_width=260):
                                voice = gr.Radio(choices=narrators.choices(), value='Aiden', label='Narrators · men, then women', elem_id='narrator-grid')
                            with gr.Column(scale=2, min_width=240, elem_classes='sub-card', elem_id='narrator-card'):
                                model_help = gr.Markdown(narrator_intro('Aiden'), elem_id='narrator-name')
                                sample_player = gr.Audio(value=sample_value('Aiden', 'qwen'), label='Sample', type='filepath', interactive=False, elem_id='narrator-sample')
                                sample_text = gr.Markdown('Reads the farmhouse passage. Ready-made — no waiting.', elem_classes='muted')
                                with gr.Accordion('Narration style', open=False) as tone_panel:
                                    style = gr.Dropdown(choices=list(STYLES),value=list(STYLES)[0],label='Tone')
                                    instructions = gr.Textbox(value=STYLES[list(STYLES)[0]], lines=3, label='Custom narration direction')
                                samples_button = gr.Button('Make Fish samples for all narrators', size='sm', visible=False)
                                remove_button = gr.Button('Remove this narrator', size='sm', variant='stop', visible=False)
                        with gr.Accordion('Hear it read your own text', open=False):
                            audition_text = gr.Textbox(value=DEMO_TEXT,lines=3,max_lines=5,label='Text to read')
                            with gr.Row(elem_classes='compact-row', equal_height=True):
                                from_book = gr.Checkbox(value=False,label='Use the first selected chapter instead', scale=3)
                                preview = gr.Button('Read it with this narrator', variant='secondary', scale=2)
                            preview_audio = gr.Audio(label='Your preview',type='filepath',interactive=False)
                        with gr.Accordion('Add a narrator', open=False):
                            with gr.Tabs():
                                with gr.Tab('Describe a voice'):
                                    design_name = gr.Textbox(label='Name', placeholder='e.g. Walter')
                                    design_description = gr.Textbox(label='Describe the voice', lines=3,
                                        placeholder='e.g. A Scottish man in his sixties with a low, gravelly, kind voice. Slow and thoughtful.')
                                    design_button = gr.Button('Create this narrator', variant='secondary')
                                    gr.Markdown('Mention age, gender, accent, pitch and pace. Takes about a minute; try again for a different take.', elem_classes='muted')
                                with gr.Tab('Use a recording'):
                                    own_file = gr.File(label='Clean 8–20 second recording (yours, or with permission)', file_types=['.wav','.mp3','.flac','.m4a','.ogg'], type='filepath')
                                    own_name = gr.Textbox(label='Narrator name', placeholder='e.g. My voice')
                                    own_text = gr.Textbox(label='Exactly what is said in the recording', lines=2)
                                    own_button = gr.Button('Add as narrator', variant='secondary')
                            narrator_feedback = gr.Markdown(elem_classes='muted')
                        saved_voice = gr.Dropdown(choices=[], value=None, visible=False)

                    with gr.Column(elem_classes='step-card'):
                        step_header(3, 'Listening & export', 'Speed, pauses and quality are applied when the file is built — changing them reuses saved narration.')
                        speed = gr.Slider(.75,1.5,value=1.0,step=.05,label='Reading speed',info='1.0× = original. Pitch is preserved.')
                        with gr.Row():
                            output_format = gr.Radio(['M4B','MP3'],value='M4B',label='Full book format',info='M4B keeps chapter markers and cover.')
                            bitrate = gr.Dropdown([96,128,192],value=128,label='Audio bitrate · kbps')
                        with gr.Row():
                            layout = gr.Radio(list(LAYOUTS),value=list(LAYOUTS)[0],label='Files to make',
                                              info='Saved in audiobooks\\Finished\\<Title - Author>\\ with the cover and an About.txt.')
                            chapter_format = gr.Radio(list(CHAPTER_FORMATS),value='M4B',label='Chapter file format',
                                                      info='M4B keeps the cover and plays in audiobook apps; MP3 plays anywhere.')
                        with gr.Accordion('Pauses & consistent volume',open=False):
                            passage_gap = gr.Slider(0,1,value=0,step=.05,label='Extra pause between passages · seconds',info='Added to the short pause already present in generated audio.')
                            chapter_gap = gr.Slider(0,5,value=1,step=.25,label='Extra pause between chapters · seconds')
                            normalize = gr.Checkbox(value=True,label='Keep listening volume consistent')

                    with gr.Column(elem_classes='step-card'):
                        step_header(4, 'Advanced', 'Optional. The defaults work well; open only if you need to tune speed or generation.')
                        with gr.Accordion('GPU speed',open=False):
                            with gr.Row():
                                engine = gr.Dropdown(choices=list(ENGINES),value=list(ENGINES)[0],label='Qwen speed engine')
                                batch_size = gr.Dropdown(choices=BATCH_SIZES,value=0,label='Passages per GPU batch')
                            gr.Markdown('**Batched GPU** narrates several passages at once with your existing install. **Fast** uses CUDA graphs (install once with `install-qwen-fast.bat`). Auto picks Fast when installed, otherwise Batched. On a GPU-memory warning, choose a smaller batch.', elem_classes='muted')
                        with gr.Accordion('Generation settings',open=False):
                            with gr.Row():
                                chunk_chars = gr.Slider(180,500,value=320,step=20,label='Characters per passage')
                                seed = gr.Number(value=42,precision=0,label='Random seed')
                            gr.Markdown('Changing the voice, style, passage size or seed creates new narration. Passages already narrated for another chapter selection of the same book are reused automatically.', elem_classes='muted')

                # ---------- Right: create, live progress, result (stays in view) ----------
                with gr.Column(scale=5, min_width=320, elem_id='side'):
                    go = gr.Button('Create audiobook', variant='primary', size='lg', elem_id='create-button')
                    with gr.Row(elem_id='job-actions'):
                        stop = gr.Button('Stop & keep progress', variant='stop', interactive=False)
                        resume = gr.Button('Resume / retry', interactive=False)
                    status = gr.HTML(render_status(MANAGER.snapshot()), elem_id='job-dashboard')
                    with gr.Column(visible=False,elem_id='conversion-result') as result_group:
                        gr.HTML('<h4 class="sub-title">Your audiobook is ready</h4>', elem_classes='sub-title-wrap')
                        book_audio = gr.Audio(label='Listen to a short excerpt', type='filepath', interactive=False)
                        download = gr.File(label='Download your complete audiobook')
                        result_folder = gr.Button('Show in folder', size='sm')
                        result_feedback = gr.Markdown(elem_classes='muted')
                    with gr.Accordion('Chapter progress & activity log', open=False):
                        chapter_status = gr.HTML(render_chapters(MANAGER.snapshot()))
                        logs = gr.Textbox(label='Live activity log', lines=6, max_lines=10, interactive=False)
                    gr.Markdown('Changes apply to the **next** job. You can refresh this page while a job runs — keep the app terminal open.', elem_classes='muted side-note')
        with gr.Tab('Library'):
            with gr.Row(equal_height=False, elem_id='library-layout'):
                with gr.Column(scale=4,min_width=290,elem_classes='step-card'):
                    gr.HTML('<div class="step-head"><div><h3>Your generations</h3><p>Search, filter and pick a saved audiobook or voice sample.</p></div></div>', elem_classes='step-head-wrap')
                    library_search=gr.Textbox(value='',label='Search books, voices or filenames',placeholder='Find a saved generation…')
                    library_kind=gr.Radio(['All','Audiobook','Voice preview'],value='All',label='Show')
                    library_sort=gr.Dropdown(['Newest first','Oldest first','Title A–Z'],value='Newest first',label='Sort')
                    refresh=gr.Button('Refresh library',size='sm')
                    library_list=gr.Radio(choices=catalog.choices(),label='Select a generation',elem_id='library-list')
                with gr.Column(scale=8,min_width=340,elem_classes='step-card'):
                    with gr.Row():
                        library_cover=gr.Image(label='Cover',type='filepath',height=150,interactive=False,scale=1)
                        library_info=gr.HTML('Select a saved generation to listen, download or edit.',elem_id='library-detail')
                    library_player=gr.Audio(label='Listen to this generation',type='filepath',interactive=False)
                    with gr.Row():
                        excerpt_start=gr.Number(value=0,minimum=0,maximum=1440,label='Excerpt starts at · minutes')
                        excerpt_length=gr.Dropdown([30,60,120],value=60,label='Excerpt length · seconds')
                        excerpt_button=gr.Button('Play excerpt from here')
                    with gr.Row(equal_height=True):
                        library_download=gr.File(label='Download complete file',scale=4)
                        library_folder=gr.Button('Show in folder',scale=1,min_width=140)
                    library_passage=gr.Textbox(label='Preview passage · when available',lines=2,interactive=False)
                    with gr.Accordion('Rename & edit details',open=False):
                        edit_title=gr.Textbox(label='Title')
                        edit_author=gr.Textbox(label='Author')
                        edit_filename=gr.Textbox(label='Filename · keep extension off')
                        edit_notes=gr.Textbox(label='Notes',lines=3)
                        save_edits=gr.Button('Save changes',variant='primary')
                        gr.Markdown('Updates audio tags and filename. The narration, chapter markers and cover are preserved.')
                    trash_button=gr.Button('Move selected generation to Trash',variant='stop')
                    library_feedback=gr.Markdown()
            with gr.Accordion('Trash · restore deleted generations',open=False):
                trash_list=gr.Dropdown(choices=catalog.trash_choices(),label='Deleted generations')
                restore_button=gr.Button('Restore selected generation')
                gr.Markdown('Trash keeps files recoverable. Saved narration passages stay available for resume. To free disk space permanently, remove the relevant files from the local audiobooks folder after checking your backups.')
            gr.Markdown('Older M4B and MP3 generations appear automatically. Selecting a book prepares a short excerpt; the complete file is available above.')

    card_outputs=[model_help,sample_player,sample_text,tone_panel,remove_button,samples_button]
    voice.change(narrator_card,[voice,tts],card_outputs,queue=False)
    output_format.change(lambda value: value, output_format, chapter_format, queue=False)   # chapters follow the book format unless changed
    tts.change(engine_help,tts,tts_help,queue=False).then(narrator_card,[voice,tts],card_outputs,queue=False)
    design_button.click(design_narrator,[design_name,design_description,seed,engine],queue=False,show_progress='hidden')
    own_button.click(add_recording,[own_file,own_name,own_text],[voice,narrator_feedback])
    remove_button.click(remove_narrator,voice,[voice,narrator_feedback],queue=False)
    style.change(lambda value:STYLES[value],style,instructions,queue=False)
    for trigger in [book,first_page,last_page,chapter_pages]:
        trigger.change(inspect_chapters,[book,first_page,last_page,chapter_pages],[chapters,chapter_data,chapter_info],show_progress='minimal')
    chapter_data.change(selection_changed,[chapter_data,chapters],[chapter_info,extracted],queue=False)
    chapters.change(selection_changed,[chapter_data,chapters],[chapter_info,extracted],queue=False)
    select_all.click(lambda data:gr.update(value=[x['id'] for x in data]),chapter_data,chapters,queue=False)
    select_none.click(lambda:gr.update(value=[]),outputs=chapters,queue=False)
    book.change(cover_preview,[book,cover],[cover_image,cover_info],show_progress='minimal')
    cover.change(cover_preview,[book,cover],[cover_image,cover_info],show_progress='minimal')
    args = [book,cover,chapters,model,voice,reference,first_page,last_page,chapter_pages,chunk_chars,
            instructions,seed,output_format,audition_text,from_book,speed,passage_gap,chapter_gap,normalize,bitrate,
            engine,batch_size,layout,chapter_format,tts]
    go.click(start_book,args,queue=False,api_name='start_book',show_progress='hidden')
    preview.click(start_preview,args,queue=False,api_name='start_preview',show_progress='hidden')
    stop.click(MANAGER.stop,queue=False,api_name='stop_job',show_progress='hidden')
    resume.click(resume_job,queue=False,api_name='resume_job',show_progress='hidden')
    samples_button.click(build_samples,args,queue=False,api_name='build_voice_samples',show_progress='hidden')
    filters=[library_search,library_kind,library_sort]
    for control in filters:
        control.change(library_choices,filters,library_list,queue=False)
    refresh.click(library_choices,filters,library_list,queue=False).then(lambda:gr.update(choices=catalog.trash_choices(),value=None),outputs=trash_list,queue=False)
    selection_outputs=[library_cover,library_info,library_player,library_download,edit_title,edit_author,edit_filename,edit_notes,library_passage,excerpt_start]
    library_list.change(library_select,library_list,selection_outputs,api_name='library_select',show_progress='minimal')
    library_folder.click(show_library_file,library_list,library_feedback,queue=False)
    result_folder.click(show_result_file,outputs=result_feedback,queue=False)
    excerpt_button.click(play_excerpt,[library_list,excerpt_start,excerpt_length],library_player,api_name='play_excerpt')
    save_edits.click(save_library,[library_list,edit_title,edit_author,edit_filename,edit_notes,*filters],[library_list,library_feedback],api_name='save_library')
    trash_button.click(trash_library,[library_list,*filters],[library_list,trash_list,library_feedback],api_name='trash_library')
    restore_button.click(restore_library,[trash_list,*filters],[library_list,trash_list,library_feedback],api_name='restore_library')
    seen = gr.State({})
    poll_outputs = [status,chapter_status,logs,go,preview,stop,resume,result_group,book_audio,download,preview_audio,library_list,sample_player,samples_button,voice,seen]
    poll_inputs=[seen,*filters,model,voice,tts]
    timer = gr.Timer(1.0)
    timer.tick(poll_ui,poll_inputs,poll_outputs,queue=False,show_progress='hidden',api_name='job_status')
    demo.load(poll_ui,poll_inputs,poll_outputs,queue=False,show_progress='hidden')

if __name__ == '__main__':
    demo.queue(default_concurrency_limit=2).launch(server_name='127.0.0.1',server_port=7860,
        inbrowser=True,show_error=True,max_file_size='100mb',allowed_paths=[str(LIBRARY), str(narrators.PRESET_DIR)],
        theme=THEME,css=CSS)
