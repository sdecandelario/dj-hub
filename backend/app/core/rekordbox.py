"""Rekordbox export logs: which tracks it could not export, and where those files went.

Pure logic (no database or web code). Rekordbox only reads the files listed here; nothing in
the Rekordbox library is ever changed. `follow_trail` replays dj-hub's own file history to find
where a missing file is now.
"""
import re
from pathlib import Path

from .names import guess_from_filename, is_similar, match_key, split_version

ENTRY = re.compile(r'^\[(\d)\]\s+(.*?)\t(/.*?)\s*$')
REASONS = {
    '1': "The file doesn't exist",
    '2': "Format not supported by CDJ/XDJ/mobile devices",
    '3': "The file could not be copied",
    '4': "Track analysis data is corrupted or missing",
    '5': "Error on the USB/SD/mobile device",
}


def decode(raw):
    """Rekordbox writes UTF-16 with a byte order mark; fall back to UTF-8."""
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16', errors='replace')
    return raw.decode('utf-8', errors='replace')


def parse_log(text):
    """[{'title', 'path', 'reason'}] from one export log; the same track listed twice counts once."""
    seen, entries = set(), []
    for line in text.splitlines():
        match = ENTRY.match(line.replace('﻿', ''))
        if match and match.group(3) not in seen:
            seen.add(match.group(3))
            entries.append({'title': match.group(2).strip(), 'path': match.group(3), 'reason': match.group(1)})
    return entries


def follow_trail(ops, path):
    """Where `path` went, replaying file operations in order.
    ops: [{'id', 'source', 'dest', 'label', 'batch_id', 'batch_status'}] sorted by id.
    Returns (final path, hops); hops are the operations that touched it."""
    by_source = {}
    for op in ops:
        by_source.setdefault(op['source'], []).append(op)
    current, last, hops = path, 0, []
    while True:
        step = next((o for o in by_source.get(current, []) if o['id'] > last and o['dest'] != current), None)
        if step is None or len(hops) > 50:
            return current, hops
        hops.append(step)
        current, last = step['dest'], step['id']


def _name_pairs(entry):
    """(artist, title) readings of a missing file's name. 'A - B' is tried both ways, because
    downloads are sometimes named 'Title - Artist'. The log's track title is the last resort."""
    guess = guess_from_filename(Path(entry['path']).stem)
    artist, title = guess.get('artist', ''), guess.get('title') or entry['title']
    pairs = [(artist, title)]
    if artist:
        pairs.append((title, artist))
    pairs.append(('', entry['title']))
    return pairs


def candidates(entry, tracks, limit=5):
    """Library songs that look like the missing track, best first.
    tracks: library scan rows ({'path', 'artist', 'title', 'kind'}); rejected copies are ignored."""
    best = {}
    for artist, title in _name_pairs(entry):
        wanted_titles = {match_key('', t)[1] for t in (title, split_version(title)[0]) if t}
        wanted_artist = match_key(artist, '')[0] if artist else ''
        for track in tracks:
            if track['kind'] == 'rejected' or not track['title']:
                continue
            key = match_key(track['artist'], track['title'])
            same_title = key[1] in wanted_titles
            if not same_title and not any(is_similar(('x', key[1]), ('x', w)) for w in wanted_titles):
                continue
            if wanted_artist:
                same_artist = key[0] == wanted_artist
                if not (same_artist or is_similar((key[0], 'x'), (wanted_artist, 'x'))):
                    continue
                score = (0 if same_title else 1) + (0 if same_artist else 1)
            else:
                score = 2 + (0 if same_title else 1)
            rank = (score, 0 if track['kind'] == 'genre' else 1, track['path'])
            if track['path'] not in best or rank < best[track['path']]:
                best[track['path']] = rank
    by_path = {t['path']: t for t in tracks}
    return [by_path[rank[2]] for rank in sorted(best.values())[:limit]]
