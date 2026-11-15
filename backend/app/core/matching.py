"""Match Spotify tracks against local files.

Statuses: 'have' (in the library), 'maybe' (check: other version, similar title or
same title by another artist), 'missing'.
"""
import difflib
import re
import unicodedata
from pathlib import Path

from .names import guess_from_filename
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


def local_entry(path, relative_path, artist=None, title=None):
    """A local file in the shape the matcher expects. Tags are read when not given."""
    if artist is None or title is None:
        tags = read_tags(path) if Path(path).suffix.lower() == ".mp3" else {}
    else:
        tags = {"artist": artist, "title": title}
    from_name = guess_from_filename(Path(path).stem)
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


class Index(dict):
    """Title core -> local tracks, plus which tracks share an artist word (to skip most of the library
    when looking for similar titles)."""

    def __init__(self):
        super().__init__()
        self.by_artist = {}
        self.no_artist = []


def build_index(library):
    index = Index()
    for position, track in enumerate(library):
        track["_pos"] = position
        keys = set()
        for title in (track["title"], track["filename_title"]):
            core, descriptor = split_title(title)
            if core:
                keys.add(core)
                track.setdefault("_versions", set()).add(distinct_version(descriptor))
        track["_cores"] = keys
        track["_artists"] = artist_tokens(track["artist"]) | artist_tokens(track["filename_artist"])
        track["_haystack"] = normalize(track["relative_path"])
        for word in track["_artists"]:
            index.by_artist.setdefault(word, []).append(track)
        if not track["_artists"]:
            index.no_artist.append(track)
        for key in keys:
            index.setdefault(key, []).append(track)
    return index


def _similar_candidates(wanted_artists, index):
    """Local tracks that could pass `artists_agree`, in library order: those sharing an artist word, and
    those with no artist info (checked against the path)."""
    found = {id(t): t for word in wanted_artists for t in index.by_artist.get(word, [])}
    found.update({id(t): t for t in index.no_artist})
    return sorted(found.values(), key=lambda t: t["_pos"])


def match_track(spotify_track, index):
    core, descriptor = split_title(spotify_track["title"])
    version = distinct_version(descriptor)
    each_artist = [artist_tokens(a) for a in spotify_track["artists"]]
    wanted_artists = set().union(*each_artist) if each_artist else set()

    def artists_agree(local):
        if not local["_artists"]:
            # No artist info locally: accept if an artist name appears anywhere in the path.
            return any(normalize(a) in local["_haystack"] for a in spotify_track["artists"])
        # A whole artist name must be there ("Pet Shop Boys" is not "Beastie Boys"), or the local artist
        # must be made of the playlist's artists ("Soft Cell & Marc Almond" for a track by both).
        return any(tokens and tokens <= local["_artists"] for tokens in each_artist) \
            or local["_artists"] <= wanted_artists

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
        for local in _similar_candidates(wanted_artists, index):
            for local_core in local["_cores"]:
                if local_core == core:
                    continue
                if not artists_agree(local):
                    continue
                contained = min(len(core), len(local_core)) >= 8 and (core in local_core or local_core in core)
                matcher = difflib.SequenceMatcher(None, core, local_core)
                if not contained and matcher.quick_ratio() < 0.85:   # an upper bound: it cannot reach 0.8 after the penalty
                    continue
                ratio = matcher.ratio()
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
