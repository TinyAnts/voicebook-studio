"""Narrator catalogue: Qwen built-in speakers plus designed / cloned narrators.

* Built-in (Qwen 1.7B CustomVoice): Aiden, Ryan. Style instructions apply.
* Library narrators: a short reference recording (made once with Qwen VoiceDesign) that the
  Qwen 1.7B Base model clones for every passage, so the voice stays the same for a whole book.
  Shipped presets live in ./voices/<id>/; narrators you design or record live in
  audiobooks/_voices/<id>/ (your data, kept across updates).
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRESET_DIR = ROOT / 'voices'

BUILTIN = {
    'Aiden': 'Aiden · young American man · bright, clear (built-in)',
    'Ryan': 'Ryan · young man · energetic, rhythmic (built-in)',
}
BUILTIN_SHORT = {'Aiden': 'man · 20s · American', 'Ryan': 'man · 20s · energetic'}
# Every narrator's ready-made sample reads this passage (made once, played instantly in the app).
SAMPLE_TEXT = ('The farmhouse stood at the edge of a quiet valley. By morning, the clouds '
               'had cleared, and the first light moved across the hills. There was work to be '
               'done, but for a moment, everything was still.')

# Reference passage read by every designed narrator (~12 s). The clone model needs the exact words.
REFERENCE_TEXT = ('The old house at the end of the lane had stood empty for many years. '
                  'Each autumn, the leaves gathered on its steps, and the village children '
                  'wondered who had lived there, and why they had never come back.')

PRESETS = [
    dict(id='arthur', short='man · 70s · British', name='Arthur', label='older man · 70s · deep, warm British storyteller',
         instruct='An elderly British man in his seventies with a deep, warm, slightly gravelly voice. '
                  'Calm, kind grandfather telling a story by the fire. Slow, steady pace, clear diction.'),
    dict(id='eleanor', short='woman · 60s · British', name='Eleanor', label='older woman · 60s · gentle, refined British',
         instruct='A woman in her sixties with a warm, gentle, refined British accent. Soft but clear, '
                  'unhurried and kind, like a favourite aunt reading a classic novel aloud.'),
    dict(id='james', short='man · 40s · American', name='James', label='middle-aged man · 40s · calm American documentary',
         instruct='A middle-aged American man in his forties with a deep, smooth, calm baritone. '
                  'Confident documentary narrator, measured pace, natural and trustworthy.'),
    dict(id='claire', short='woman · 40s · American', name='Claire', label='middle-aged woman · 40s · clear American, nonfiction',
         instruct='An American woman in her forties with a clear, confident, warm mid-range voice. '
                  'Professional nonfiction audiobook narrator, articulate and engaging, steady pace.'),
    dict(id='henry', short='man · 50s · British', name='Henry', label='middle-aged man · 50s · measured British',
         instruct='A British man in his fifties with a rich, warm, measured voice. Thoughtful and '
                  'articulate, like a respected radio presenter reading history. Unhurried, precise diction.'),
    dict(id='victoria', short='woman · 50s · British', name='Victoria', label='middle-aged woman · 50s · crisp British literary',
         instruct='A British woman in her fifties with a crisp, elegant, authoritative voice. Literary '
                  'audiobook narrator with poise and quiet intensity, perfect enunciation.'),
    dict(id='marcus', short='man · 30s · deep, dramatic', name='Marcus', label='man · 30s · deep, dramatic thriller',
         instruct='A man in his thirties with a deep, resonant, slightly husky voice. Dramatic thriller '
                  'narrator with tension and gravitas, controlled and intense, never shouting.'),
    dict(id='sophie', short='woman · 20s · American', name='Sophie', label='young woman · 20s · bright, friendly American',
         instruct='A young American woman in her mid twenties with a bright, friendly, expressive voice. '
                  'Warm and natural, like a modern fiction narrator, lively but not rushed.'),
    dict(id='grace', short='woman · 30s · soft, calm', name='Grace', label='woman · 30s · soft, soothing bedtime',
         instruct='A woman in her thirties with a very soft, soothing, gentle voice. Slow and relaxed, '
                  'calm breathing, perfect for bedtime stories and meditation. Quiet and tender.'),
    dict(id='priya', short='woman · 30s · Indian English', name='Priya', label='woman · 30s · warm Indian English',
         instruct='An Indian woman in her thirties speaking fluent English with a natural Indian accent. '
                  'Warm, clear and articulate, friendly and engaging nonfiction narrator.'),
]


def custom_dir():
    from core import LIBRARY
    path = LIBRARY / '_voices'
    path.mkdir(exist_ok=True)
    return path


def _read(folder: Path):
    try:
        data = json.loads((folder / 'voice.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    wav = folder / 'reference.wav'
    if not wav.is_file() or not data.get('ref_text'):
        return None
    data['reference'] = str(wav)
    return data


def library_narrators():
    """Narrators that have a usable reference recording, presets first."""
    found = []
    for folder in sorted(PRESET_DIR.glob('*')) if PRESET_DIR.is_dir() else []:
        item = _read(folder)
        if item:
            found.append({**item, 'kind': 'preset'})
    for folder in sorted(custom_dir().glob('*')):
        item = _read(folder)
        if item:
            found.append({**item, 'kind': 'custom'})
    return found


PRESET_BY_ID = {p['id']: p for p in PRESETS}


def choices():
    """(label, value) pairs for the narrator picker: men, then women, then your own narrators.

    Value = 'Aiden' / 'Ryan' / 'voice:<id>'.
    """
    rows = [(f'{name} · {BUILTIN_SHORT[name]}', name, 'man', 0) for name in BUILTIN]
    order = [p['id'] for p in PRESETS]
    for v in library_narrators():
        preset = PRESET_BY_ID.get(v['id'])
        if preset and v['kind'] == 'preset':
            gender = 'woman' if preset['short'].startswith('woman') else 'man'
            rows.append((f"{v['name']} · {preset['short']}", 'voice:' + v['id'], gender, order.index(v['id']) + 1))
        else:
            rows.append((f"{v['name']} · yours", 'voice:' + v['id'], 'zz', 999))
    rows.sort(key=lambda r: ({'man': 0, 'woman': 1}.get(r[2], 2), r[3]))
    return [(label, value) for label, value, _g, _o in rows]


def describe(value):
    """(name, one-line description, kind) for the narrator card."""
    if value in BUILTIN:
        return value, BUILTIN[value].split(' · ', 1)[1], 'builtin'
    wanted = str(value or '')[6:]
    for v in library_narrators():
        if v['id'] == wanted:
            preset = PRESET_BY_ID.get(v['id'])
            text = preset['label'] if preset and v['kind'] == 'preset' else (v.get('description') or v.get('label') or 'your narrator')
            return v['name'], text, v['kind']
    return str(value), '', 'missing'


def ready_sample(value):
    """Path of a ready-made Qwen sample for this narrator (no model needed), or None."""
    if value in BUILTIN:
        path = PRESET_DIR / '_builtin' / f'{value.lower()}.mp3'
        return path if path.is_file() else None
    wanted = str(value or '')[6:]
    for v in library_narrators():
        if v['id'] == wanted:
            sample = Path(v['reference']).with_name('sample-qwen.mp3')
            return sample if sample.is_file() else Path(v['reference'])
    return None


def resolve(value):
    """Map a Narrator value to (model_id, speaker_name, reference_path_or_None, ref_text)."""
    value = str(value or 'Aiden')
    if value in BUILTIN:
        return 'qwen17', value, None, ''
    if value.startswith('voice:'):
        wanted = value[6:]
        for v in library_narrators():
            if v['id'] == wanted:
                return 'qwen17clone', v['name'], Path(v['reference']), v['ref_text']
        raise ValueError('That narrator is no longer available. Pick another narrator.')
    raise ValueError(f'Unknown narrator: {value}')


def display_name(value):
    try:
        return resolve(value)[1]
    except ValueError:
        return str(value)


def new_custom_folder(name: str) -> Path:
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:30] or 'narrator'
    folder = custom_dir() / f'{slug}-{uuid.uuid4().hex[:6]}'
    folder.mkdir(parents=True)
    return folder


def save_custom(folder: Path, name: str, label: str, ref_text: str, description: str = '', source: str = 'design'):
    data = dict(id=folder.name, name=name.strip()[:40] or 'Narrator', label=label.strip()[:80],
                description=description.strip()[:600], ref_text=ref_text.strip(), source=source)
    (folder / 'voice.json').write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return 'voice:' + folder.name


def import_recording(path, name: str, transcript: str):
    """Use your own (authorized) recording as a narrator. The transcript must match the audio."""
    path = Path(path)
    if path.suffix.lower() not in ('.wav', '.mp3', '.flac', '.m4a', '.ogg'):
        raise ValueError('Use a WAV, MP3, FLAC, M4A or OGG recording.')
    transcript = ' '.join(str(transcript or '').split())
    if len(transcript) < 20:
        raise ValueError('Type exactly what is said in the recording (at least a sentence).')
    import subprocess
    from core import ffmpeg_binary
    folder = new_custom_folder(name)
    target = folder / 'reference.wav'
    result = subprocess.run([ffmpeg_binary(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(path),
                             '-t', '20', '-ac', '1', '-ar', '24000', str(target)], capture_output=True, text=True, timeout=60)
    if result.returncode or not target.is_file():
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError('Could not read that recording: ' + result.stderr[-300:])
    return save_custom(folder, name, 'your recording', transcript, source='recording')


def delete_custom(value):
    if not str(value).startswith('voice:'):
        raise ValueError('Only narrators you created can be removed.')
    folder = custom_dir() / str(value)[6:]
    if folder.parent != custom_dir() or not folder.is_dir():
        raise ValueError('Only narrators you created can be removed.')
    shutil.rmtree(folder)
