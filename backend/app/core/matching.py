"""Match Spotify tracks against local files (ported from check_playlists.py).

Statuses: 'have' (in the library), 'maybe' (check: other version, similar title or
same title by another artist), 'missing'.
"""
import difflib
import re
import unicodedata
from pathlib import Path

from .tags import read_tags

# Suffixes that describe the same recording for DJ purposes.
NEUTRAL_VERSION = re.compile(
    r"\b(remaster(ed)?|\d{4}|radio|edit|original|mix|version|single|album|mono|stereo|explicit|clean|"
    r"feat|ft|featuring|with|bonus|track|deluxe|edition|from|soundtrack|live)\b")
# Words that mean a different recording.
DISTINCT_VERSION = re.compile(r"\b(remix|rework|re-?edit|dub|bootleg|vip|flip|instrumental|acapella|cover|rmx)\b")
ARTIST_STOPWORDS = {"the", "and", "los", "las", "la", "el", "le", "les", "de", "del", "dj", "mc", "der", "die", "das"}


def normalize(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("&", " and ").replace("$", "s")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_filename(stem):
    """Guess artist/title from names like '01 - Artist - Title' or 'Artist - Title'."""
    stem = re.sub(r"^\s*\d{1,3}\s*[-.\s_]\s*", "", stem)
    parts = [p.strip() for p in re.split(r"\s+-\s+", stem) if p.strip()]
    if len(parts) >= 2:
        return {"artist": parts[0], "title": parts[-1]}
    return {"title": stem.strip()}


def local_entry(path, relative_path, artist=None, title=None):
    """A local file in the shape the matcher expects. Tags are read when not given."""
    if artist is None or title is None:
        tags = read_tags(path) if Path(path).suffix.lower() == ".mp3" else {}
    else:
        tags = {"artist": artist, "title": title}
    from_name = parse_filename(Path(path).stem)
    return {
        "path": str(path), "relative_path": relative_path,
        "title": tags.get("title") or from_name.get("title", ""),
        "artist": tags.get("artist") or from_name.get("artist", ""),
        "filename_title": from_name.get("title", ""),
        "filename_artist": from_name.get("artist", ""),
    }


def split_title(title):
    """Return (core title, version descriptor) for 'Song (X Remix)' or 'Song - Radio Edit'."""
    title = title or ""
    versions = re.findall(r"[(\[]([^)\]]*)[)\]]", title)
    core = re.sub(r"[(\[][^)\]]*[)\]]", " ", title)
    parts = re.split(r"\s+-\s+", core)
    core = parts[0]
    versions += parts[1:]
    descriptor = " ".join(normalize(v) for v in versions)
    return normalize(core), descriptor


def distinct_version(descriptor):
    """The version words that make a recording different (empty for plain edits/remasters)."""
    if not DISTINCT_VERSION.search(descriptor):
        return ""
    return re.sub(r"\s+", " ", NEUTRAL_VERSION.sub(" ", descriptor)).strip()


def artist_tokens(text):
    text = normalize(re.sub(r"\b(feat|ft|featuring|vs|x|and|with)\b\.?", ",", text or "", flags=re.I))
    return {w for w in text.split() if (len(w) > 1 or w.isdigit()) and w not in ARTIST_STOPWORDS}


def build_index(library):
    index = {}
    for track in library:
        keys = set()
        for title in (track["title"], track["filename_title"]):
            core, descriptor = split_title(title)
            if core:
                keys.add(core)
                track.setdefault("_versions", set()).add(distinct_version(descriptor))
        track["_cores"] = keys
        track["_artists"] = artist_tokens(track["artist"]) | artist_tokens(track["filename_artist"])
        track["_haystack"] = normalize(track["relative_path"])
        for key in keys:
            index.setdefault(key, []).append(track)
    return index


def match_track(spotify_track, library, index):
    core, descriptor = split_title(spotify_track["title"])
    version = distinct_version(descriptor)
    wanted_artists = artist_tokens(", ".join(spotify_track["artists"]))

    def artists_agree(local):
        if not local["_artists"]:
            # No artist info locally: accept if an artist name appears anywhere in the path.
            return any(normalize(a) in local["_haystack"] for a in spotify_track["artists"])
        return bool(wanted_artists & local["_artists"])

    best, best_score, best_note = None, 0.0, ""
    for local in index.get(core, []):
        same_version = version in local["_versions"]
        score = 1.0 if artists_agree(local) else 0.75
        if not same_version:
            score -= 0.2
        if score > best_score:
            best, best_score = local, score
            best_note = "" if same_version else "Different version or remix"
            if score < 1.0 and same_version:
                best_note = "Same title, different artist"
            elif score < 0.8:
                best_note = "Same title, different artist and version"

    if best_score < 1.0 and core and len(core) >= 3:
        for local in library:
            for local_core in local["_cores"]:
                if local_core == core:
                    continue
                if not artists_agree(local):
                    continue
                ratio = difflib.SequenceMatcher(None, core, local_core).ratio()
                contained = min(len(core), len(local_core)) >= 8 and (core in local_core or local_core in core)
                score = max(ratio, 0.86 if contained else 0) - 0.05
                if score > best_score and score >= 0.8:
                    best, best_score, best_note = local, score, "Similar title"

    if best is None:
        status = "missing"
    elif best_score >= 1.0:
        status = "have"
    else:
        status = "maybe"
    return {
        "status": status,
        "match": None if best is None else {
            "path": best["path"],
            "relative_path": best["relative_path"],
            "title": best["title"],
            "artist": best["artist"],
            "note": best_note,
        },
    }
