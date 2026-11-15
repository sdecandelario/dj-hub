"""One-time import of the old projects' data. Read-only on the old files; safe to run twice.

- DJ_Loudness_Analyzer/runs/*.json        -> analysis runs and measurements
- DJ_Loudness_Analyzer/runs/.downloads-cache.json -> downloads measurement cache
- <library>/.djlib-log.jsonl               -> file batches (so old batches can be undone)
- DJ_Playlist_Checker/check_playlists.py + latest.json -> playlists and their tracks
"""
import datetime as dt
import json
import os
import re
from pathlib import Path

from sqlalchemy import select

from ..config import get_config
from ..models import Batch, FileOp, Job, Measurement, Playlist, PlaylistTrack
from . import settings

LEGACY_DIR = Path(os.environ.get("DJ_HUB_LEGACY_DIR", "~/Projects")).expanduser()
# Which DJ project each reference playlist defines (from DJ_Playlist_Checker/AGENTS.md).
DEFAULT_PROJECTS = {
    "3PuCqjzr4B2fWcsd2SGKp7": "Serge Candel",
    "1U0L91CdWLM5HNz5gIITqr": "Serge Candel",
    "0y8lq7C5y2vtmOxSSAuwzp": "Serge Candel",
    "2K52sYJ72EQ8VT5sk49m2k": "Serge Candel",
    "1FURH6wFT0gwsbOZpMWSy3": "Perry Boys",
}


def _when(ident):
    try:
        return dt.datetime.strptime(ident[:19], "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return dt.datetime.now().replace(microsecond=0)


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def import_runs(session, folder):
    added = 0
    for path in sorted(Path(folder).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("schema_version") != 2 or not {"id", "date", "config", "tracks"} <= set(record):
                continue
        except (OSError, ValueError, AttributeError):   # one damaged old file must not stop the import
            continue
        if session.scalar(select(Job).where(Job.legacy_id == record["id"])):
            continue
        when = _when(record["date"])
        job = Job(type="analyze", status="done" if record["complete"] else "interrupted",
                  params={"path": record["config"].get("input", "")}, legacy_id=record["id"],
                  summary={"scope": record["scope"], "complete": record["complete"],
                           "input": record["config"].get("input", ""), "config": record["config"],
                           "manifest": record["manifest"]},
                  message=f"Imported from {path.name}", done=len(record["tracks"]), total=len(record["tracks"]),
                  created_at=when, started_at=when, finished_at=when)
        session.add(job)
        session.flush()
        for t in record["tracks"]:
            session.add(Measurement(
                job_id=job.id, path=t["path"], sha256=t.get("sha256"), measured_at=when, origin="legacy-run",
                status=t.get("status", ""), error=t.get("error") or "",
                integrated_lufs=_float(t.get("integrated_lufs")), true_peak_dbtp=_float(t.get("true_peak_dbtp")),
                loudness_range_lu=_float(t.get("loudness_range_lu")),
                duration_seconds=_float(t.get("duration_seconds")), codec=t.get("codec") or "",
                sample_rate_hz=_int(t.get("sample_rate_hz")), channels=_int(t.get("channels")),
                extra={k: record["config"][k] for k in ("ffmpeg_version",) if k in record["config"]}))
        added += 1
    return added


def import_downloads_cache(session, path):
    if not Path(path).is_file():
        return 0
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    paths = {}
    for key, sha in (data.get("files") or {}).items():
        paths.setdefault(sha, key.split("|", 1)[0])
    known = {m.sha256 for m in session.scalars(select(Measurement).where(Measurement.full.is_(True))).all()}
    added = 0
    for sha, result in (data.get("hashes") or {}).items():
        if sha in known:
            continue
        quality = ("corrupt_frames", "audio_md5", "tag_artist", "tag_title", "album", "year", "bitrate_kbps",
                   "has_art", "hf_gap_17k_db", "hf_gap_19k_db")
        session.add(Measurement(
            path=paths.get(sha, ""), sha256=sha, full=True, origin="legacy-cache",
            status=result.get("status") or "", error=result.get("error") or "",
            integrated_lufs=result.get("integrated_lufs"), true_peak_dbtp=result.get("true_peak_dbtp"),
            loudness_range_lu=result.get("loudness_range_lu"), duration_seconds=result.get("duration_seconds"),
            codec=result.get("codec") or "", sample_rate_hz=_int(result.get("sample_rate_hz")),
            extra={k: result.get(k) for k in quality}))
        added += 1
    return added


def import_djlib_log(session, path):
    """Batches from djlib.py. Library-relative paths become absolute."""
    if not Path(path).is_file():
        return 0
    root = get_config().root
    entries = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    undone = {e["batch"] for e in entries if e.get("action") == "undo"}
    order = []
    for e in entries:
        if e.get("action") != "undo" and e["batch"] not in order:
            order.append(e["batch"])
    absolute = lambda p: str(Path(p) if Path(p).is_absolute() else root / p)
    added = 0
    for ident in order:
        if session.scalar(select(Batch).where(Batch.legacy_id == ident)):
            continue
        ops = [e for e in entries if e["batch"] == ident and e.get("action") != "undo"]
        counts = {}
        for e in ops:
            counts[e["action"]] = counts.get(e["action"], 0) + 1
        batch = Batch(kind="legacy", status="undone" if ident in undone else "applied", legacy_id=ident,
                      label="dj-library skill (" + ", ".join(f"{n} {a}" for a, n in sorted(counts.items())) + ")",
                      created_at=_when(ident), applied_at=_when(ident),
                      plan={"kind": "legacy", "steps": [], "problems": [], "notes": []})
        session.add(batch)
        session.flush()
        for seq, e in enumerate(ops, 1):
            session.add(FileOp(batch_id=batch.id, seq=seq, action="copy" if e["action"] == "copy" else "move",
                               label="trash" if e["action"] == "trash" else "",
                               source=absolute(e["source"]), dest=absolute(e["dest"])))
        added += 1
    return added


def import_playlists(session, checker_dir):
    checker_dir = Path(checker_dir)
    ids = []
    script = checker_dir / "check_playlists.py"
    if script.is_file():
        block = re.search(r"PLAYLISTS\s*=\s*\[(.*?)\]", script.read_text(encoding="utf-8"), re.S)
        ids = re.findall(r'"([A-Za-z0-9]{22})"', block.group(1)) if block else []
    latest, generated = {}, None
    report = checker_dir / "latest.json"
    if report.is_file():
        data = json.loads(report.read_text(encoding="utf-8"))
        latest = {p["id"]: p for p in data["playlists"]}
        try:
            generated = dt.datetime.fromisoformat(data.get("generated_at", ""))
        except ValueError:
            generated = None
        ids += [i for i in latest if i not in ids]
    added = 0
    for position, playlist_id in enumerate(ids):
        if session.get(Playlist, playlist_id):
            continue
        data = latest.get(playlist_id, {})
        session.add(Playlist(id=playlist_id, name=data.get("name") or playlist_id, owner=data.get("owner", ""),
                             cover=data.get("cover"), source=data.get("source", ""),
                             possibly_truncated=bool(data.get("possibly_truncated")),
                             project=DEFAULT_PROJECTS.get(playlist_id, ""), position=position,
                             refreshed_at=generated if data else None))
        for i, t in enumerate(data.get("tracks", [])):
            session.add(PlaylistTrack(playlist_id=playlist_id, position=i, spotify_id=t["spotify_id"],
                                      title=t.get("title", ""), artists=t.get("artists", []),
                                      duration_ms=t.get("duration_ms")))
        added += 1
    return added


def import_all(session, legacy_dir=None):
    legacy_dir = Path(legacy_dir or LEGACY_DIR)
    analyzer = legacy_dir / "DJ_Loudness_Analyzer"
    result = {
        "runs": import_runs(session, analyzer / "runs"),
        "downloads_cache": import_downloads_cache(session, analyzer / "runs" / ".downloads-cache.json"),
        "batches": import_djlib_log(session, get_config().root / ".djlib-log.jsonl"),
        "playlists": import_playlists(session, legacy_dir / "DJ_Playlist_Checker"),
    }
    if any(result.values()) or settings.get(session, "legacy_imported") is None:
        settings.put(session, "legacy_imported", result)   # a repeat import that adds nothing keeps the first summary
    session.flush()
    return result
