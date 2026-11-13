"""Library browsing, file details, audio streaming and file batches."""
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from ..config import get_config
from ..core import library as lib
from ..db import session_scope
from ..jobs import runner
from ..models import Batch, File, Playlist
from ..services import analysis, library, playlists, settings
from . import get_session

router = APIRouter()


def file_dict(row):
    return {"id": row.id, "path": row.path, "rel_path": row.rel_path, "area": row.area, "kind": row.kind,
            "folder": row.folder, "artist": row.artist, "title": row.title, "genre_tag": row.genre_tag,
            "bpm": row.bpm, "size": row.size, "present": row.present, "name": Path(row.path).name,
            "quick_fp": row.quick_fp}


@router.get("/library/tree")
def tree(session=Depends(get_session)):
    """Folders with file counts, grouped by kind, plus the genre and session names."""
    rows = session.execute(select(File.kind, File.folder, func.count()).where(
        File.area == "library", File.present.is_(True)).group_by(File.kind, File.folder)).all()
    folders = [{"kind": k, "folder": f, "count": n} for k, f, n in rows]
    root = get_config().root
    genres = sorted(p.name for p in (root / lib.GENRES).iterdir() if p.is_dir() and not p.name.startswith(".")) \
        if (root / lib.GENRES).is_dir() else []
    sessions = sorted(p.name for p in (root / lib.SESSIONS).iterdir() if p.is_dir()
                      and not p.name.startswith(".")) if (root / lib.SESSIONS).is_dir() else []
    return {"root": str(root), "folders": folders, "genres": genres, "sessions": sessions}


@router.get("/library/files")
def files(kind: str | None = None, folder: str | None = None, q: str | None = None, area: str = "library",
          session=Depends(get_session)):
    query = select(File).where(File.area == area, File.present.is_(True))
    if kind:
        query = query.where(File.kind == kind)
    if folder:
        query = query.where(File.folder == folder)
    rows = session.scalars(query.order_by(File.rel_path, File.path)).all()
    if q:
        words = lib.normalize(q).split()
        rows = [r for r in rows if all(w in lib.normalize(f"{r.artist} {r.title} {r.rel_path or r.path}")
                                       for w in words)]
    # Latest loudness per file, for the table.
    latest = {}
    if rows:
        for m in analysis.latest_by_path(session, [r.path for r in rows]):
            latest[m["path"]] = m
    out = [file_dict(r) | {"loudness": latest.get(r.path)} for r in rows]
    if kind == "inbox" and area == "library":
        _mark_already_in_library(session, out, rows)
    return out


def _mark_already_in_library(session, out, inbox_rows):
    """Inbox rows get `in_library`: copies of the same song in genre or session folders (same audio file, or
    same artist and title), so a duplicate is known before moving."""
    others = session.scalars(select(File).where(File.area == "library", File.present.is_(True),
                                                File.kind.in_(["genre", "session"]))).all()
    by_fp, by_name = {}, {}
    for o in others:
        if o.quick_fp:
            by_fp.setdefault(o.quick_fp, []).append(o)
        if o.title:
            by_name.setdefault(lib.match_key(o.artist, o.title), []).append(o)
    loudness = {m["path"]: m for m in analysis.latest_by_path(session, [o.path for o in others])}
    for entry, row in zip(out, inbox_rows):
        hits = {o.path: (o, "file") for o in by_fp.get(row.quick_fp, [])} if row.quick_fp else {}
        if row.title:
            for o in by_name.get(lib.match_key(row.artist, row.title), []):
                hits.setdefault(o.path, (o, "name"))
        entry["in_library"] = [
            {"rel_path": o.rel_path, "kind": o.kind, "folder": o.folder, "match": match,
             "integrated_lufs": (loudness.get(o.path) or {}).get("integrated_lufs")}
            for o, match in hits.values()]


@router.get("/library/status")
def status(session=Depends(get_session)):
    tracks = library.scan(session)
    report = lib.status(tracks)
    report["dupes"] = lib.dupes(tracks)
    return report


@router.get("/files/{file_id}")
def file_detail(file_id: int, session=Depends(get_session)):
    row = session.get(File, file_id)
    if row is None:
        raise HTTPException(404, "File not found")
    copies = []
    if row.quick_fp:
        copies = [file_dict(c) for c in session.scalars(select(File).where(
            File.quick_fp == row.quick_fp, File.present.is_(True), File.id != row.id)).all()]
    return {**file_dict(row), "copies": copies, "history": analysis.file_history(session, row),
            "playlists": playlists.playlists_for_path(session, row.path)}


def _allowed(path):
    """Only files inside the library or the download folders are served or revealed."""
    with session_scope() as s:
        roots = [get_config().root] + list(settings.sources(s))
    resolved = Path(path).resolve()
    return any(Path(r).resolve() in resolved.parents for r in roots)


@router.get("/files/{file_id}/audio")
def audio_stream(file_id: int, session=Depends(get_session)):
    row = session.get(File, file_id)
    if row is None or not Path(row.path).is_file() or not _allowed(row.path):
        raise HTTPException(404, "File not available")
    return FileResponse(row.path)


@router.post("/files/{file_id}/reveal")
def reveal(file_id: int, session=Depends(get_session)):
    row = session.get(File, file_id)
    if row is None or not Path(row.path).exists() or not _allowed(row.path):
        raise HTTPException(404, "File not available")
    subprocess.run(["open", "-R", row.path], check=False)
    return {"ok": True}


# --- Batches ---------------------------------------------------------------------


class PreviewBody(BaseModel):
    kind: str
    payload: dict
    label: str = ""


@router.post("/batches/preview")
def preview(body: PreviewBody, session=Depends(get_session)):
    try:
        batch = library.preview(session, body.kind, body.payload, body.label)
    except library.BatchError as exc:
        raise HTTPException(400, str(exc))
    return library.batch_dict(session, batch)


@router.post("/batches/{batch_id}/apply")
def apply(batch_id: int):
    try:
        result = library.apply(session_scope, batch_id)
    except library.BatchError as exc:
        raise HTTPException(409, str(exc))
    if result.get("replaced"):
        runner.submit("analyze", {"paths": result["replaced"], "reuse": True})
    with session_scope() as s:
        if s.scalar(select(func.count()).select_from(Playlist)):
            runner.submit("match_playlists")
    return result


@router.post("/batches/{batch_id}/discard")
def discard(batch_id: int, session=Depends(get_session)):
    library.discard(session, batch_id)
    return {"ok": True}


@router.post("/batches/{batch_id}/undo")
def undo_preview(batch_id: int, session=Depends(get_session)):
    try:
        batch = library.preview(session, "undo", {"batch_id": batch_id})
    except library.BatchError as exc:
        raise HTTPException(400, str(exc))
    return library.batch_dict(session, batch)


@router.get("/batches")
def batches(limit: int = 100, session=Depends(get_session)):
    rows = session.scalars(select(Batch).where(Batch.status != "discarded").order_by(Batch.id.desc())
                           .limit(limit)).all()
    out = []
    for b in rows:
        d = library.batch_dict(session, b)
        d.pop("plan")
        d["steps"] = len([s for s in b.plan.get("steps", []) if s["action"] != "skip"])
        out.append(d)
    return out


@router.get("/batches/{batch_id}")
def batch(batch_id: int, session=Depends(get_session)):
    row = session.get(Batch, batch_id)
    if row is None:
        raise HTTPException(404, "Batch not found")
    return library.batch_dict(session, row, with_ops=True)
