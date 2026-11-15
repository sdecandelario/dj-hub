"""Loudness analysis runs: measure a file or a folder, keep every result as history."""
import concurrent.futures
import os
from pathlib import Path

from sqlalchemy import select

from ..config import get_config
from ..core import audio, history
from ..db import session_scope
from ..jobs import handler
from ..models import File, Job, Measurement
from .library import register_file

MEASURE_FIELDS = ("status", "error", "integrated_lufs", "true_peak_dbtp", "loudness_range_lu",
                  "duration_seconds", "codec", "sample_rate_hz", "channels")
QUALITY_FIELDS = ("corrupt_frames", "audio_md5", "tag_artist", "tag_title", "album", "year",
                  "bitrate_kbps", "has_art", "hf_gap_17k_db", "hf_gap_19k_db",
                  "loud_lufs", "momentary_max_lufs", "tone_low_db", "tone_mid_db", "tone_presence_db", "tone_air_db")
DEEP_MARKER = "tone_air_db"  # measurements without it predate the loud-section and tone checks
# What each page needs from a stored measurement before it can reuse it instead of measuring again.
ANALYSIS_NEEDS = (DEEP_MARKER,)
REVIEW_NEEDS = ("audio_md5", "hf_gap_19k_db", "corrupt_frames")


def measurement_row(m):
    """A measurement as a flat dict (the shape the history and the review use)."""
    row = {"id": m.id, "job_id": m.job_id, "path": m.path, "filename": os.path.basename(m.path),
           "sha256": m.sha256, "measured_at": m.measured_at, "origin": m.origin, "full": m.full}
    row.update({k: getattr(m, k) for k in MEASURE_FIELDS})
    row.update({k: (m.extra or {}).get(k) for k in QUALITY_FIELDS if k in (m.extra or {})})
    return row


def new_measurement(path, result, sha, stat, job_id, full, origin="app", versions=None):
    extra = {k: result.get(k) for k in QUALITY_FIELDS if k in result}
    if versions:
        extra.update(versions)
    return Measurement(job_id=job_id, path=str(path), sha256=sha, size=stat.st_size if stat else None,
                       mtime_ns=str(stat.st_mtime_ns) if stat else None, full=full, origin=origin,
                       extra=extra, **{k: result.get(k) for k in MEASURE_FIELDS})


def cached_sha(session, path, stat):
    row = session.scalar(select(File).where(File.path == str(path)))
    if row and row.sha256 and row.size == stat.st_size and row.mtime_ns == str(stat.st_mtime_ns):
        return row.sha256
    return None


def cached_shas(session, items):
    """Fill item["sha256"] from the stored hashes in one pass: only for files whose size and
    modification time still match what was hashed. `items` need path, size and mtime_ns."""
    stored = {}
    paths = [i["path"] for i in items]
    for start in range(0, len(paths), 500):
        for row in session.scalars(select(File).where(File.path.in_(paths[start:start + 500]))).all():
            stored[row.path] = row
    for item in items:
        row = stored.get(item["path"])
        ok = row and row.sha256 and row.size == item["size"] and row.mtime_ns == str(item["mtime_ns"])
        item["sha256"] = row.sha256 if ok else None


def _usable(m, ffmpeg_version, need):
    extra = m.extra or {}
    return extra.get("ffmpeg_version") in (None, ffmpeg_version) and all(key in extra for key in need)


def reusable_many(session, shas, ffmpeg_version, need=()):
    """{sha: newest good measurement of those bytes} in few queries. The measurement must come from
    this ffmpeg (or an unknown one) and hold every key in `need` (what the caller wants to show), so work
    done by the analysis page and by the downloads review can be shared."""
    found = {}
    shas = sorted({s for s in shas if s})
    for start in range(0, len(shas), 500):
        query = select(Measurement).where(Measurement.sha256.in_(shas[start:start + 500]), Measurement.status == "OK")
        for m in session.scalars(query.order_by(Measurement.id.desc())).all():
            if m.sha256 not in found and _usable(m, ffmpeg_version, need):
                found[m.sha256] = m
    return found


def reusable(session, sha, ffmpeg_version, need=()):
    """A previous good measurement of the same bytes with the same ffmpeg that holds the `need` keys."""
    return reusable_many(session, [sha], ffmpeg_version, need).get(sha)


def collect_paths(sources):
    """Audio files under each source (a file or a folder), sorted, without duplicates
    when sources overlap (for example the whole library plus one genre)."""
    found = set()
    for source in sources:
        if source.is_file():
            found.add(source)
            continue
        found.update(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in audio.EXT
                     and not any(part.startswith(".") for part in p.relative_to(source).parts))
    return sorted(found)


def analysis_sources(params):
    """params["paths"] (a list) or params["path"] (one), resolved; nested sources are dropped."""
    raw = params.get("paths") or [params["path"]]
    sources = []
    for item in dict.fromkeys(Path(p).expanduser().resolve() for p in raw):
        if not item.exists() or (item.is_file() and item.suffix.lower() not in audio.EXT):
            raise ValueError(f"Input does not exist or format is unsupported: {item}")
        sources.append(item)
    return [s for s in sources if not any(o != s and o.is_dir() and s.is_relative_to(o) for o in sources)]


@handler("analyze")
def run_analysis(ctx):
    """params: {"path": file or folder} or {"paths": [files or folders]}, "reuse": true.
    Measuring is read-only."""
    missing = audio.missing_tools()
    if missing:
        raise RuntimeError(f"Missing executable: {', '.join(missing)}")
    sources = analysis_sources(ctx.params)
    if not sources:
        raise ValueError("Nothing to analyze")
    paths = collect_paths(sources)
    versions = audio.tool_versions()
    if all(s.is_dir() for s in sources):
        scope = "folder"  # whole folders: can serve as a reference
    elif len(sources) == 1:
        scope = "file"
    else:
        scope = "selection"  # hand-picked songs: never a reference
    inputs = [str(s) for s in sources]
    summary = {"scope": scope, "input": "; ".join(inputs), "manifest": [str(p) for p in paths],
               "config": {"input": "; ".join(inputs), "inputs": inputs, **versions,
                          "filter": "loudnorm=print_format=json; first audio stream"}}
    with session_scope() as s:
        job = s.get(Job, ctx.job_id)
        job.summary = {**summary, "complete": False}
        done_here = {m.path: m.mtime_ns for m in s.scalars(select(Measurement).where(
            Measurement.job_id == ctx.job_id)).all()}
    total = len(paths)
    ctx.progress(0, total, f"{total} file(s) to analyze")
    todo = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError as exc:
            with session_scope() as s:
                s.add(new_measurement(path, {"status": "ERROR", "error": str(exc)}, None, None, ctx.job_id, False))
            continue
        if done_here.get(str(path)) == str(stat.st_mtime_ns):
            continue  # resumed: measured before the interruption
        todo.append((path, stat))
    finished = total - len(todo)
    reused = 0

    def work(item):
        path, stat = item
        with session_scope() as s:
            sha = cached_sha(s, path, stat)
        sha = sha or audio.sha256_file(path)
        if ctx.params.get("reuse", True):
            with session_scope() as s:
                old = reusable(s, sha, versions["ffmpeg_version"], ANALYSIS_NEEDS)
                if old:
                    return path, stat, sha, measurement_row(old), True
        result = audio.analyze(path)
        after = path.stat()
        if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
            result.update(status="ERROR", error="File changed during analysis")
        return path, stat, sha, result, False

    workers = get_config().workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        pending = set()
        queue = iter(todo)
        for item in queue:
            pending.add(pool.submit(work, item))
            if len(pending) >= workers * 2:
                break
        while pending:
            done, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                path, stat, sha, result, was_reused = future.result()
                reused += was_reused
                with session_scope() as s:
                    s.add(new_measurement(path, result, sha, stat, ctx.job_id, False,
                                          origin="reused" if was_reused else "app", versions=versions))
                    row = register_file(s, path, _area(path))
                    if result.get("status") != "ERROR" or "changed" not in (result.get("error") or ""):
                        row.sha256, row.size, row.mtime_ns = sha, stat.st_size, str(stat.st_mtime_ns)
                finished += 1
                ctx.progress(finished, total, path.name)
            if not ctx.cancelled():
                for item in queue:
                    pending.add(pool.submit(work, item))
                    if len(pending) >= workers * 2:
                        break
    complete = not ctx.cancelled()
    with session_scope() as s:
        job = s.get(Job, ctx.job_id)
        job.summary = {**job.summary, "complete": complete}
    ctx.check()
    return {"complete": True, "message": f"{total} file(s) analyzed ({reused} reused from earlier runs)"}


def _area(path):
    root = get_config().root
    try:
        Path(path).relative_to(root)
        return "library"
    except ValueError:
        return "other"


# --- Reading the history -----------------------------------------------------------------


def runs(session, with_tracks=True):
    """Analysis runs oldest first, in the shape core.history expects."""
    jobs = session.scalars(select(Job).where(Job.type == "analyze", Job.status.in_(
        ("done", "cancelled", "interrupted", "failed", "running"))).order_by(Job.created_at, Job.id)).all()
    by_job = {}
    if with_tracks and jobs:   # one query for every run, not one per run
        for m in session.scalars(select(Measurement).where(Measurement.job_id.in_([j.id for j in jobs]))
                                 .order_by(Measurement.path)).all():
            by_job.setdefault(m.job_id, []).append(measurement_row(m))
    out = []
    for job in jobs:
        summary = job.summary or {}
        tracks = by_job.get(job.id, [])
        out.append({
            "id": job.id, "label": job.legacy_id or job.created_at.strftime("%Y-%m-%d %H:%M"),
            "scope": summary.get("scope", "file"), "complete": bool(summary.get("complete")),
            "status": job.status, "config": summary.get("config") or {"input": job.params.get("path", "")},
            "manifest": summary.get("manifest") or [], "tracks": tracks, "created_at": job.created_at,
            "legacy": bool(job.legacy_id),
        })
    return out


def overview(session):
    """Runs (without tracks), reference candidates with their median, and the current library."""
    all_runs = runs(session)
    current = history.current_library(all_runs)
    listing = []
    for run in all_runs:
        listing.append({k: v for k, v in run.items() if k not in ("tracks", "manifest")}
                       | {"files": len(run["tracks"]), "median_lufs": history.median_lufs(run["tracks"])})
    references = [r for r in listing if r["scope"] == "folder" and r["complete"] and r["median_lufs"] is not None]
    return {"runs": listing[::-1], "references": references[::-1], "current": current}


def run_tracks(session, job_id):
    return [measurement_row(m) for m in session.scalars(
        select(Measurement).where(Measurement.job_id == job_id).order_by(Measurement.path)).all()]


def file_history(session, file):
    """Every measurement of this file: by its path, and by its hash when known."""
    query = select(Measurement).where(Measurement.path == file.path)
    if file.sha256:
        query = select(Measurement).where((Measurement.path == file.path) | (Measurement.sha256 == file.sha256))
    return [measurement_row(m) for m in session.scalars(query.order_by(Measurement.measured_at)).all()]


def library_median(session):
    """Median LUFS of the latest complete folder analysis (the review's reference)."""
    refs = overview_references(session)
    return (refs[0]["median_lufs"], refs[0]["id"]) if refs else (None, None)


def overview_references(session):
    out = []
    for run in reversed(runs(session)):
        if run["scope"] == "folder" and run["complete"]:
            median = history.median_lufs(run["tracks"])
            if median is not None:
                out.append({"id": run["id"], "label": run["label"], "median_lufs": median})
    return out


def latest_for_files(session, files):
    """{file path: newest measurement} (for library tables): found by the file's path, or by its hash,
    so a file that was moved or renamed after it was measured still shows its loudness."""
    by_path, by_sha = {}, {}
    for start in range(0, len(files), 500):
        chunk = files[start:start + 500]
        paths = [f.path for f in chunk]
        shas = [f.sha256 for f in chunk if f.sha256]
        for m in session.scalars(select(Measurement).where(
                Measurement.path.in_(paths) | Measurement.sha256.in_(shas)).order_by(Measurement.id)).all():
            by_path[m.path] = m
            if m.sha256:
                by_sha[m.sha256] = m
    out = {}
    for f in files:
        found = [m for m in (by_path.get(f.path), by_sha.get(f.sha256) if f.sha256 else None) if m]
        if found:
            m = max(found, key=lambda x: x.id)
            out[f.path] = {"path": f.path, "status": m.status, "integrated_lufs": m.integrated_lufs,
                           "true_peak_dbtp": m.true_peak_dbtp, "loudness_range_lu": m.loudness_range_lu,
                           "measured_at": m.measured_at}
    return out
