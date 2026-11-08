"""Group downloaded versions of the same song and rank them (ported from review_downloads.py)."""
import hashlib
import re
from pathlib import Path

from .audio import EXT, LOSSLESS
from .names import COPY_SUFFIX, normalize, parse_download_filename, split_version

EDIT_GAP_SECONDS = 10         # versions further apart in length are a different edit
TRANSCODE_GAP_DB = 85         # level difference full band vs > 19.5 kHz
LESS_DETAIL_DB = 12           # versus the best version of the same song
COMPILATION = re.compile(r'\b(best of|greatest|hits|collection|anthology|compilation|vol(ume)?\.?\s*\d|'
                         r'various|bands you should know|essential|classics|now that)\b', re.I)


def find_files(sources, now, settle_seconds=120):
    """Audio files in the download folders. Files changed in the last `settle_seconds`
    are skipped (possibly still downloading)."""
    files, skipped = [], []
    for source in sources:
        source = Path(source)
        if not source.is_dir():
            continue
        for path in sorted(source.rglob('*')):
            rel = path.relative_to(source)
            if (not path.is_file() or path.suffix.lower() not in EXT
                    or any(p.startswith('.') for p in rel.parts)):
                continue
            if now - path.stat().st_mtime < settle_seconds:
                skipped.append(path)
                continue
            files.append((source, path))
    return files, skipped


def song_identity(item):
    artist = item.get('tag_artist') or ''
    title = item.get('tag_title') or ''
    guess_artist, guess_title = parse_download_filename(Path(item['path']).stem)
    artist = artist or guess_artist
    title = title or guess_title
    base, label, remix = split_version(title)
    if not label:
        label = split_version(guess_title)[1]
    return artist, base or title, label, remix


def group_files(items):
    """Group items by normalized artist + base title. Items without an artist join a
    group with the same title when exactly one artist has that title."""
    groups, no_artist = {}, []
    for item in items:
        artist, title, label, _ = song_identity(item)
        item.update(artist=artist, title=title, version_label=label)
        if normalize(artist):
            groups.setdefault((normalize(artist), normalize(title)), []).append(item)
        else:
            no_artist.append(item)
    for item in no_artist:
        same = [key for key in groups if key[1] == normalize(item['title'])]
        key = same[0] if len(same) == 1 else ('', normalize(item['title']))
        groups.setdefault(key, []).append(item)
    return list(groups.values())


def most_common(items, field):
    values = [i[field] for i in items if i[field]]
    return max(set(values), key=lambda v: (values.count(v), v)) if values else ''


def song_key(artist, title):
    return hashlib.sha1(f'{normalize(artist)}|{normalize(title)}'.encode()).hexdigest()[:12]


def annotate_group(items):
    """Warnings, identical copies, edits and the suggested pick for one song."""
    by_hash = {}
    for item in items:
        by_hash.setdefault(item['sha256'], []).append(item)
    durations = [i['duration_seconds'] for i in items if i['duration_seconds']]
    clusters = []
    for value in sorted(durations):
        if clusters and value - clusters[-1][-1] <= EDIT_GAP_SECONDS:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    main = max(clusters, key=lambda c: (len(c), max(c))) if clusters else []
    gaps = [i['hf_gap_19k_db'] for i in items if i['hf_gap_19k_db'] is not None]
    best_gap = min(gaps) if gaps else None
    for item in items:
        twins = [i['name'] for i in by_hash[item['sha256']] if i is not item]
        item['identical_to'] = twins
        item['same_audio_as'] = [i['name'] for i in items if i is not item and i['name'] not in twins
                                 and item.get('audio_md5') and i.get('audio_md5') == item['audio_md5']]
        warnings = []
        if item['status'] != 'OK':
            warnings.append('Could not be measured')
        if item['corrupt_frames']:
            warnings.append(f"{item['corrupt_frames']} decode error(s)")
        gap = item['hf_gap_19k_db']
        item['likely_transcode'] = gap is not None and gap > TRANSCODE_GAP_DB and item['codec'] not in LOSSLESS
        if item['likely_transcode']:
            warnings.append('Likely transcode: almost nothing above 19.5 kHz')
        elif gap is not None and best_gap is not None and gap - best_gap > LESS_DETAIL_DB:
            warnings.append('Less high-frequency detail than another version')
        if item['true_peak_dbtp'] is not None and item['true_peak_dbtp'] > 2:
            warnings.append(f"High peak {item['true_peak_dbtp']:+.1f} dBTP")
        item['other_edit'] = bool(main and item['duration_seconds']
                                  and not (min(main) - EDIT_GAP_SECONDS <= item['duration_seconds']
                                           <= max(main) + EDIT_GAP_SECONDS))
        if item['other_edit']:
            warnings.append('Different length: another edit or an incomplete file')
        if COMPILATION.search(item['album'] or ''):
            warnings.append('From a compilation')
        item['warnings'] = warnings
    ranked = sorted(items, key=rank_key(best_gap))
    for position, item in enumerate(ranked):
        item['rank'] = position
    return ranked[0]['path'] if ranked else None


def rank_key(best_gap):
    def key(item):
        gap = item['hf_gap_19k_db']
        return (
            item['likely_transcode'],
            item['status'] != 'OK' or item['corrupt_frames'] > 0,
            item['other_edit'],
            item['codec'] not in LOSSLESS,
            -min(item['bitrate_kbps'] or 0, 320) // 32,
            round((gap - best_gap) / 6) if gap is not None and best_gap is not None else 99,
            round((item['true_peak_dbtp'] or 0) * 2) / 2 if (item['true_peak_dbtp'] or 0) > 0 else 0,
            bool(COMPILATION.search(item['album'] or '')),
            -sum(bool(item[k]) for k in ('tag_artist', 'tag_title', 'album', 'year', 'has_art')),
            bool(COPY_SUFFIX.search(Path(item['path']).stem)),
            item['name'].lower(),
        )
    return key


def library_index(tracks):
    """Library songs (not rejected) keyed by normalized artist + base title."""
    index = {}
    for track in tracks:
        if track['kind'] == 'rejected':
            continue
        base = split_version(track['title'])[0]
        index.setdefault((normalize(track['artist']), normalize(base)), []).append(track)
    return index


def build_songs(items, library):
    """Songs with their ranked versions, the suggested pick and library copies."""
    songs = []
    for members in group_files(items):
        suggested = annotate_group(members)
        members.sort(key=lambda i: i['rank'])
        artist = most_common(members, 'artist')
        title = most_common(members, 'title')
        in_library = library.get((normalize(artist), normalize(title)), [])
        songs.append({
            'id': song_key(artist, title),
            'artist': artist, 'title': title,
            'song': f'{artist} - {title}' if artist else title,
            'suggested': suggested,
            'in_library': sorted({t['path'] for t in in_library}),
            'versions': members,
        })
    songs.sort(key=lambda s: normalize(s['song']))
    return songs
