import os,sys,time,tempfile,wave,shutil,json
from pathlib import Path
os.environ['GRADIO_ANALYTICS_ENABLED']='False'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from gradio_client import Client,handle_file
with tempfile.TemporaryDirectory() as d:
    core.LIBRARY=Path(d)/'audiobooks';core.LIBRARY.mkdir()
    import app
    source=Path(d)/'ui-smoke.txt'
    source.write_text('This is a cached test passage for checking the interface and export. '*8)
    instruction=app.STYLES[list(app.STYLES)[0]]
    folder,pieces,_=core.plan_job(source,'qwen17','Aiden',instruction,None,1,0,10,320,42,[0])
    for piece in pieces:
        with wave.open(str(piece.wav),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\0'*24000)
    try:
        app.demo.queue().launch(server_name='127.0.0.1',server_port=7861,prevent_thread_lock=True,
                               inbrowser=False,quiet=True,allowed_paths=[str(core.LIBRARY)],css=app.CSS,
                               theme=app.gr.themes.Soft(primary_hue='sky',neutral_hue='slate'))
        client=Client('http://127.0.0.1:7861',verbose=False)
        initial=client.predict('', 'All', 'Newest first', list(app.MODELS)[0], 'Aiden', api_name='/job_status')
        assert 'READY WHEN YOU ARE' in initial[0]
        args=[handle_file(str(source)),None,['0'],list(app.MODELS)[0],'Aiden',None,1,0,10,320,
              instruction,42,'M4B',app.DEMO_TEXT,False,1.1,.1,1,True,128]
        client.predict(handle_file(str(source)),1,0,10,api_name='/inspect_chapters')
        client.predict(*args,api_name='/start_book')
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            status=client.predict('', 'All', 'Newest first', list(app.MODELS)[0], 'Aiden', api_name='/job_status')
            if app.MANAGER.snapshot()['status'] in ('done','failed'):break
            time.sleep(.1)
        s=app.MANAGER.snapshot()
        assert s['status']=='done',s
        status=client.predict('', 'All', 'Newest first', list(app.MODELS)[0], 'Aiden', api_name='/job_status')
        assert 'READY TO LISTEN' in status[0],status[0]
        fresh=Client('http://127.0.0.1:7861',verbose=False)
        assert 'READY TO LISTEN' in fresh.predict('', 'All', 'Newest first', list(app.MODELS)[0], 'Aiden', api_name='/job_status')[0]
        assert Path(s['output']).is_file()
        selected=client.predict(s['output'],api_name='/library_select')
        assert 'ui-smoke' in selected[1]
        updated=client.predict(s['output'],'Smoke Test Book','Test Author','Readable Test Book','Test note','','All','Newest first',api_name='/save_library')
        renamed=str(Path(s['output']).with_name('Readable Test Book.m4b'))
        assert Path(renamed).exists()
        client.predict(renamed,api_name='/library_select')
        client.predict(renamed,'','All','Newest first',api_name='/trash_library')
        assert not Path(renamed).exists()
        identifier=app.catalog.trash_choices()[0][1]
        client.predict(identifier,'','All','Newest first',api_name='/restore_library')
        assert Path(renamed).exists()
        print('PASS: real Gradio library selection, playback excerpt, metadata edit, rename, Trash and restore.')
        print('PASS: real Gradio upload, start event, live polling, cached export, download result and fresh client reconnect.')
    finally:
        app.demo.close()
        shutil.rmtree(folder,ignore_errors=True)
