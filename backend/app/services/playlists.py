"""Spotify playlists vs the library, and which waiting downloads fill the gaps."""
import urllib.error

from sqlalchemy import delete, select

from ..core import matching, spotify
from ..db import session_scope
from ..jobs import handler
from ..models import File, Mark, Match, Playlist, PlaylistTrack, Review, now


def add_playlist(session, value, project=""):
    playlist_id = spotify.parse_playlist_id(value)
    row = session.get(Playlist, playlist_id)
    if row is None:
        position = len(session.scalars(select(Playlist)).all())
        row = Playlist(id=playlist_id, name=playlist_id, project=project, position=position)
        session.add(row)
    row.tracked = True
    if project:
        row.project = project
    session.flush()
    return row


@handler("spotify_refresh")
def run_refresh(ctx):
    """params: {"ids": [...]} (default: every tracked playlist). Then matches again."""
    with session_scope() as s:
        ids = ctx.params.get("ids") or [p.id for p in s.scalars(
            select(Playlist).where(Playlist.tracked.is_(True)).order_by(Playlist.position)).all()]
        names = {p.id: p.name for p in s.scalars(select(Playlist)).all() if p.name}
    if not ids:
        raise ValueError("No playlists configured. Add one in Settings.")
    try:
        token = spotify.spotify_token(interactive=False)
    except (spotify.SpotifyLoginError, urllib.error.URLError, OSError, ValueError, KeyError) as error:
        ctx.log(f"Spotify login unavailable ({error}); using the embed pages (first 100 tracks)")
        token = None
    ctx.log("Using Spotify Web API" if token else "Using Spotify embed pages (first 100 tracks per playlist)")
    failed = []
    for i, playlist_id in enumerate(ids, 1):
        ctx.check()
        ctx.progress(i - 1, len(ids), f"Reading {names.get(playlist_id, playlist_id)}")
        try:
            data = spotify.fetch_playlist(playlist_id, token)
        except (urllib.error.URLError, RuntimeError, KeyError, ValueError) as error:
            ctx.log(f"{playlist_id}: failed ({error})")
            failed.append(playlist_id)
            continue
        with session_scope() as s:
            row = s.get(Playlist, playlist_id)
            if row is None:
                row = Playlist(id=playlist_id, position=i)
                s.add(row)
            row.name, row.owner, row.cover = data["name"], data["owner"], data["cover"]
            row.source, row.possibly_truncated, row.refreshed_at = data["source"], data["possibly_truncated"], now()
            s.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
            for position, track in enumerate(data["tracks"]):
                s.add(PlaylistTrack(playlist_id=playlist_id, position=position, spotify_id=track["spotify_id"],
                                    title=track["title"], artists=track["artists"],
                                    duration_ms=track.get("duration_ms")))
        ctx.log(f"{data['name']}: {len(data['tracks'])} tracks ({data['source']})")
    ctx.progress(len(ids), len(ids), "Matching against the library")
    with session_scope() as s:
        counts = match_all(s)
    message = f"{counts['have']} in library, {counts['maybe']} to check, {counts['missing']} missing"
    if failed:
        message += f"; {len(failed)} playlist(s) failed"
    return {"message": message, **counts, "failed": failed}


@handler("match_playlists")
def run_match(ctx):
    with session_scope() as s:
        counts = match_all(s)
    return {"message": f"{counts['have']} in library, {counts['maybe']} to check, {counts['missing']} missing",
            **counts}


def _library_entries(session):
    rows = session.scalars(select(File).where(File.area == "library", File.present.is_(True),
                                              File.kind != "rejected")).all()
    return [matching.local_entry(r.path, r.rel_path, artist=r.artist, title=r.title) for r in rows]


def _download_entries(session):
    review = session.scalar(select(Review).order_by(Review.id.desc()).limit(1))
    entries = []
    for song in (review.payload["songs"] if review else []):
        for version in song["versions"]:
            entry = matching.local_entry(version["path"], version["name"],
                                         artist=song["artist"], title=version.get("tag_title") or song["title"])
            entry["song_key"] = song["id"]
            entries.append(entry)
    return entries


def _unique_tracks(session):
    tracks = {}
    for t in session.scalars(select(PlaylistTrack)).all():
        tracks.setdefault(t.spotify_id, {"spotify_id": t.spotify_id, "title": t.title, "artists": t.artists})
    return tracks


def match_all(session):
    """Match every playlist track against the library, then the gaps against the downloads."""
    library = _library_entries(session)
    index = matching.build_index(library)
    tracks = _unique_tracks(session)
    old = {m.spotify_id: m for m in session.scalars(select(Match)).all()}
    counts = {"have": 0, "maybe": 0, "missing": 0}
    stamp = now()
    for spotify_id, track in tracks.items():
        result = matching.match_track(track, library, index)
        row = old.pop(spotify_id, None) or Match(spotify_id=spotify_id)
        session.add(row)
        match = result["match"] or {}
        row.status, row.path, row.relative_path = result["status"], match.get("path"), match.get("relative_path")
        row.matched_title, row.matched_artist, row.note = match.get("title", ""), match.get("artist", ""), \
            match.get("note", "")
        row.computed_at = stamp
        counts[result["status"]] += 1
    for row in old.values():
        session.delete(row)
    session.flush()
    link_downloads(session, tracks)
    return counts


def link_downloads(session, tracks=None):
    """For tracks not in the library, find a waiting download of the same song."""
    tracks = tracks or _unique_tracks(session)
    entries = _download_entries(session)
    index = matching.build_index(entries)
    for row in session.scalars(select(Match)).all():
        row.download_song_key, row.download_status = None, ""
        if row.status == "have" or not entries or row.spotify_id not in tracks:
            continue
        result = matching.match_track(tracks[row.spotify_id], entries, index)
        if result["status"] != "missing":
            entry = next(e for e in entries if e["path"] == result["match"]["path"])
            row.download_song_key, row.download_status = entry["song_key"], result["status"]
    session.flush()


def wanted_by_song(session):
    """song_key -> [{"spotify_id", "title", "artists", "playlists", "status"}] for the review page."""
    names = {p.id: p.name for p in session.scalars(select(Playlist)).all()}
    in_playlists = {}
    meta = {}
    for t in session.scalars(select(PlaylistTrack)).all():
        in_playlists.setdefault(t.spotify_id, set()).add(names.get(t.playlist_id, t.playlist_id))
        meta.setdefault(t.spotify_id, t)
    out = {}
    for m in session.scalars(select(Match).where(Match.download_song_key.is_not(None))).all():
        t = meta.get(m.spotify_id)
        if t is None:
            continue
        out.setdefault(m.download_song_key, []).append({
            "spotify_id": m.spotify_id, "title": t.title, "artists": t.artists,
            "playlists": sorted(in_playlists.get(m.spotify_id, ())), "status": m.download_status})
    return out


def overview(session):
    """Playlists with counts per status, for tabs and summary cards."""
    playlists = session.scalars(select(Playlist).order_by(Playlist.position)).all()
    matches = {m.spotify_id: m for m in session.scalars(select(Match)).all()}
    marks = {m.spotify_id for m in session.scalars(select(Mark)).all()}
    out = []
    for p in playlists:
        tracks = session.scalars(select(PlaylistTrack).where(PlaylistTrack.playlist_id == p.id)).all()
        counts = {"have": 0, "maybe": 0, "missing": 0, "downloaded": 0, "waiting": 0, "total": len(tracks)}
        for t in tracks:
            m = matches.get(t.spotify_id)
            status = m.status if m else "missing"
            counts[status] += 1
            if status != "have" and t.spotify_id in marks:
                counts["downloaded"] += 1
            if status != "have" and m and m.download_song_key:
                counts["waiting"] += 1
        out.append({"id": p.id, "name": p.name, "owner": p.owner, "cover": p.cover, "source": p.source,
                    "possibly_truncated": p.possibly_truncated, "project": p.project, "tracked": p.tracked,
                    "refreshed_at": p.refreshed_at, "counts": counts})
    return out


def tracks(session, playlist_id=None):
    """Tracks of one playlist, or of all playlists with duplicates merged."""
    playlists = {p.id: p for p in session.scalars(select(Playlist)).all()}
    query = select(PlaylistTrack).order_by(PlaylistTrack.playlist_id, PlaylistTrack.position)
    rows = session.scalars(query).all()
    matches = {m.spotify_id: m for m in session.scalars(select(Match)).all()}
    marks = {m.spotify_id for m in session.scalars(select(Mark)).all()}
    in_lists = {}
    for t in rows:
        in_lists.setdefault(t.spotify_id, []).append(t.playlist_id)
    out, seen = [], set()
    if playlist_id:
        rows = [t for t in rows if t.playlist_id == playlist_id]
    for t in rows:
        if t.spotify_id in seen:
            continue
        seen.add(t.spotify_id)
        m = matches.get(t.spotify_id)
        lists = sorted(set(in_lists[t.spotify_id]), key=lambda i: playlists[i].position if i in playlists else 0)
        out.append({
            "spotify_id": t.spotify_id, "title": t.title, "artists": t.artists, "duration_ms": t.duration_ms,
            "position": t.position, "status": m.status if m else "missing",
            "match": None if not m or not m.path else {
                "path": m.path, "relative_path": m.relative_path, "title": m.matched_title,
                "artist": m.matched_artist, "note": m.note},
            "download": None if not m or not m.download_song_key else {
                "song_key": m.download_song_key, "status": m.download_status},
            "downloaded": t.spotify_id in marks,
            "playlists": [playlists[i].name if i in playlists else i for i in lists],
            "projects": sorted({playlists[i].project for i in lists if i in playlists and playlists[i].project}),
        })
    return out


def set_mark(session, spotify_id, downloaded):
    row = session.get(Mark, spotify_id)
    if downloaded and row is None:
        session.add(Mark(spotify_id=spotify_id))
    elif not downloaded and row is not None:
        session.delete(row)


def playlists_for_path(session, path):
    """Playlists whose tracks matched this library file."""
    names = {p.id: p.name for p in session.scalars(select(Playlist)).all()}
    out = []
    for m in session.scalars(select(Match).where(Match.path == path)).all():
        for t in session.scalars(select(PlaylistTrack).where(PlaylistTrack.spotify_id == m.spotify_id)).all():
            out.append({"playlist": names.get(t.playlist_id, t.playlist_id), "title": t.title,
                        "artists": t.artists, "status": m.status})
    return out
