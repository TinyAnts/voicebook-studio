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
from jobs import MANAGER, read_log
import library_store as catalog
from naming import MODEL_NAMES
from theme import CSS, THEME

MODELS = {
    'Qwen3-TTS 1.7B — quality': 'qwen17',
    'Qwen3-TTS 0.6B — lower memory': 'qwen06',
    'Chatterbox Multilingual V3 — custom voice': 'chatter_v3',
    'Chatterbox Turbo — custom English voice': 'chatter_turbo',
    'Kokoro-82M — fast': 'kokoro',
}
VOICES = {
    'qwen17': ['Aiden', 'Ryan'], 'qwen06': ['Aiden', 'Ryan'],
    'chatter_v3': ['Reference recording'], 'chatter_turbo': ['Reference recording'],
    'kokoro': ['af_heart', 'af_bella', 'af_sarah', 'am_michael', 'am_adam', 'bf_emma', 'bm_george'],
}
STYLES = {
    'Nonfiction — clear and warm': 'Read in a natural, calm, warm professional nonfiction audiobook voice. Steady pace, subtle emphasis, clear diction, and comfortable pauses; no theatrics.',
    'Fiction — immersive storytelling': 'Read like an engaging, emotionally nuanced fiction audiobook narrator. Natural pacing, vivid but restrained expression, consistent narrator identity.',
    'Calm bedtime listening': 'Read slowly, gently and softly, with clear diction and a relaxed, soothing rhythm.',
}
DEMO_TEXT = ('The farmhouse stood at the edge of a quiet valley. By morning, the clouds '
             'had cleared, and the first light moved across the hills. There was work to be '
             'done, but for a moment, everything was still.')


def update_model(label):
    model = MODELS[label]
    note = ('Upload a clean 6–15 second voice recording you have permission to use.' if model.startswith('chatter') else
            'Aiden and Ryan are English voices. Try the same passage with both.' if model.startswith('qwen') else
            'Choose a predefined voice and listen to a sample.')
    if model == 'qwen06':
        note += ' Custom tone instructions are only applied to Qwen 1.7B in this app.'
    return (gr.update(choices=VOICES[model], value=VOICES[model][0]),
            gr.update(visible=model.startswith('chatter')), gr.update(visible=model=='qwen17'), note)


def inspect_chapters(book, first_page, last_page, chapter_pages):
    if not book:
        return gr.update(choices=[], value=[]), [], 'Upload a book to choose chapters.'
    try:
        chapters = extract_document(Path(book), int(first_page), int(last_page) or None, int(chapter_pages))
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
        if item['chapter_names']:text+='<p>'+esc(' / '.join(item['chapter_names']))+'</p>'
        return (item['cover'],text,catalog.preview(value),value,item['title'],item['author'],
                item['filename'],item['notes'],item['excerpt'],0)
    except Exception as exc:raise gr.Error(str(exc)) from exc


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
    values=catalog.voice_choices(MODELS[model],voice)
    return gr.update(choices=values,value=values[0][1] if values else None)


def saved_voice_audio(value):
    if not value:return None,''
    try:return catalog.preview(value),catalog.detail(value)['excerpt']
    except Exception as exc:raise gr.Error(str(exc)) from exc


def launch_job(preview, book, cover, chapters, model, voice, reference, first_page, last_page,
               chapter_pages, chunk_chars, instructions, seed, output_format, audition_text,
               from_book, speed, passage_gap, chapter_gap, normalize, bitrate, sample_voices=None):
    try:
        MANAGER.start(dict(preview=preview, book=book, cover=cover, chapters=chapters,
                           model=MODELS[model], voice=voice, reference=reference,
                           first_page=first_page, last_page=last_page, chapter_pages=chapter_pages,
                           chunk_chars=chunk_chars, instructions=instructions, seed=seed,
                           format=output_format, audition_text=audition_text, from_book=from_book,
                           speed=float(speed), passage_gap=float(passage_gap), chapter_gap=float(chapter_gap),
                           normalize=normalize, bitrate=int(bitrate),sample_voices=sample_voices))
    except Exception as exc:
        raise gr.Error(str(exc)) from exc


def start_book(*args):
    launch_job(False, *args)


def start_preview(*args):
    launch_job(True, *args)


def build_samples(*args):
    values=list(args)
    model=MODELS[values[3]]
    if model.startswith('chatter'):
        raise gr.Error('Custom voices use your recording. Use Generate voice preview to save a sample of it.')
    values[13]=DEMO_TEXT
    values[14]=False
    values[15]=1.0
    launch_job(True,*values,sample_voices=VOICES[model])


def resume_job():
    try:
        MANAGER.retry()
    except Exception as exc:
        raise gr.Error(str(exc)) from exc


def poll_ui(seen,query="",kind="All",sort="Newest first",model=list(MODELS)[0],voice="Aiden"):
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
        saved_voices(model,voice) if catalog_changed and (finished or s.get('sample_index',1)>1) else skip(),
        gr.update(interactive=not busy and not MODELS[model].startswith('chatter')),
        {'token':token, 'chapter_token':chapter_token, 'log':log,'catalog_token':catalog_token},
    )



with gr.Blocks(title='Voicebook Studio') as demo:
    gr.HTML('<header id="masthead"><div><h1>Voicebook Studio</h1><p>Your books. Your narrator. At your pace.</p></div><span class="local-badge">Runs on your computer</span></header>')
    status = gr.HTML(render_status(MANAGER.snapshot()), elem_id='job-dashboard')
    with gr.Row(elem_id='job-actions'):
        go = gr.Button('Create audiobook', variant='primary', scale=3)
        stop = gr.Button('Stop & keep progress', variant='stop', interactive=False, scale=1)
        resume = gr.Button('Resume / retry last job', interactive=False, scale=1)
    with gr.Accordion('Chapter progress & backend activity', open=False):
        chapter_status = gr.HTML(render_chapters(MANAGER.snapshot()))
        logs = gr.Textbox(label='Live activity log', lines=5, max_lines=8, interactive=False)
    with gr.Column(visible=False,elem_id='conversion-result') as result_group:
        gr.Markdown('### Your audiobook is ready')
        book_audio = gr.Audio(label='Listen to a short excerpt', type='filepath', interactive=False)
        download = gr.File(label='Download your complete audiobook')

    with gr.Tabs():
        with gr.Tab('Create audiobook'):
            with gr.Row():
                with gr.Column(scale=6, min_width=340):
                    gr.Markdown('### 1 · Your book')
                    book = gr.File(label='Upload PDF, EPUB, TXT or MD', file_types=['.pdf','.epub','.txt','.md'], type='filepath')
                    with gr.Row():
                        cover_image = gr.Image(label='Book cover', type='filepath', interactive=False, height=170, scale=1)
                        with gr.Column(scale=2):
                            cover_info = gr.Markdown('Cover detected after upload.')
                            with gr.Accordion('Replace artwork', open=False):
                                cover = gr.File(label='Custom JPG / PNG / WEBP', file_types=['.jpg','.jpeg','.png','.webp'], type='filepath')
                    chapter_info = gr.Markdown('Upload a book to choose chapters.')
                    with gr.Row():
                        select_all = gr.Button('Select all', size='sm')
                        select_none = gr.Button('Clear selection', size='sm')
                    chapters = gr.CheckboxGroup(choices=[], value=[], label='Chapters to narrate', elem_id='chapter-selector')
                    chapter_data = gr.State([])
                    with gr.Accordion('Check extracted text', open=False):
                        extracted = gr.Textbox(label='Beginning of the first selected chapter', lines=6, interactive=False)
                        gr.Markdown('Check the reading order before a long conversion. Scanned PDFs need OCR first.')
                    with gr.Accordion('PDF page range & section size', open=False):
                        with gr.Row():
                            first_page = gr.Number(value=1, minimum=1, precision=0, label='First page')
                            last_page = gr.Number(value=0, minimum=0, precision=0, label='Last page · 0 = end')
                        chapter_pages = gr.Slider(1,30,value=10,step=1,label='Pages per section when PDF bookmarks are unavailable')
                with gr.Column(scale=6, min_width=340):
                    gr.Markdown('### 2 · Your narrator')
                    model = gr.Dropdown(choices=list(MODELS), value=list(MODELS)[0], label='Voice model')
                    voice = gr.Dropdown(choices=VOICES['qwen17'], value='Aiden', label='Narrator')
                    model_help = gr.Markdown('Aiden and Ryan are English voices. Try the same passage with both.')
                    reference = gr.File(label='Authorized narrator recording · 6–15 seconds', file_types=['.wav','.mp3','.flac'], type='filepath', visible=False)
                    with gr.Accordion('Narration style', open=False) as tone_panel:
                        style = gr.Dropdown(choices=list(STYLES),value=list(STYLES)[0],label='Tone · Qwen 1.7B')
                        instructions = gr.Textbox(value=STYLES[list(STYLES)[0]], lines=3, label='Custom narration direction')
                    with gr.Accordion('Saved voice samples · replay instantly',open=True):
                        saved_voice = gr.Dropdown(choices=catalog.voice_choices('qwen17','Aiden'),value=None,label='Samples for this narrator')
                        sample_player = gr.Audio(label='Play saved voice sample',type='filepath',interactive=False)
                        sample_text = gr.Textbox(label='Passage read in this sample',lines=2,interactive=False)
                        samples_button = gr.Button('Create missing voice samples for this model',size='sm')
                        gr.Markdown('Creates one shared passage for every built-in voice at 1×, then saves it. First setup generates speech; later replays need no model. Uses the selected tone and seed. Custom voices use your reference recording below.')
                    audition_text = gr.Textbox(value=DEMO_TEXT,lines=3,max_lines=5,label='Voice preview text')
                    from_book = gr.Checkbox(value=False,label='Use selected book excerpt instead')
                    preview = gr.Button('Generate voice preview', variant='secondary')
                    preview_audio = gr.Audio(label='Listen to your voice preview',type='filepath',interactive=False)
                    gr.Markdown('### 3 · Pace & export')
                    speed = gr.Slider(.75,1.5,value=1.0,step=.05,label='Reading speed',info='1.0× = original. Applied to preview and export with pitch preserved; cached narration is reused.')
                    with gr.Row():
                        output_format = gr.Radio(['M4B','MP3'],value='M4B',label='File format')
                        bitrate = gr.Dropdown([96,128,192],value=128,label='Audio bitrate · kbps')
                    gr.Markdown('**M4B** keeps navigable chapter markers and cover artwork.')
                    with gr.Accordion('Pauses & consistent volume',open=False):
                        passage_gap = gr.Slider(0,1,value=0,step=.05,label='Extra pause between passages · seconds',info='Added to the short pause already present in generated audio.')
                        chapter_gap = gr.Slider(0,5,value=1,step=.25,label='Extra pause between chapters · seconds')
                        normalize = gr.Checkbox(value=True,label='Keep listening volume consistent')
                    with gr.Accordion('Advanced generation settings',open=False):
                        chunk_chars = gr.Slider(180,500,value=320,step=20,label='Characters per passage')
                        seed = gr.Number(value=42,precision=0,label='Random seed')
                        gr.Markdown('Changing the voice, style, passage size or seed creates new narration. Speed, pauses and export quality reuse saved narration.')
            gr.Markdown('Changes apply to the **next** job. The monitor shows the settings used by the running job. You may refresh this page while a job runs; keep the app terminal open.')
        with gr.Tab('Library'):
            with gr.Row():
                with gr.Column(scale=4,min_width=290):
                    gr.Markdown('### Your generations')
                    library_search=gr.Textbox(value='',label='Search books, voices or filenames',placeholder='Find a saved generation…')
                    library_kind=gr.Radio(['All','Audiobook','Voice preview'],value='All',label='Show')
                    library_sort=gr.Dropdown(['Newest first','Oldest first','Title A–Z'],value='Newest first',label='Sort')
                    refresh=gr.Button('Refresh library',size='sm')
                    library_list=gr.Radio(choices=catalog.choices(),label='Select a generation',elem_id='library-list')
                with gr.Column(scale=8,min_width=340):
                    with gr.Row():
                        library_cover=gr.Image(label='Cover',type='filepath',height=150,interactive=False,scale=1)
                        library_info=gr.HTML('Select a saved generation to listen, download or edit.',elem_id='library-detail')
                    library_player=gr.Audio(label='Listen to this generation',type='filepath',interactive=False)
                    with gr.Row():
                        excerpt_start=gr.Number(value=0,minimum=0,maximum=1440,label='Excerpt starts at · minutes')
                        excerpt_length=gr.Dropdown([30,60,120],value=60,label='Excerpt length · seconds')
                        excerpt_button=gr.Button('Play excerpt from here')
                    library_download=gr.File(label='Download complete file')
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

    model.change(update_model,model,[voice,reference,tone_panel,model_help],queue=False)
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
            instructions,seed,output_format,audition_text,from_book,speed,passage_gap,chapter_gap,normalize,bitrate]
    go.click(start_book,args,queue=False,api_name='start_book',show_progress='hidden')
    preview.click(start_preview,args,queue=False,api_name='start_preview',show_progress='hidden')
    stop.click(MANAGER.stop,queue=False,api_name='stop_job',show_progress='hidden')
    resume.click(resume_job,queue=False,api_name='resume_job',show_progress='hidden')
    samples_button.click(build_samples,args,queue=False,api_name='build_voice_samples',show_progress='hidden')
    for control in (model,voice):
        control.change(saved_voices,[model,voice],saved_voice,queue=False)
    saved_voice.change(saved_voice_audio,saved_voice,[sample_player,sample_text],show_progress='minimal')
    filters=[library_search,library_kind,library_sort]
    for control in filters:
        control.change(library_choices,filters,library_list,queue=False)
    refresh.click(library_choices,filters,library_list,queue=False).then(lambda:gr.update(choices=catalog.trash_choices(),value=None),outputs=trash_list,queue=False)
    selection_outputs=[library_cover,library_info,library_player,library_download,edit_title,edit_author,edit_filename,edit_notes,library_passage,excerpt_start]
    library_list.change(library_select,library_list,selection_outputs,api_name='library_select',show_progress='minimal')
    excerpt_button.click(play_excerpt,[library_list,excerpt_start,excerpt_length],library_player,api_name='play_excerpt')
    save_edits.click(save_library,[library_list,edit_title,edit_author,edit_filename,edit_notes,*filters],[library_list,library_feedback],api_name='save_library').then(saved_voices,[model,voice],saved_voice,queue=False)
    trash_button.click(trash_library,[library_list,*filters],[library_list,trash_list,library_feedback],api_name='trash_library').then(saved_voices,[model,voice],saved_voice,queue=False)
    restore_button.click(restore_library,[trash_list,*filters],[library_list,trash_list,library_feedback],api_name='restore_library').then(saved_voices,[model,voice],saved_voice,queue=False)
    seen = gr.State({})
    poll_outputs = [status,chapter_status,logs,go,preview,stop,resume,result_group,book_audio,download,preview_audio,library_list,saved_voice,samples_button,seen]
    poll_inputs=[seen,*filters,model,voice]
    timer = gr.Timer(1.0)
    timer.tick(poll_ui,poll_inputs,poll_outputs,queue=False,show_progress='hidden',api_name='job_status')
    demo.load(poll_ui,poll_inputs,poll_outputs,queue=False,show_progress='hidden')

if __name__ == '__main__':
    demo.queue(default_concurrency_limit=2).launch(server_name='127.0.0.1',server_port=7860,
        inbrowser=True,show_error=True,max_file_size='100mb',allowed_paths=[str(LIBRARY)],
        theme=THEME,css=CSS)
