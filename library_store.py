"""Local output catalog: playback excerpts, metadata edits and recoverable Trash."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core import LIBRARY, ffmpeg_binary

LOCK = threading.RLock()
RESERVED = {'_trash', '_cover-previews', '_audition-inputs', '_library-previews'}


def _json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def _write(path, data):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


def resolve_entry(value):
    if not value:
        raise ValueError('Select a generation first.')
    path = Path(value).resolve()
    root = LIBRARY.resolve()
    if path.parent.parent != root or path.parent.name in RESERVED or path.suffix.lower() not in ('.mp3','.m4b'):
        raise ValueError('Select a generated file from this app’s library.')
    if not path.is_file() or '.partial.' in path.name or path.name.startswith('listening-sample'):
        raise ValueError('This generation is unavailable. Refresh the library.')
    return path


def detail(value):
    path = resolve_entry(value)
    book = _json(path.parent/'book.json')
    custom = _json(path.parent/'library.json').get(path.name, {})
    return dict(path=str(path), filename=path.stem, title=custom.get('title') or ('Voice sample' if 'voice-audition-' in book.get('original','') else Path(book.get('original') or path.stem).stem),
                author=custom.get('author',''), notes=custom.get('notes',''),
                kind=custom.get('kind') or ('Voice preview' if path.name.lower().startswith('preview') else 'Audiobook'),
                model=book.get('model','Unknown'), voice=book.get('speaker','Unknown'),
                size_mb=path.stat().st_size/1024**2, modified=path.stat().st_mtime,
                format=path.suffix[1:].upper(), chapters=book.get('chapters'),
                excerpt=custom.get('excerpt',''),chapter_names=custom.get('chapter_names',[]),settings=custom.get('settings',{}),
                cover=str(path.parent/'cover.jpg') if (path.parent/'cover.jpg').is_file() else None)


def entries(query='', kind='All', sort='Newest first'):
    # Gradio can send None for untouched or cleared text/dropdown inputs.
    query = str(query or '').casefold().strip()
    kind = kind or 'All'
    sort = sort or 'Newest first'
    with LOCK:
        items=[]
        for folder in LIBRARY.iterdir():
            if not folder.is_dir() or folder.name in RESERVED:
                continue
            for path in folder.iterdir():
                if path.suffix.lower() not in ('.mp3','.m4b') or '.partial.' in path.name or path.name.startswith('listening-sample'):
                    continue
                try:
                    item=detail(path)
                except (OSError, ValueError):
                    continue
                if kind!='All' and item['kind']!=kind:
                    continue
                haystack=' '.join(str(item[x]) for x in ('title','author','model','voice','filename')).casefold()
                if query not in haystack:
                    continue
                items.append(item)
        if sort=='Title A–Z':items.sort(key=lambda x:x['title'].casefold())
        else:items.sort(key=lambda x:x['modified'],reverse=sort!='Oldest first')
        return items


def choices(query='', kind='All', sort='Newest first'):
    return [(f'{x["title"]} · {x["voice"]} · {x["format"]} · {x["size_mb"]:.1f} MB',x['path']) for x in entries(query,kind,sort)]


def preview(value, start_seconds=0, seconds=60):
    """Decode at most a short excerpt, never a complete long M4B into memory."""
    path=resolve_entry(value)
    start_seconds=float(start_seconds)
    if not 0<=start_seconds<=86400 or seconds not in (30,60,120):
        raise ValueError('Choose an excerpt start from 0 to 86,400 seconds and a 30/60/120 second excerpt.')
    if start_seconds==0 and path.suffix=='.mp3' and detail(path)['kind']=='Voice preview':
        return str(path)
    stamp=f'{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}:{start_seconds}:{seconds}'
    folder=LIBRARY/'_library-previews';folder.mkdir(exist_ok=True)
    target=folder/(hashlib.sha256(stamp.encode()).hexdigest()[:24]+'.mp3')
    with LOCK:
        if target.is_file():return str(target)
        temp=target.with_suffix('.partial.mp3')
        try:
            result=subprocess.run([ffmpeg_binary(),'-hide_banner','-loglevel','error','-nostdin','-y',
                                   '-ss',str(start_seconds),'-i',str(path),'-t',str(seconds),
                                   '-map','0:a:0','-vn','-c:a','libmp3lame','-b:a','128k',str(temp)],
                                  capture_output=True,text=True,timeout=90)
            if result.returncode or not temp.exists() or temp.stat().st_size<1000:
                raise ValueError('Could not create this excerpt. Try an earlier start time. '+result.stderr[-600:])
            temp.replace(target)
            return str(target)
        finally:
            temp.unlink(missing_ok=True)


def edit(value, title, author, notes, filename):
    with LOCK:
        path=resolve_entry(value)
        item=detail(path)
        title,author,notes,filename=(str(x or '').strip() for x in (title,author,notes,filename))
        if not title or len(title)>200 or len(author)>150 or len(notes)>4000:
            raise ValueError('Use a title up to 200 characters, author up to 150, and notes up to 4,000.')
        if not filename or len(filename)>160 or re.search(r'[<>:"/\\|?*\x00-\x1f]',filename) or filename.endswith(('.', ' ')):
            raise ValueError('Use a valid Windows filename without an extension or path.')
        if filename.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
            raise ValueError('This filename is reserved by Windows.')
        if filename.startswith('listening-sample') or '.partial' in filename:
            raise ValueError('This filename is reserved for temporary app output.')
        destination=path.with_name(filename+path.suffix)
        if destination!=path and destination.exists():
            raise ValueError('That filename already exists. Choose another; no file was overwritten.')
        temp=path.with_name('metadata-'+uuid.uuid4().hex+'.partial'+path.suffix)
        try:
            command=[ffmpeg_binary(),'-hide_banner','-loglevel','error','-nostdin','-y',
                     '-i',str(path),'-map','0:a','-map','0:v?','-c','copy','-map_metadata','0','-map_chapters','0',
                     '-metadata','title='+title,'-metadata','artist='+author,
                     '-metadata','comment='+notes]
            if path.suffix=='.m4b':command+=['-f','ipod']
            else:command+=['-id3v2_version','3','-f','mp3']
            result=subprocess.run(command+[str(temp)],capture_output=True,text=True,timeout=180)
            if result.returncode:
                raise RuntimeError('Could not save audio tags: '+result.stderr[-1000:])
            metadata=_json(path.parent/'library.json')
            metadata.pop(path.name,None)
            metadata[destination.name]={**{k:item[k] for k in ('kind','excerpt','chapter_names','settings')},'title':title,'author':author,'notes':notes}
            temp.replace(destination)
            if path!=destination:path.unlink()
            _write(path.parent/'library.json',metadata)
            index=_json(path.parent/'export-index.json')
            _write(path.parent/'export-index.json',{k:destination.name if v==path.name else v for k,v in index.items()})
            return str(destination)
        finally:
            temp.unlink(missing_ok=True)


def trash(value):
    with LOCK:
        path=resolve_entry(value)
        item=detail(path)
        trash_root=LIBRARY/'_trash';trash_root.mkdir(exist_ok=True)
        folder=trash_root/uuid.uuid4().hex;folder.mkdir()
        record={'original_folder':path.parent.name,'filename':path.name,'details':item,
                'deleted_at':datetime.now(timezone.utc).isoformat()}
        _write(folder/'record.json',record)
        shutil.move(str(path),str(folder/path.name))
        return folder.name


def trash_choices():
    root=LIBRARY/'_trash'
    if not root.exists():return []
    result=[]
    for folder in sorted(root.iterdir(),key=lambda p:p.stat().st_mtime,reverse=True):
        record=_json(folder/'record.json')
        if record and (folder/Path(record.get('filename','')).name).is_file():
            result.append((f'{record["details"]["title"]} · {record["deleted_at"][:10]}',folder.name))
    return result


def restore(identifier):
    if not re.fullmatch(r'[a-f0-9]{32}',str(identifier or '')):
        raise ValueError('Select an item in Trash.')
    with LOCK:
        folder=LIBRARY/'_trash'/identifier
        record=_json(folder/'record.json')
        parent=record.get('original_folder','')
        filename=record.get('filename','')
        if not parent or parent in ('.','..') or parent in RESERVED or Path(parent).name!=parent or not filename or Path(filename).name!=filename or '/' in filename or '\\' in filename:
            raise ValueError('This Trash record is invalid.')
        destination=LIBRARY/parent/filename
        if destination.resolve().parent.parent!=LIBRARY.resolve():
            raise ValueError('This Trash record is invalid.')
        if destination.exists():
            raise ValueError('A file with the same name exists. Rename that file before restoring this one.')
        destination.parent.mkdir(exist_ok=True)
        shutil.move(str(folder/filename),str(destination))
        (folder/'record.json').unlink()
        folder.rmdir()
        return str(destination)


def record_export(path,**values):
    with LOCK:
        metadata=_json(path.parent/'library.json')
        metadata[path.name]={**metadata.get(path.name,{}),**values}
        _write(path.parent/'library.json',metadata)


def voice_choices(model,voice=None):
    return [(f'{x["voice"]} · {x["title"]} · {x["filename"]}',x['path'])
            for x in entries(kind='Voice preview') if x['model']==model and (not voice or x['voice']==voice)]
