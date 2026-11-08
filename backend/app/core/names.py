"""Names: comparison keys, artist/title from filenames, version labels.

`normalize` is the key used for library and download songs. Spotify matching
uses its own, looser rules in `matching.py`.
"""
import re
import unicodedata

VERSION_WORDS = re.compile(
    r'remaster(ed)?|album|single|radio|edit|version|extended|original|mix|12|7|bonus|live|demo|'
    r'mono|stereo|re-?recorded|explicit|clean|instrumental|vocal|club|dub|reprise', re.I)
REMIX_WORDS = re.compile(r'\b(re-?mix|rmx|remake|rework|bootleg|dub)\b', re.I)
COPY_SUFFIX = re.compile(r'\s*\(\d{1,2}\)$')


def normalize(text):
    """Comparison key: ASCII, lower case, no apostrophes, no leading 'the'."""
    text = re.sub("['’‘`\x92´]", '', text or '')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    text = re.sub(r'[^a-z0-9]+', ' ', text.replace('&', ' and ')).strip()
    return re.sub(r'^the ', '', text)


def guess_from_filename(stem):
    """Artist/title from library names like '01 - Artist - Title'."""
    stem = re.sub(r"^\s*\(?\d{1,3}\)?\s*[-.\s_]\s*", "", stem)
    parts = [p.strip() for p in re.split(r"\s+-\s+", stem) if p.strip()]
    if len(parts) >= 2:
        return {"artist": parts[0], "title": parts[-1]}
    return {"title": stem.strip()}


def parse_download_filename(stem):
    """Best-effort (artist, title) from a download filename (Soulseek, stores, scene names)."""
    stem = COPY_SUFFIX.sub('', stem).strip()
    stem = re.sub(r'-[0-9a-f]{8}$', '', stem)                 # store hash suffixes
    scene = '_' in stem and ' ' not in stem                   # e.g. 03-artist_name-title
    stem = stem.replace('_', ' ')
    separator = r'-' if scene else r'\s+-\s+|\s+-(?=\S)|(?<=\S)-\s+'
    parts = [p.strip() for p in re.split(separator, stem) if p.strip()]
    parts = [p for p in parts if not re.fullmatch(r'\d{1,4}\.?', p)]   # bare track numbers
    if parts:
        parts[0] = re.sub(r'^\(?\d{1,4}\)?(?:[-.]\d{1,3})?[.)\-\s]+', '', parts[0]).strip() or parts[0]
        parts[-1] = re.sub(r'^\d{1,3}[.\s]+', '', parts[-1]).strip() or parts[-1]
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return '', parts[0] if parts else stem


def split_version(title):
    """(base title, version label, is_remix) from a title like 'Song (Remastered 2009)'."""
    labels = []
    remix = False

    def take(match):
        nonlocal remix
        inner = match.group(1).strip()
        if re.match(r'(feat|ft)\b\.?', inner, re.I):
            return ' '
        if REMIX_WORDS.search(inner):
            remix = True
            return match.group(0)
        if VERSION_WORDS.search(inner):
            labels.append(inner)
            return ' '
        return match.group(0)

    base = re.sub(r'[(\[]([^()\[\]]*)[)\]]', take, title or '')
    base = re.sub(r'\s+(feat|ft)\.?\s.*$', '', base, flags=re.I)
    tail = re.search(r'\s+-\s+([^-]+)$', base)
    if tail:
        if REMIX_WORDS.search(tail.group(1)):
            remix = True
        elif VERSION_WORDS.search(tail.group(1)):
            labels.append(tail.group(1).strip())
            base = base[:tail.start()]
    return re.sub(r'\s+', ' ', base).strip(), ', '.join(labels), remix


def song_folder_name(song):
    """Folder name for a song's rejected versions (a new folder, never a renamed file)."""
    name = re.sub(r'[/:\x00-\x1f]+', "-", song or "").strip().lstrip(".").strip()
    return name[:120].rstrip() or "Unknown song"
