"""Group downloaded versions of the same song and rank them."""
import difflib
import hashlib
import re
from pathlib import Path

from .audio import EXT, LOSSLESS
from .names import COPY_SUFFIX, is_similar, normalize, parse_download_filename, split_version, strip_remaster

EDIT_GAP_SECONDS = 10         # versions further apart in length are a different edit
TRANSCODE_GAP_DB = 85         # level difference full band vs > 19.5 kHz
LESS_DETAIL_DB = 12           # versus the best version of the same song
ACCEPTED_SUFFIX = '.mp3'      # only MP3 downloads go to the library


def not_mp3_reason(item):
    """Why a download is not an accepted MP3, or '' when it is."""
    suffix = Path(item['path']).suffix.lower()
    if suffix != ACCEPTED_SUFFIX:
        return f"Not an MP3 ({suffix.lstrip('.').upper() or 'no extension'}): only MP3 files are accepted"
    codec = item.get('codec') or ''
    if codec and codec != 'mp3':
        return f"Named .mp3 but the audio is {codec}: only MP3 files are accepted"
    return ''


COMPILATION = re.compile(r'\b(best of|greatest|hits|collection|anthology|compilation|vol(ume)?\.?\s*\d|'
                         r'various|bands you should know|essential|classics|now that)\b', re.I)


def find_files(sources, now, settle_seconds=120, finished=()):
    """Audio files in the download folders. Files changed in the last `settle_seconds`
    are skipped (possibly still downloading), unless they are in `finished` (resolved paths
    of downloads known to be complete)."""
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
            if now - path.stat().st_mtime < settle_seconds and str(path.resolve()) not in finished:
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


def inbox_name(song, item):
    """(artist, title) to name the kept file: the song's artist and the version's full title,
    so remix and version labels stay in the name. A plain "remaster" label is left out."""
    title = item.get('tag_title') or parse_download_filename(Path(item['path']).stem)[1]
    return song.get('artist') or item.get('artist') or '', strip_remaster(title or song.get('title') or '')


def missing_info(song, kept):
    """Album and year for the kept version when it has none: taken from the best other version
    of the song that is not from a compilation. Used to fill empty tags, never to replace them."""
    out = {}
    for key in ('album', 'year'):
        if kept.get(key):
            continue
        for other in song['versions']:
            if other is kept or not other.get(key) or COMPILATION.search(other.get('album') or ''):
                continue
            out[key] = other[key]
            break
    return out


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
    return merge_similar_groups(list(groups.values()))


# --- Songs that are probably the same under different names ---------------------------------

FILE_JUNK = {'mp3', 'wmv', 'wma', 'flac', 'wav', 'm4a', 'aac', 'ogg', 'aif', 'aiff', 'mp4', 'avi', 'www'}
FUZZY_RATIO = 0.92            # whole-name similarity that counts as a typo, not another song


def _tokens(text):
    return [t for t in normalize(text).split() if t not in FILE_JUNK]


def _artist_related(a, b):
    """Same artist written differently: equal, one contains the other, or an acronym (DAF)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if set(ta) <= set(tb) or set(tb) <= set(ta):
        return True
    for short, long_ in ((ta, tb), (tb, ta)):
        words = [w for w in long_ if w != 'and']
        if len(short) == 1 and len(words) > 1 and short[0] == ''.join(w[0] for w in words):
            return True
    return False


def _group_identity(members):
    return most_common(members, 'artist'), most_common(members, 'title')


def _same_song(a, b):
    """Whether two groups are probably one song. Conservative: remixes never match because
    the remix label stays in the title."""
    if {i['sha256'] for i in a if i.get('sha256')} & {i['sha256'] for i in b if i.get('sha256')}:
        return True
    if {i['audio_md5'] for i in a if i.get('audio_md5')} & {i['audio_md5'] for i in b if i.get('audio_md5')}:
        return True
    (artist_a, title_a), (artist_b, title_b) = _group_identity(a), _group_identity(b)
    full_a, full_b = _tokens(f'{artist_a} {title_a}'), _tokens(f'{artist_b} {title_b}')
    if full_a == full_b:
        return True
    if artist_a and artist_b and _tokens(title_a) == _tokens(title_b) and _artist_related(artist_a, artist_b):
        return True
    joined_a, joined_b = ' '.join(full_a), ' '.join(full_b)
    return (min(len(joined_a), len(joined_b)) >= 8
            and difflib.SequenceMatcher(None, joined_a, joined_b).ratio() >= FUZZY_RATIO)


def merge_similar_groups(groups):
    """Join groups that look like the same song so all their files are compared together.
    Each merged item keeps its own artist/title; `name_differs` marks the ones whose name is
    not the group's most common name."""
    parent = list(range(len(groups)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_token = {}
    for index, members in enumerate(groups):
        artist, title = _group_identity(members)
        for token in {t for t in _tokens(f'{artist} {title}') if len(t) >= 3}:
            by_token.setdefault(token, []).append(index)
    checked = set()
    for indexes in by_token.values():
        for pos, i in enumerate(indexes):
            for j in indexes[pos + 1:]:
                if (i, j) in checked or find(i) == find(j):
                    continue
                checked.add((i, j))
                if _same_song(groups[i], groups[j]):
                    parent[find(j)] = find(i)
    merged = {}
    for index, members in enumerate(groups):
        merged.setdefault(find(index), []).extend(members)
    return list(merged.values())


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
        reason = not_mp3_reason(item)
        item['invalid'] = bool(reason)
        warnings = [reason] if reason else []
        if item['status'] != 'OK':
            warnings.append('Could not be measured')
        if item['corrupt_frames']:
            warnings.append(f"{item['corrupt_frames']} decode error(s)")
        gap = item['hf_gap_19k_db']
        item['likely_transcode'] = gap is not None and gap > TRANSCODE_GAP_DB and item['codec'] not in LOSSLESS
        if item['likely_transcode']:
            warnings.append(f'Likely transcode: almost nothing above 19.5 kHz (HF gap {gap:.0f} dB, limit {TRANSCODE_GAP_DB})')
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
    valid = [i for i in ranked if not i['invalid']]
    return valid[0]['path'] if valid else None


def rank_key(best_gap):
    def key(item):
        gap = item['hf_gap_19k_db']
        return (
            bool(item.get('invalid')),
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
        names = {(i['artist'], i['title']) for i in members}
        in_library = [t for a, t_ in names for t in library.get((normalize(a), normalize(t_)), [])]
        in_library += library.get((normalize(artist), normalize(title)), [])
        similar = False
        if not in_library:   # no exact match: a library song with a slightly different spelling
            key = (normalize(artist), normalize(title))
            in_library = [t for other, tracks in library.items() if is_similar(key, other) for t in tracks]
            similar = bool(in_library)
        for i in members:
            i['name_differs'] = (normalize(i['artist']), normalize(i['title'])) != (normalize(artist), normalize(title))
            i['listed_as'] = f"{i['artist']} - {i['title']}" if i['artist'] else i['title']
        songs.append({
            'id': song_key(artist, title),
            'artist': artist, 'title': title,
            'song': f'{artist} - {title}' if artist else title,
            'suggested': suggested,
            'in_library': sorted({t['path'] for t in in_library}),
            'in_library_similar': similar,
            'grouped_by_name': any(i['name_differs'] for i in members),
            'versions': members,
        })
    songs.sort(key=lambda s: normalize(s['song']))
    return songs


# --- Comparison with the library copy ----------------------------------------------------

QUALITY_STEPS = (
    ('likely_transcode', 'Likely transcode', 'Library copy looks like a transcode'),
    ('broken', 'Has decode errors', 'Library copy has decode errors'),
    ('lossy', 'Lossy, library copy is lossless', 'Lossless, library copy is lossy'),
    ('bitrate', None, None),
    ('hf_detail', 'Less high-frequency detail than the library copy',
     'More high-frequency detail than the library copy'),
)


def _quality_key(item, best_gap):
    """The quality part of rank_key: what makes a file sound better, not tags or names."""
    full = rank_key(best_gap)(item)
    return {'likely_transcode': full[1], 'broken': full[2], 'lossy': full[4],
            'bitrate': full[5], 'hf_detail': full[6]}


LOUDNESS_GAP_LU = 4.0       # from here on, a level difference is shown next to the verdict
MIN_USABLE_KBPS = 160       # a louder MP3 at or above this is not called worse for a lower bitrate


def _loudness_diff(version, ref):
    """How much louder the download is than the library copy, in LU (None when unmeasured)."""
    a, b = version.get('integrated_lufs'), ref.get('integrated_lufs')
    return None if a is None or b is None else round(a - b, 1)


def _verdict(version, ref, keys):
    if version['sha256'] and version['sha256'] == ref['sha256']:
        return 'same', 'Identical file to the library copy'
    if version.get('audio_md5') and version.get('audio_md5') == ref.get('audio_md5'):
        return 'same', 'Same audio as the library copy, other tags'
    mine, theirs = keys[version['path']], keys[ref['path']]
    for field, worse, better in QUALITY_STEPS:
        if mine[field] == theirs[field]:
            continue
        if field == 'bitrate':
            text = f"{version['bitrate_kbps'] or '?'} kbps vs {ref['bitrate_kbps'] or '?'} kbps in the library"
            diff = _loudness_diff(version, ref)
            if (mine[field] > theirs[field] and diff is not None and diff >= LOUDNESS_GAP_LU
                    and (version['bitrate_kbps'] or 0) >= MIN_USABLE_KBPS):
                return 'similar', f'{text}, but {diff:.1f} LU louder, so it plays at a usable level without gain changes'
            return ('better' if mine[field] < theirs[field] else 'worse'), text
        return ('better', better) if mine[field] < theirs[field] else ('worse', worse)
    return 'similar', 'Same quality level as the library copy'


def compare_with_library(versions, library_items):
    """Compare each download with the best library copy of the same song.
    Library items get warnings like downloads; each version gets `vs_library`.
    Inputs are measured items (the shape annotate_group expects); downloads keep their own ranking."""
    if not library_items:
        return []
    pool = [dict(i) for i in versions + library_items]
    annotate_group(pool)
    pooled = {i['path']: i for i in pool}
    gaps = [i['hf_gap_19k_db'] for i in pool if i['hf_gap_19k_db'] is not None]
    best_gap = min(gaps) if gaps else None
    keys = {path: _quality_key(i, best_gap) for path, i in pooled.items()}
    for item in library_items:
        # The MP3-only rule is for downloads; library copies are not judged by it.
        own = pooled[item['path']]
        item['warnings'] = [w for w in own['warnings']
                            if not w.startswith('Different length') and w != not_mp3_reason(own)]
        item['likely_transcode'] = pooled[item['path']]['likely_transcode']
    ranked = sorted(library_items, key=lambda i: (tuple(keys[i['path']].values()), i['path']))
    ref = ranked[0]
    for version in versions:
        verdict, reason = _verdict(version, ref, keys)
        length_differs = bool(version['duration_seconds'] and ref['duration_seconds'] and
                              abs(version['duration_seconds'] - ref['duration_seconds']) > EDIT_GAP_SECONDS)
        version['vs_library'] = {'verdict': verdict, 'reason': reason, 'library_path': ref['path'],
                                 'length_differs': length_differs, 'loudness_diff': _loudness_diff(version, ref)}
    return ranked


def add_library_comparison(songs, measured):
    """`measured` maps a library-relative path (as in `in_library`) to its measured item. Adds `library_versions` to each song
    and `vs_library` to its versions (left out when no library copy could be measured)."""
    for song in songs:
        library_items = [measured[p] for p in song['in_library'] if p in measured]
        song['library_versions'] = compare_with_library(song['versions'], library_items)
    return songs
