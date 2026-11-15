"""Find new songs for a genre folder (pure logic: no database, no web).

Pipeline: seeds (artists already in the folder, weighted by track count) ->
similar artists from a source -> score by how many seeds agree -> top tracks of the
best artists -> drop what is already owned. Every candidate keeps its reasons, so the
result can be checked and never depends on an AI inventing tracks.
"""
import math
import re
from collections import Counter

from . import matching

AGREEMENT_BONUS = 0.25  # extra score share for each additional seed that points to the same artist
COLLAB = re.compile(r"\s+(?:&|and|x|vs\.?|feat\.?|ft\.?|featuring|with)\s+|\s*[,;/]\s*", re.I)


def seed_weights(artists):
    """{artist: track count} from the artist tag of every song in the folder."""
    return dict(Counter(a.strip() for a in artists if a and a.strip()))


def split_artists(tag):
    """The individual artists in a collaboration tag: 'A & B feat. C' -> ['A', 'B', 'C']."""
    return [p.strip() for p in COLLAB.split(tag or "") if p.strip()]


def artist_keys(name):
    """Normalized spellings of one artist, including its acronym ('Deutsch Amerikanische
    Freundschaft' and 'D.A.F.' share the key 'daf'), for telling that two names are one artist."""
    words = matching.normalize(name).split()
    keys = set()
    if words:
        keys.add(" ".join(words))
        if all(len(w) == 1 for w in words):
            keys.add("".join(words))
        elif len(words) >= 3:
            keys.add("".join(w[0] for w in words))
    return keys


def owned_artist_counts(library):
    """{artist key: number of library tracks} over every artist named in a track's tags."""
    counts = Counter()
    for track in library:
        keys = set()
        for tag in (track["artist"], track["filename_artist"]):
            for part in [tag] + split_artists(tag):
                keys |= artist_keys(part)
        counts.update(keys)
    return counts


def score_artists(seeds, similar, include_seeds=False):
    """Rank artists similar to the seeds.

    seeds: {artist: weight}; similar: {seed: [(artist, match 0..1)]}.
    Returns [{"artist", "score", "because": [seed, ...]}], best first. Each seed counts
    sqrt(weight) * match, so a folder with 17 tracks by one artist does not drown out the
    rest, and the total grows by AGREEMENT_BONUS for every extra seed that agrees: an artist
    reached from several seeds beats one reached from a single heavy seed.
    """
    known = {matching.normalize(s) for s in seeds}
    found = {}
    for seed, rows in similar.items():
        weight = seeds.get(seed, 1)
        for name, match in rows:
            if not include_seeds and matching.normalize(name) in known:
                continue
            entry = found.setdefault(name, {"artist": name, "score": 0.0, "because": []})
            entry["score"] += math.sqrt(weight) * match
            entry["because"].append(seed)
    for entry in found.values():
        entry["score"] *= 1 + AGREEMENT_BONUS * (len(entry["because"]) - 1)
    return sorted(found.values(), key=lambda e: (-e["score"], -len(e["because"]), e["artist"]))


def _same_song_other_spelling(result, artist):
    """True when the matcher found the same title by an artist that is the same one under
    another spelling ('D.A.F.' vs 'Deutsch Amerikanische Freundschaft')."""
    match = result["match"]
    if result["status"] != "maybe" or not match or not match["note"].startswith("Same title, different artist"):
        return False
    wanted = artist_keys(artist)
    return any(wanted & artist_keys(part) for part in [match["artist"]] + split_artists(match["artist"]))


def candidate_tracks(artists, top_tracks, library, dismissed=()):
    """Turn ranked artists into tracks that are not owned and not dismissed.

    top_tracks: {artist: [title]}; library: entries from matching.local_entry;
    dismissed: {(artist, title)} normalized with matching.normalize.
    `you_own` is how many tracks by that artist (under any spelling) are already in the library.
    A track counts as owned when the matcher says 'have'; 'maybe' is kept and flagged.
    """
    index = matching.build_index(library)
    owned = owned_artist_counts(library)
    out = []
    for entry in artists:
        you_own = max((owned.get(k, 0) for k in artist_keys(entry["artist"])), default=0)
        for title in top_tracks.get(entry["artist"], []):
            key = (matching.normalize(entry["artist"]), matching.normalize(title))
            if key in dismissed:
                continue
            result = matching.match_track({"title": title, "artists": [entry["artist"]]}, index)
            if result["status"] == "have" or _same_song_other_spelling(result, entry["artist"]):
                continue
            out.append({
                "artist": entry["artist"], "title": title, "score": round(entry["score"], 3),
                "because": entry["because"], "you_own": you_own, "check": result["match"] if result["status"] == "maybe" else None,
            })
    return out
