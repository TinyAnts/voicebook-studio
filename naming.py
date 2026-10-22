"""Readable Windows-safe names; internal cache fingerprints stay out of downloads."""
import re
from pathlib import Path

MODEL_NAMES={'qwen17':'Qwen 1.7B','qwen17clone':'Qwen 1.7B','design17':'Qwen VoiceDesign','fish_s2':'Fish S2 Pro','qwen06':'Qwen 0.6B','kokoro':'Kokoro',
             'chatter_v3':'Chatterbox V3','chatter_turbo':'Chatterbox Turbo'}

def clean_name(value,limit=65):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]',' ',str(value)).replace(' · ',' ')
    value=re.sub(r'\s+',' ',value).strip(' .')[:limit].rstrip(' .') or 'Untitled'
    if value.upper().split('.')[0] in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
        value='Book '+value
    return value

def book_info(source,custom_preview=False):
    """(title, author) for names and audio tags.

    EPUB: title/creator metadata. PDF/TXT: a "Title - Author" filename is split; otherwise the
    PDF's author metadata is used when present. Missing author -> ''.
    """
    if custom_preview:return 'Voice sample',''
    source=Path(source)
    stem=re.sub(r'\s+',' ',source.stem.replace('_',' ')).strip()
    title,author=stem,''
    parts=[x.strip() for x in stem.split(' - ')]
    if len(parts)==2 and all(parts) and len(parts[1])<=40 and 1<=len(parts[1].split())<=5:
        title,author=parts
    try:
        if source.suffix.lower()=='.epub':
            from ebooklib import epub
            book=epub.read_epub(str(source),options={'ignore_ncx':True})
            meta_title=book.get_metadata('DC','title');meta_author=book.get_metadata('DC','creator')
            if meta_title and meta_title[0][0].strip():title=meta_title[0][0].strip()
            if meta_author and meta_author[0][0].strip():author=meta_author[0][0].strip()
        elif source.suffix.lower()=='.pdf' and not author:
            import pymupdf
            with pymupdf.open(str(source)) as doc:
                meta=(doc.metadata or {}).get('author','') or ''
            if meta.strip() and len(meta)<=60 and meta.strip().lower() not in {'unknown','admin','user','author'}:
                author=meta.strip()
    except Exception:
        pass
    return clean_name(title,90),clean_name(author,60) if author else ''


def display_title(source,custom_preview=False):
    return book_info(source,custom_preview)[0]

def export_name(title,pieces,model,voice,speed,preview=False,custom_preview=False,author='',full_book=False):
    chapters=list(dict.fromkeys(p.chapter for p in pieces))
    parts=['Preview'] if preview else []
    parts.append(clean_name(title,48))
    if author and author.casefold() not in title.casefold():
        parts.append(clean_name(author,30))
    if full_book and not preview:
        parts.append('Full book')
    elif not custom_preview:
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
