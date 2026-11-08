"""Downloads review: measure new downloads, pick the best version, move picks to Inbox/Rejected."""
import concurrent.futures
import datetime as dt
import time
from pathlib import Path

from sqlalchemy import select

from ..config import get_config
from ..core import audio
from ..core import downloads as dl
from ..db import session_scope
from ..jobs import handler
from ..models import Decision, File, Review, now
from . import analysis, library, playlists, settings


@handler("review_downloads")
def run_review(ctx):
    """Read-only: files in the download folders are measured, never moved."""
    missing = audio.missing_tools()
    if missing:
        raise RuntimeError(f"Missing executable: {', '.join(missing)}")
    cfg = get_config()
    with session_scope() as s:
        sources = [Path(p).resolve() for p in settings.sources(s)]
    files, skipped = dl.find_files(sources, time.time(), cfg.settle_seconds)
    versions = audio.tool_versions()
    items, todo = [], []
    with session_scope() as s:
        for source, path in files:
            stat = path.stat()
            item = {"path": str(path.resolve()), "name": path.name, "source": str(source),
                    "size": stat.st_size, "mtime_ns": str(stat.st_mtime_ns)}
            item["sha256"] = analysis.cached_sha(s, path, stat)
            items.append(item)
    ctx.progress(0, len(items), f"{len(items)} download(s) found")
    for i, item in enumerate(items, 1):
        ctx.check()
        if not item["sha256"]:
            item["sha256"] = audio.sha256_file(item["path"])
        with session_scope() as s:
            old = analysis.reusable(s, item["sha256"], True, versions["ffmpeg_version"])
            if old is None:
                old = analysis.reusable(s, item["sha256"], True, None)
            if old:
                item.update(_quality(analysis.measurement_row(old)))
            else:
                todo.append(item)
    measured = 0
    if todo:
        ctx.progress(0, len(todo), f"Measuring {len(todo)} new file(s)")
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.workers) as pool:
            futures = {pool.submit(audio.analyze, Path(item["path"])): item for item in todo}
            for future in concurrent.futures.as_completed(futures):
                if ctx.cancelled():
                    for f in futures:
                        f.cancel()
                    ctx.check()
                item = futures[future]
                result = future.result()
                item.update(_quality(result))
                measured += 1
                stat = Path(item["path"]).stat()
                with session_scope() as s:
                    s.add(analysis.new_measurement(item["path"], result, item["sha256"], stat, ctx.job_id, True,
                                                   versions=versions))
                ctx.progress(measured, len(todo), item["name"])
    with session_scope() as s:
        seen = set()
        for item in items:
            row = library.register_file(s, item["path"], "download")
            row.area, row.present, row.last_seen = "download", True, now()
            row.size, row.mtime_ns, row.sha256 = item["size"], item["mtime_ns"], item["sha256"]
            row.artist, row.title = item.get("tag_artist") or "", item.get("tag_title") or ""
            item["file_id"] = row.id
            seen.add(item["path"])
        for row in s.scalars(select(File).where(File.area == "download", File.present.is_(True))).all():
            if row.path not in seen:
                row.present = False
        tracks = library.scan(s)
        median, median_run = analysis.library_median(s)
    songs = dl.build_songs(items, dl.library_index(tracks))
    payload = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources": [str(p) for p in sources], "library_median": median, "median_run": median_run,
        "skipped_recent": [str(p) for p in skipped], "settle_seconds": cfg.settle_seconds, "songs": songs,
    }
    with session_scope() as s:
        s.add(Review(job_id=ctx.job_id, payload=payload))
    with session_scope() as s:
        playlists.link_downloads(s)
    multi = sum(len(song["versions"]) > 1 for song in songs)
    return {"message": f"{len(items)} file(s), {len(songs)} song(s), {multi} with more than one version; "
                       f"{measured} measured now", "files": len(items), "songs": len(songs),
            "measured": measured, "skipped_recent": len(skipped)}


def _quality(row):
    keys = analysis.MEASURE_FIELDS + analysis.QUALITY_FIELDS
    out = {k: row.get(k) for k in keys}
    out["corrupt_frames"] = out.get("corrupt_frames") or 0
    for key in ("tag_artist", "tag_title", "album", "year"):
        out[key] = out.get(key) or ""
    out["has_art"] = bool(out.get("has_art"))
    return out


def latest_review(session):
    return session.scalar(select(Review).order_by(Review.id.desc()).limit(1))


def review_view(session):
    """Latest review with your decisions and the playlists that want each song.
    Songs whose decision was applied are left out (their files have moved)."""
    review = latest_review(session)
    if review is None:
        return None
    payload = dict(review.payload)
    decisions = {d.song_key: d for d in session.scalars(select(Decision)).all()}
    wanted = playlists.wanted_by_song(session)
    songs = []
    for song in payload["songs"]:
        decision = decisions.get(song["id"])
        if decision and decision.applied_batch_id:
            continue
        paths = {v["path"] for v in song["versions"]}
        if decision and decision.choice == "keep" and decision.keep_path not in paths:
            decision = None
        present = [v for v in song["versions"] if Path(v["path"]).is_file()]
        songs.append({**song, "gone": len(present) < len(song["versions"]),
                      "decision": None if decision is None else {
                          "choice": decision.choice, "keep_path": decision.keep_path,
                          "decided_at": decision.decided_at},
                      "wanted_by": wanted.get(song["id"], [])})
    payload["songs"] = songs
    payload["review_id"] = review.id
    payload["created_at"] = review.created_at
    return payload


def decide(session, song_key, choice, keep_path=None):
    """Record your choice for a song: keep (one version), reject (all), later, or clear."""
    review = latest_review(session)
    song = next((s for s in (review.payload["songs"] if review else []) if s["id"] == song_key), None)
    if song is None:
        raise ValueError("Song not in the latest review")
    row = session.get(Decision, song_key)
    if choice == "clear":
        if row and not row.applied_batch_id:
            session.delete(row)
        return None
    if choice not in ("keep", "reject", "later"):
        raise ValueError(f"Unknown choice {choice!r}")
    if choice == "keep" and keep_path not in {v["path"] for v in song["versions"]}:
        raise ValueError("That file is not a version of this song")
    if row is None:
        row = Decision(song_key=song_key)
        session.add(row)
    row.song, row.choice, row.keep_path, row.decided_at = song["song"], choice, (
        keep_path if choice == "keep" else None), now()
    row.applied_batch_id = None
    session.flush()
    return row


def picks(session, song_keys=None):
    """Picks for the intake plan from your pending decisions (keep or reject)."""
    review = latest_review(session)
    if review is None:
        return [], {}
    decisions = {d.song_key: d for d in session.scalars(select(Decision).where(
        Decision.applied_batch_id.is_(None), Decision.choice.in_(("keep", "reject")))).all()}
    out, songs = [], {}
    for song in review.payload["songs"]:
        decision = decisions.get(song["id"])
        if decision is None or (song_keys and song["id"] not in song_keys):
            continue
        paths = [v["path"] for v in song["versions"]]
        keep = decision.keep_path if decision.choice == "keep" else None
        if keep and keep not in paths:
            continue
        out.append({"song": song["song"], "keep": keep, "reject": [p for p in paths if p != keep],
                    "signatures": {v["path"]: [v["size"], v["mtime_ns"]] for v in song["versions"]}})
        songs[song["id"]] = paths
    return out, songs


def preview_intake(session, song_keys=None):
    chosen, songs = picks(session, song_keys)
    if not chosen:
        raise library.BatchError("No decided songs to move. Pick Keep or Reject all first.")
    return library.preview(session, "intake", {"picks": chosen, "songs": songs})
