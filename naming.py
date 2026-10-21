"""Readable Windows-safe names; internal cache fingerprints stay out of downloads."""
import re
from pathlib import Path

MODEL_NAMES={'qwen17':'Qwen 1.7B','qwen06':'Qwen 0.6B','kokoro':'Kokoro',
             'chatter_v3':'Chatterbox V3','chatter_turbo':'Chatterbox Turbo'}

def clean_name(value,limit=65):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',str(value)).replace(' · ',' ')
    value=re.sub(r'\s+',' ',value).strip(' .')[:limit].rstrip(' .') or 'Untitled'
    if value.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
        value='Book '+value
    return value

def display_title(source,custom_preview=False):
    if custom_preview:return 'Voice sample'
    title=Path(source).stem.replace('_',' ')
    try:
        if Path(source).suffix.lower()=='.epub':
            from ebooklib import epub
            metadata=epub.read_epub(str(source),options={'ignore_ncx':True}).get_metadata('DC','title')
            if metadata and metadata[0][0].strip():title=metadata[0][0]
    except Exception:
        pass
    return clean_name(title,90)

def export_name(title,pieces,model,voice,speed,preview=False,custom_preview=False):
    chapters=list(dict.fromkeys(p.chapter for p in pieces))
    parts=['Preview'] if preview else []
    parts.append(clean_name(title,48))
    if not custom_preview:
        if len(chapters)==1:
            chapter=clean_name(chapters[0],40)
            if chapter.casefold()!=clean_name(title,40).casefold():parts.append(chapter)
        elif chapters:
            numbers=[re.match(r'\d+',c).group() for c in chapters if re.match(r'\d+',c)]
            consecutive=numbers and [int(x) for x in numbers]==list(range(int(numbers[0]),int(numbers[-1])+1))
            parts.append('Chapters '+(f'{numbers[0]}-{numbers[-1]}' if consecutive else ', '.join(numbers)) if numbers else f'{len(chapters)} chapters')
    parts.extend([clean_name(voice,22),MODEL_NAMES.get(model,model),f'{speed:g}x'])
    return clean_name(' - '.join(parts),150)

def unique_path(folder,stem,extension):
    path=folder/(stem+'.'+extension)
    count=2
    while path.exists():
        path=folder/(stem+f' ({count}).'+extension);count+=1
    return path
