"""Optional real-browser visual check. Uses temporary books/audio, no GPU.
Install Playwright for this developer check, then `python -m playwright install chromium`.
Set VOICEBOOK_AXE_SCRIPT to axe-core's axe.min.js to enable text contrast checks.
Screenshots are local review material, not application data or bundled recordings.
"""
import os,sys,tempfile,time,json,math,struct,wave
from pathlib import Path
os.environ['GRADIO_ANALYTICS_ENABLED']='False'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from PIL import Image,ImageDraw
import core
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('VOICEBOOK_SCREENSHOT_DIR',str(ROOT/'visual-review')));OUT.mkdir(parents=True,exist_ok=True)
AXE_SCRIPT=os.environ.get('VOICEBOOK_AXE_SCRIPT')
def audit(page,name):
 if not AXE_SCRIPT:
  print('Contrast scan skipped: set VOICEBOOK_AXE_SCRIPT to a local axe.min.js path.',flush=True)
  return
 if not page.evaluate('typeof window.axe !== "undefined"'):
  page.add_script_tag(path=AXE_SCRIPT)
 result=page.evaluate("async () => await axe.run(document,{runOnly:{type:'rule',values:['color-contrast']}})")
 (OUT/(name+'-contrast.json')).write_text(json.dumps(result,indent=2))
 assert not result['violations'], result['violations']
 print('CONTRAST',name,[{'id':v['id'],'nodes':[{'target':n['target'],'message':n['failureSummary']} for n in v['nodes']]} for v in result['violations']],flush=True)

TEMP=tempfile.TemporaryDirectory(prefix='voicebook-visual-')
core.LIBRARY=Path(TEMP.name)/'audiobooks';core.LIBRARY.mkdir()
folder=core.LIBRARY/'sample-book';folder.mkdir()
(folder/'book.json').write_text(json.dumps(dict(original='The Quiet Valley.epub',model='qwen17',speaker='Aiden',chapters=3)))
cover=Image.new('RGB',(400,400),'#434b3b');draw=ImageDraw.Draw(cover);draw.text((45,110),'THE QUIET\nVALLEY',fill='#f2efe8',font_size=48,spacing=12);draw.text((45,310),'VISUAL TEST BOOK',fill='#c8c1b7',font_size=18);cover.save(folder/'cover.jpg')
wav=folder/'test.wav'
with wave.open(str(wav),'wb') as out:
 out.setnchannels(1);out.setsampwidth(2);out.setframerate(24000)
 out.writeframes(b''.join(struct.pack('<h',int(2000*math.sin(2*math.pi*300*i/24000))) for i in range(72000)))
pieces=[core.Piece('01 · A New Beginning','A sample passage for the visual test.',1,wav)]
book=core.assemble(folder,pieces,folder/'The Quiet Valley - Aiden.m4b','The Quiet Valley',normalize=False)
preview=core.assemble(folder,pieces,folder/'Preview - Aiden.mp3','Voice sample',normalize=False)
import app
app.catalog.record_export(preview,title='Voice sample',kind='Voice preview',excerpt=app.DEMO_TEXT)
state=dict(status='running',stage='narrating',job_id='visual-fixture',title='The Quiet Valley',kind='Audiobook',
 model='qwen17',voice='Aiden',speed=1.1,total=48,completed=19,cached=4,started_at=time.monotonic()-380,
 generated_count=15,generated_chars=4400,generated_seconds=360,total_chars=14000,completed_chars=5400,
 current_started_at=time.monotonic()-8,last_progress_at=time.monotonic()-8,heartbeat_at=time.monotonic()-1,
 current_chapter='02 · Across the hills',excerpt='The farmhouse stood at the edge of a quiet valley. By morning, the clouds had cleared, and the first light moved across the hills.',
 device='NVIDIA GeForce RTX 3070',vram_used_gb=5.2,message='Saved passage 19 of 48. Narrating the next passage…',
 chapters=[dict(title='01 · A New Beginning',done=12,total=12),dict(title='02 · Across the hills',done=7,total=16),dict(title='03 · Home again',done=0,total=20)])
app.MANAGER.update(**state)
app.demo.queue().launch(server_name='127.0.0.1',server_port=7863,prevent_thread_lock=True,inbrowser=False,quiet=True,
                       theme=app.THEME,css=app.CSS,allowed_paths=[str(core.LIBRARY)])
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport=dict(width=1440,height=1080),device_scale_factor=1,color_scheme='dark')
  errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('http://127.0.0.1:7863',wait_until='domcontentloaded')
  page.get_by_text('Saved passage 19 of 48.',exact=False).wait_for()
  page.wait_for_timeout(800)
  page.screenshot(path=str(OUT/'01_conversion_desktop.png'),full_page=True)
  page.screenshot(path=str(OUT/'01_conversion_viewport.png'))
  (OUT/'dom.txt').write_text(page.locator('body').inner_text())
  print('MAIN SCREEN',page.title(),flush=True)
  audit(page,'conversion')
  page.get_by_text('Chapter progress & backend activity',exact=True).click()
  page.screenshot(path=str(OUT/'02_progress_details.png'),full_page=True)
  page.get_by_text('Chapter progress & backend activity',exact=True).click()
  app.MANAGER.update(status='done',stage='sample',completed=48,finished_at=time.monotonic(),output=str(book),audio=str(preview),message='Your audiobook is ready to download.',chapters=[{**c,'done':c['total']} for c in state['chapters']])
  page.get_by_text('READY TO LISTEN',exact=True).wait_for()
  page.get_by_role('tab',name='Library').click()
  page.get_by_label('Select a generation').count()
  page.get_by_role('radio',name=__import__('re').compile('The Quiet Valley.*M4B')).check()
  page.locator('#library-detail').get_by_text(__import__('re').compile('Saved ')).wait_for()
  page.get_by_text('Rename & edit details',exact=True).click()
  page.get_by_label('Title',exact=True).wait_for()
  page.screenshot(path=str(OUT/'03_library_desktop.png'),full_page=True)
  audit(page,'library')
  page.get_by_label('Search books, voices or filenames',exact=True).fill('Valley')
  page.get_by_label('Search books, voices or filenames',exact=True).fill('')
  page.wait_for_timeout(1500)
  assert not page.get_by_text("'NoneType' object has no attribute",exact=False).count()
  # Capture the library at mobile width and check horizontal overflow.
  page.get_by_role('radio',name=__import__('re').compile('The Quiet Valley.*M4B')).check()
  page.locator('#library-detail').get_by_text(__import__('re').compile('Saved ')).wait_for()
  page.set_viewport_size(dict(width=390,height=844))
  page.wait_for_timeout(500)
  page.screenshot(path=str(OUT/'04_library_mobile.png'),full_page=True)
  page.screenshot(path=str(OUT/'04_mobile_viewport.png'))
  assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Page overflows on mobile'
  print('MOBILE WIDTH',page.evaluate('({viewport:innerWidth,document:document.documentElement.scrollWidth})'),flush=True)
  page.set_viewport_size(dict(width=1440,height=1080))
  page.get_by_role('tab',name='Create audiobook',exact=True).click()
  page.get_by_role('combobox',name='Voice model',exact=True).click()
  page.wait_for_timeout(300)
  page.screenshot(path=str(OUT/'05_dropdown.png'),full_page=True)
  audit(page,'dropdown')
  page.keyboard.press('Escape')
  page.emulate_media(color_scheme='light')
  page.goto('http://127.0.0.1:7863/?__theme=light',wait_until='domcontentloaded')
  page.get_by_text('READY TO LISTEN',exact=True).wait_for()
  page.screenshot(path=str(OUT/'06_light_preference.png'),full_page=True)
  audit(page,'light-preference')
  app.MANAGER.update(status='running',stage='loading',message='Loading the voice model for this visual check…')
  page.get_by_text('Loading the voice model for this visual check…',exact=True).wait_for()
  page.screenshot(path=str(OUT/'07_loading.png'))
  audit(page,'loading')
  app.MANAGER.update(status='failed',message='Test error: voice model could not start. Saved passages are available to resume.')
  page.get_by_text('NEEDS ATTENTION',exact=True).wait_for()
  page.screenshot(path=str(OUT/'08_error.png'))
  audit(page,'error')
  print('ERRORS',errors,flush=True)
  assert not errors, errors
  print('BODY COLORS',page.locator('.gradio-container').evaluate('(e)=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor})'),flush=True)
  browser.close()
finally:
 app.demo.close();TEMP.cleanup()
