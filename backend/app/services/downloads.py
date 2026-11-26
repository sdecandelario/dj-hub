"""Downloads review: measure new downloads, pick the best version, move picks to Inbox/Rejected."""
import concurrent.futures
import datetime as dt
from pathlib import Path

from sqlalchemy import delete, select

from ..config import get_config
from ..core import audio
from ..core import downloads as dl
from ..db import session_scope
from ..jobs import handler
from ..models import Decision, File, Job, Review, now
from . import analysis, library, playlists, settings




def soulseek_busy(session):
    """Resolved paths of the files a running Soulseek download is still writing (it writes straight into the folder)."""
    jobs = session.scalars(select(Job).where(Job.type == "soulseek_download", Job.status == "running")).all()
    return {str(Path(f["local_path"]).resolve()) for job in jobs
            for song in (job.summary or {}).get("songs", {}).values() for f in song["files"]
            if not f.get("done") and f.get("local_path")}


@handler("review_downloads")
def run_review(ctx):
    """Read-only: files in the download folders are measured, never moved."""
    missing = audio.missing_tools()
    if missing:
        raise RuntimeError(f"Missing executable: {', '.join(missing)}")
    cfg = get_config()
    with session_scope() as s:
        sources = [Path(p).resolve() for p in settings.sources(s)]
    with session_scope() as s:
        busy = soulseek_busy(s)
    files, skipped = dl.find_files(sources, busy)
    versions = audio.tool_versions()
    items = []
    for source, path in files:
        stat = path.stat()
        items.append({"path": str(path.resolve()), "name": path.name, "source": str(source),
                      "size": stat.st_size, "mtime_ns": str(stat.st_mtime_ns)})
    with session_scope() as s:
        analysis.cached_shas(s, items)
    ctx.progress(0, len(items), f"{len(items)} download(s) found")
    measured = _measure(ctx, items, versions, cfg.workers)
    with session_scope() as s:
        _store_downloads(s, items)
        tracks = library.scan(s)
        median, median_run = analysis.library_median(s)
    songs = dl.build_songs(items, dl.library_index(tracks))
    library_items = _library_items(ctx, songs, tracks, versions, cfg.workers)
    dl.add_library_comparison(songs, library_items)
    payload = {
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "sources": [str(p) for p in sources], "library_median": median, "median_run": median_run,
        "skipped_busy": [str(p) for p in skipped], "songs": songs,
    }
    with session_scope() as s:
        s.add(Review(job_id=ctx.job_id, payload=payload))
        s.flush()
        s.execute(delete(Review).where(Review.job_id != ctx.job_id))   # only the latest review is ever read
    with session_scope() as s:
        playlists.link_downloads(s)
    multi = sum(len(song["versions"]) > 1 for song in songs)
    return {"message": f"{len(items)} file(s), {len(songs)} song(s), {multi} with more than one version; "
                       f"{measured} measured now", "files": len(items), "songs": len(songs),
            "measured": measured, "skipped_busy": len(skipped)}


def _store_downloads(session, items):
    """Record the download files in the files table (and mark the ones no longer there as gone)."""
    seen = set()
    for item in items:
        row = library.register_file(session, item["path"], "download")
        row.area, row.present = "download", True
        row.size, row.mtime_ns, row.sha256 = item["size"], item["mtime_ns"], item["sha256"]
        row.artist, row.title = item.get("tag_artist") or "", item.get("tag_title") or ""
        item["file_id"] = row.id
        seen.add(item["path"])
    for row in session.scalars(select(File).where(File.area == "download", File.present.is_(True))).all():
        if row.path not in seen:
            row.present = False


def _measure(ctx, items, versions, workers):
    """Fill each item with its quality measurement: reused when the same bytes were measured
    before, otherwise measured now (read-only) and stored. Returns how many were measured now."""
    for item in items:   # hashing reads the whole file, so it happens outside any database session
        ctx.check()
        if not item["sha256"]:
            item["sha256"] = audio.sha256_file(item["path"])
    with session_scope() as s:
        old = analysis.reusable_many(s, [i["sha256"] for i in items], versions["ffmpeg_version"], analysis.REVIEW_NEEDS)
        todo = []
        for item in items:
            if item["sha256"] in old:
                item.update(_quality(analysis.measurement_row(old[item["sha256"]])))
            else:
                todo.append(item)
    measured = 0
    if todo:
        ctx.progress(0, len(todo), f"Measuring {len(todo)} new file(s)")
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
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
    return measured


def _library_items(ctx, songs, tracks, versions, workers):
    """Measured library copies of the downloaded songs, keyed by their library-relative path
    (the paths in song["in_library"]). Read-only."""
    by_rel = {t["path"]: t for t in tracks}
    items = []
    with session_scope() as s:
        for rel in sorted({p for song in songs for p in song["in_library"]}):
            track = by_rel.get(rel)
            file = Path(track["abs"]) if track else None
            if file is None or not file.is_file():
                continue
            stat = file.stat()
            row = library.register_file(s, track["abs"], "library")
            items.append({"path": track["abs"], "rel_path": rel, "name": file.name, "size": stat.st_size,
                          "mtime_ns": str(stat.st_mtime_ns), "file_id": row.id,
                          "sha256": analysis.cached_sha(s, file, stat),
                          "folder": track["folder"], "kind": track["kind"]})
    if items:
        ctx.progress(0, len(items), f"Checking {len(items)} library copy(ies)")
        _measure(ctx, items, versions, workers)
        with session_scope() as s:
            for item in items:  # remember the hash so the next review skips hashing again
                row = s.get(File, item["file_id"])
                if row.size == item["size"] and row.mtime_ns == item["mtime_ns"]:
                    row.sha256 = item["sha256"]
    return {item["rel_path"]: item for item in items}


def _quality(row):
    keys = analysis.MEASURE_FIELDS + analysis.QUALITY_FIELDS
    out = {k: row.get(k) for k in keys}
    out["corrupt_frames"] = out.get("corrupt_frames") or 0
    for key in ("tag_artist", "tag_title", "album", "year"):
        out[key] = out.get(key) or ""
    out["has_art"] = bool(out.get("has_art"))
    return out


def pending(session):
    """Audio files waiting in the download folders, counted without measuring anything.
    Songs are estimated from file names; `new` counts files the latest review has not seen."""
    sources = [Path(p).resolve() for p in settings.sources(session)]
    files, _ = dl.find_files(sources, soulseek_busy(session))
    review = latest_review(session)
    reviewed = {v["path"] for song in (review.payload["songs"] if review else []) for v in song["versions"]}
    paths = [str(path.resolve()) for _, path in files]
    songs = {(dl.normalize(a), dl.normalize(t)) for a, t, _, _ in
             (dl.song_identity({"path": p}) for p in paths)}
    return {"files": len(paths), "songs": len(songs), "new": sum(p not in reviewed for p in paths),
            "reviewed_at": review.created_at if review else None}


def latest_review(session):
    return session.scalar(select(Review).order_by(Review.id.desc()).limit(1))


def review_view(session):
    """Latest review with your decisions and the playlists that want each song.
    Songs whose decision was applied are left out while their files are gone (they have moved). A file back in
    the download folder (downloaded again, or the batch was undone) is a new song to decide."""
    review = latest_review(session)
    if review is None:
        return None
    payload = dict(review.payload)
    decisions = {d.song_key: d for d in session.scalars(select(Decision)).all()}
    wanted = playlists.wanted_by_song(session)
    songs = []
    for song in payload["songs"]:
        decision = decisions.get(song["id"])
        present = [v for v in song["versions"] if Path(v["path"]).is_file()]
        if decision and decision.applied_batch_id:
            if not present:
                continue
            decision = None
        paths = {v["path"] for v in song["versions"]}
        if decision and decision.choice == "keep" and decision.keep_path not in paths:
            decision = None
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
    if choice == "keep":
        version = next(v for v in song["versions"] if v["path"] == keep_path)
        if version.get("invalid") or dl.not_mp3_reason(version):
            raise ValueError("Only MP3 files can be kept. Reject this version instead.")
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
        pick = {"song": song["song"], "keep": keep, "reject": [p for p in paths if p != keep],
                "signatures": {v["path"]: [v["size"], v["mtime_ns"]] for v in song["versions"]}}
        if keep:
            version = next(v for v in song["versions"] if v["path"] == keep)
            pick["artist"], pick["title"] = dl.inbox_name(song, version)
            pick.update(dl.missing_info(song, version))
        out.append(pick)
        songs[song["id"]] = paths
    return out, songs


def preview_intake(session, song_keys=None):
    chosen, songs = picks(session, song_keys)
    if not chosen:
        raise library.BatchError("No decided songs to move. Pick Keep or Reject all first.")
    return library.preview(session, "intake", {"picks": chosen, "songs": songs})
