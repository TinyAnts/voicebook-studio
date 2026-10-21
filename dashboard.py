"""Accessible, escaped status markup. Percentages measure each named stage."""
import html
import time


def duration(seconds):
    if seconds is None:
        return '—'
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f'{seconds//3600}h {(seconds%3600)//60:02d}m'
    if seconds >= 60:
        return f'{seconds//60}m {seconds%60:02d}s'
    return f'{seconds}s'


def narration_eta(s, now):
    if s.get('stage') != 'narrating' or s.get('generated_count', 0) < 2 or not s.get('generated_chars'):
        return None
    rate = s['generated_seconds'] / s['generated_chars']
    remaining = max(0, s['total_chars'] - s['completed_chars']) * rate
    current_elapsed = now - s.get('current_started_at', now)
    return max(0, remaining - current_elapsed)


def render_status(s, now=None):
    now = now or time.monotonic()
    esc = lambda x: html.escape(str(x))
    state = s.get('status', 'idle')
    stage = s.get('stage', 'prepare')
    busy = state in ('running', 'stopping')
    total = s.get('total', 0)
    done = s.get('completed', 0)
    fraction = done/total if total else 0
    if state == 'idle':
        return '<section class="job-card"><div class="eyebrow">READY WHEN YOU ARE</div><h2>Your next audiobook starts here.</h2><p>Add a book below, choose a narrator, and listen to a preview before you begin.</p></section>'
    stages = [('prepare', 'Prepare book'), ('loading', 'Load voice'), ('narrating', 'Narrate'), ('export', 'Export audio')]
    position = ['prepare', 'loading', 'narrating', 'export', 'sample'].index(stage)
    steps = []
    for i, (_, label) in enumerate(stages):
        style = 'finished' if state == 'done' or i < position else 'active' if i == position else ''
        steps.append(f'<span class="step {style}"><b>{"✓" if style == "finished" else i+1}</b>{label}</span>')
    label = 'Narration complete'
    percent = fraction*100
    indeterminate = busy and stage in ('prepare', 'loading', 'sample')
    if stage == 'export':
        label, percent = 'Audio export', s.get('export_fraction', 0)*100
    elif stage == 'narrating':
        label = 'Narration · completed passages'
    elif stage == 'sample':
        label, percent = 'Preparing listening sample', 100
    elif stage in ('prepare', 'loading'):
        label = 'Preparing your book' if stage == 'prepare' else 'Loading or downloading voice model'
    if state == 'done':
        label, percent = 'Completed', 100
    if indeterminate:
        meter = f'<progress class="job-progress" aria-label="{esc(label)}"></progress>'
        value = 'Working…'
    else:
        meter = f'<progress class="job-progress" max="100" value="{percent:.2f}" aria-label="{esc(label)}"></progress>'
        value = f'{percent:.0f}%'
    end = s.get('finished_at') or now
    elapsed = duration(end - s.get('started_at', now))
    eta = narration_eta(s, now) if busy else None
    estimate = ('About ' + duration(eta)) if eta and eta >= 1 else ('Learning your speed…' if stage == 'narrating' and busy and s.get('generated_count', 0)<2 else 'Recalculating…' if stage == 'narrating' and busy else '—')
    chapter_done = sum(c['done']==c['total'] for c in s.get('chapters', []))
    chapter_count = len(s.get('chapters', []))
    metrics = [('Elapsed',elapsed), ('Narration remaining*',estimate),
               ('Passages saved',f'{done:,} / {total:,}'), ('Chapters narrated',f'{chapter_done} / {chapter_count}')]
    metric_html = ''.join(f'<div class="metric"><span>{label}</span><strong>{esc(value)}</strong></div>' for label,value in metrics)
    statuses = {'running':'IN PROGRESS','stopping':'STOPPING','stopped':'STOPPED · SAVED','failed':'NEEDS ATTENTION','done':'READY TO LISTEN'}
    current = ''
    if stage == 'narrating' and busy and s.get('excerpt'):
        current = f'<div class="current-passage"><strong>Reading: {esc(s.get("current_chapter", ""))}</strong><p>{esc(s["excerpt"][:350])}{"…" if len(s["excerpt"])>350 else ""}</p></div>'
    heartbeat = ''
    if busy:
        age = now - s.get('last_progress_at', now)
        signal = s.get('heartbeat_at', 0)
        if stage in ('loading', 'narrating'):
            heartbeat = ('Worker signal ' + duration(now-signal) + ' ago' if signal else 'Waiting for worker to start')
            heartbeat += ' · last progress update ' + duration(age) + ' ago'
            if age > 90:
                heartbeat += ' · No recent progress; the process may still be busy. Check the activity log below.'
        elif stage in ('export','sample'):
            heartbeat = 'Encoding locally · last progress update ' + duration(age) + ' ago'
    settings = f'{s.get("model", "")} · {s.get("voice", "")} · {s.get("speed", 1):g}× export speed'
    if s.get('sample_total',1)>1:
        settings += f' · Voice sample {s["sample_index"]} of {s["sample_total"]}'
    device = s.get('device', '')
    if s.get('vram_used_gb') is not None:
        device += f' · {s["vram_used_gb"]:.1f} GB reserved by voice model'
    foot = f'{s.get("cached", 0)} cached passages reused. *Estimate covers narration only; model loading and export are separate.'
    return f'''<section class="job-card {esc(state)}">
    <div class="job-top"><div><div class="eyebrow">{statuses.get(state,'READY')}</div><h2>{esc(s.get('title','Audiobook'))}</h2></div><span class="job-kind">{esc(s.get('kind',''))}</span></div>
    <div class="job-settings">{esc(settings)}</div><div class="stages">{''.join(steps)}</div>
    <div class="progress-label"><strong>{esc(label)}</strong><strong>{value}</strong></div>{meter}
    <div class="job-message" role="status" aria-live="polite">{esc(s.get('message',''))}</div>
    <div class="metrics">{metric_html}</div>{current}<div class="worker-line">{esc(device)}<br>{esc(heartbeat)}</div>
    <div class="job-foot">{esc(foot)}</div></section>'''


def render_chapters(s):
    rows = s.get('chapters', [])
    if not rows:
        return '<p class="muted">Chapter progress appears when a conversion starts.</p>'
    body = []
    for row in rows:
        status = 'Done' if row['done']==row['total'] else 'Reading' if row['title']==s.get('current_chapter') and s['status']=='running' else 'Saved partially' if row['done'] else 'Waiting'
        body.append(f'<tr><td>{html.escape(row["title"])}</td><td>{row["done"]} / {row["total"]}</td><td>{status}</td></tr>')
    return '<div class="chapter-table"><table><thead><tr><th>Chapter</th><th>Passages saved</th><th>Status</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'
