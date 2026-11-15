"""Discovery use case: new songs for one genre folder (read-only, never touches files)."""
from sqlalchemy import select

from ..core import discovery, lastfm, matching
from ..core.library import GENRES
from ..models import Candidate, File, Playlist, PlaylistTrack, now
from .playlists import _library_entries


class UnknownGenre(ValueError):
    pass


def genre_names(session):
    rows = session.scalars(select(File.folder).where(File.area == "library", File.kind == "genre",
                                                     File.present.is_(True)).distinct()).all()
    return sorted(rows)


def seeds_for(session, genre):
    """{artist: track count} for the songs in Genres/<genre>."""
    artists = session.scalars(select(File.artist).where(
        File.area == "library", File.kind == "genre", File.folder == genre, File.present.is_(True))).all()
    weights = discovery.seed_weights(artists)
    if not weights:
        names = ", ".join(genre_names(session)) or f"none found under {GENRES}/"
        raise UnknownGenre(f"No songs in genre folder '{genre}'. Genre folders: {names}")
    return weights


COLLAB_SHARE = 0.25


def _similar_for(client, seeds):
    """Similar artists per seed. A collaboration tag Last.fm does not know ('A & B') is split:
    the first artist, usually the main one, gets the full weight and each other artist a
    quarter of it (COLLAB_SHARE), so a remixer or guest does not take over the folder."""
    similar, used = {}, {}
    for seed, weight in seeds.items():
        rows = client.similar_artists(seed)
        parts = discovery.split_artists(seed)
        if rows or len(parts) < 2:
            similar[seed], used[seed] = rows, used.get(seed, 0) + weight
            continue
        for i, part in enumerate(parts):
            if part not in similar:
                similar[part] = client.similar_artists(part)
            used[part] = used.get(part, 0) + (weight if i == 0 else weight * COLLAB_SHARE)
    return similar, used


def discover(session, genre, client=None, seed_limit=15, artist_limit=20, tracks_per_artist=2):
    """Ranked candidates for a genre folder.

    Uses the `seed_limit` heaviest artists of the folder as seeds, scores their similar
    artists, and returns the top tracks of the best `artist_limit` artists that are not
    owned anywhere in the library.
    """
    client = client or lastfm.Lastfm()
    seeds = seeds_for(session, genre)
    top_seeds = dict(sorted(seeds.items(), key=lambda kv: (-kv[1], kv[0]))[:seed_limit])
    similar, top_seeds = _similar_for(client, top_seeds)
    artists = discovery.score_artists(top_seeds, similar)[:artist_limit]
    tracks = {a["artist"]: client.top_tracks(a["artist"], limit=tracks_per_artist) for a in artists}
    candidates = discovery.candidate_tracks(artists, tracks, _library_entries(session),
                                            dismissed=dismissed_keys(session))
    return {"genre": genre, "seeds": top_seeds, "candidates": candidates}


STATUSES = ("new", "wanted", "dismissed")


def key_for(artist, title):
    return f"{matching.normalize(artist)}|{matching.normalize(title)}"


def dismissed_keys(session):
    """{(artist, title)} normalized, for every dismissed candidate."""
    rows = session.scalars(select(Candidate).where(Candidate.status == "dismissed")).all()
    return {(matching.normalize(c.artist), matching.normalize(c.title)) for c in rows}


def save(session, result):
    """Store a discover() result. New songs start as 'new'; songs already stored keep their
    status (wanted stays wanted) and only get a fresh score and reasons. Returns the rows."""
    rows = []
    for c in result["candidates"]:
        key = key_for(c["artist"], c["title"])
        row = session.scalar(select(Candidate).where(Candidate.key == key))
        if row is None:
            row = Candidate(key=key, genre=result["genre"], artist=c["artist"], title=c["title"])
            session.add(row)
        row.score, row.because, row.you_own, row.check, row.updated_at = \
            c["score"], c["because"], c["you_own"], c["check"], now()
        rows.append(row)
    session.flush()
    return rows


def set_status(session, ids, status):
    """Mark candidates wanted, dismissed or back to new. Returns the rows changed."""
    if status not in STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(STATUSES)}")
    rows = session.scalars(select(Candidate).where(Candidate.id.in_(ids))).all()
    missing = set(ids) - {r.id for r in rows}
    if missing:
        raise KeyError(f"Candidate(s) not found: {', '.join(map(str, sorted(missing)))}")
    for row in rows:
        row.status, row.updated_at = status, now()
    return rows


class _PlaylistIndex:
    """Playlist tracks by title, to tell which playlists already contain a song (no double buying)."""
    def __init__(self, session):
        names = {p.id: p for p in session.scalars(select(Playlist)).all()}
        self.by_core = {}
        for t in session.scalars(select(PlaylistTrack)).all():
            core, _ = matching.split_title(t.title)
            playlist = names.get(t.playlist_id)
            self.by_core.setdefault(core, []).append((
                matching.artist_tokens(", ".join(t.artists)),
                {"playlist": playlist.name if playlist else t.playlist_id,
                 "project": playlist.project if playlist else ""}))

    def lookup(self, artist, title):
        core, _ = matching.split_title(title)
        wanted = matching.artist_tokens(artist)
        found = []
        for tokens, info in self.by_core.get(core, []):
            if wanted & tokens and info not in found:
                found.append(info)
        return found


def _playlist_index(session):
    return _PlaylistIndex(session)


def list_candidates(session, status=None, genre=None):
    """Stored candidates, best first, each with the playlists that already have the song."""
    query = select(Candidate).order_by(Candidate.score.desc(), Candidate.id)
    if status:
        query = query.where(Candidate.status == status)
    if genre:
        query = query.where(Candidate.genre == genre)
    index = _playlist_index(session)
    return [{
        "id": c.id, "genre": c.genre, "artist": c.artist, "title": c.title, "status": c.status,
        "score": c.score, "because": c.because, "you_own": c.you_own, "check": c.check,
        "in_playlists": index.lookup(c.artist, c.title),
    } for c in session.scalars(query).all()]
