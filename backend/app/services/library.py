"""Library state in the database, and the preview -> apply -> undo flow for file changes."""
import threading
from pathlib import Path

from sqlalchemy import func, select

from ..config import get_config
from ..core import library as lib
from ..db import session_scope
from ..jobs import handler
from ..models import Batch, Decision, File, FileOp, Playlist, now
from . import settings

_apply_lock = threading.Lock()


class BatchError(Exception):
    """The batch cannot be applied as asked (shown to the user)."""


# --- Library scan -------------------------------------------------------------------


def _cache(session, area="library"):
    rows = session.scalars(select(File).where(File.area == area)).all()
    return {r.path: {"size": r.size, "mtime_ns": r.mtime_ns, "fp": r.quick_fp, "artist": r.artist,
                     "title": r.title, "genre_tag": r.genre_tag, "bpm": r.bpm} for r in rows}


def scan(session):
    """Fresh scan of the library on disk, reusing stored fingerprints for unchanged files."""
    root = get_config().root
    if not root.is_dir():
        raise BatchError(f"Library not found: {root}")
    return lib.scan(root, _cache(session))


def sync_library(session, tracks=None):
    """Store the library scan in the files table. Returns counts."""
    tracks = scan(session) if tracks is None else tracks
    existing = {r.path: r for r in session.scalars(select(File).where(File.area == "library")).all()}
    seen, added = set(), 0
    stamp = now()
    for t in tracks:
        row = existing.get(t["abs"])
        if row is None:
            row = File(path=t["abs"], area="library", first_seen=stamp)
            session.add(row)
            added += 1
        if row.quick_fp != t["fp"] or row.size != t["size"] or row.mtime_ns != t["mtime_ns"]:
            row.sha256 = None if row.quick_fp and row.quick_fp != t["fp"] else row.sha256
        row.kind, row.folder, row.rel_path = t["kind"], t["folder"], t["path"]
        row.size, row.mtime_ns, row.quick_fp = t["size"], t["mtime_ns"], t["fp"]
        row.artist, row.title, row.genre_tag, row.bpm = t["artist"], t["title"], t["genre_tag"], t["bpm"]
        row.present, row.last_seen = True, stamp
        seen.add(t["abs"])
    gone = 0
    for path, row in existing.items():
        if path not in seen and row.present:
            row.present = False
            gone += 1
    session.flush()
    return {"files": len(tracks), "added": added, "gone": gone}


def register_file(session, path, area):
    """Find or create the files row for an absolute path (for downloads and analysis inputs)."""
    path = str(path)
    row = session.scalar(select(File).where(File.path == path))
    if row is None:
        row = File(path=path, area=area)
        session.add(row)
        session.flush()
    return row


# --- Plans and batches ---------------------------------------------------------------


def make_plan(session, kind, payload, when=None, tracks=None):
    """Plan without storing it (dry run). payload depends on kind:
    apply: {"items": [...]}, remove: {"paths": [...]}, intake: {"picks": [...]}, undo: {"batch_id": id}."""
    cfg = get_config()
    when = when or lib.stamp()
    if kind == "undo":
        target = session.get(Batch, payload.get("batch_id"))
        if target is None:
            raise BatchError("Batch not found")
        if target.status not in ("applied", "partial"):
            raise BatchError(f"Batch {target.id} is {target.status}; only applied batches can be undone")
        if target.kind == "undo":
            raise BatchError("An undo cannot be undone; plan the change again instead")
        ops = session.scalars(select(FileOp).where(FileOp.batch_id == target.id).order_by(FileOp.seq)).all()
        return lib.plan_undo(cfg.root, cfg.trash, target.legacy_id or str(target.id),
                             [{"action": o.action, "source": o.source, "dest": o.dest,
                               "trash": o.label == "trash"} for o in ops])
    tracks = scan(session) if tracks is None else tracks
    if kind == "apply":
        return lib.plan_apply(cfg.root, tracks, payload.get("items") or [])
    if kind == "remove":
        return lib.plan_remove(cfg.root, cfg.trash, tracks, payload.get("paths") or [], when=when)
    if kind == "intake":
        return lib.plan_intake(cfg.root, settings.sources(session), tracks, payload.get("picks") or [])
    raise BatchError(f"Unknown batch kind {kind!r}")


def preview(session, kind, payload, label=""):
    """Plan a change and store it as a batch waiting for confirmation."""
    when = lib.stamp()
    plan = make_plan(session, kind, payload, when=when)
    batch = Batch(kind=kind, status="preview", label=label or default_label(kind, plan),
                  request={"payload": payload, "when": when}, plan=plan.to_dict(),
                  undoes_id=payload.get("batch_id") if kind == "undo" else None)
    session.add(batch)
    session.flush()
    return batch


def default_label(kind, plan):
    counts = {}
    for step in plan.runnable():
        counts[step.label or step.action] = counts.get(step.label or step.action, 0) + 1
    detail = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "nothing to do"
    return {"apply": "Library change", "remove": "Send to Trash", "intake": "Downloads to Inbox/Rejected",
            "undo": "Undo"}.get(kind, kind) + f" ({detail})"


def _step_keys(plan_dict):
    return [(s["action"], s["source"], s["dest"]) for s in plan_dict["steps"] if s["action"] != "skip"]


def apply(session_factory, batch_id):
    """Run a previewed batch. The plan is computed again first; if the library changed
    since the preview, nothing is done and the user is asked to preview again.

    `session_factory` is a context manager giving a session (each step is logged in
    its own transaction, so a crash half way still leaves an accurate history)."""
    with _apply_lock:
        refusal = None
        with session_factory() as session:
            batch = session.get(Batch, batch_id)
            if batch is None:
                raise BatchError("Batch not found")
            if batch.status != "preview":
                raise BatchError(f"Batch {batch.id} is already {batch.status}")
            fresh = make_plan(session, batch.kind, batch.request["payload"], when=batch.request["when"])
            if _step_keys(fresh.to_dict()) != _step_keys(batch.plan):
                batch.status = "discarded"
                batch.error = "The library changed since the preview"
                refusal = "The files changed since the preview. Preview the change again."
            else:
                batch.status = "running"
                batch.applied_at = now()
        if refusal:
            raise BatchError(refusal)
        seq = [0]
        moved = set()

        def log(step):
            seq[0] += 1
            moved.add(step.source)
            with session_factory() as s:
                s.add(FileOp(batch_id=batch_id, seq=seq[0], action=step.action, label=step.label,
                             source=step.source, dest=step.dest))

        error = ""
        try:
            done = lib.execute(get_config().root, fresh, on_done=log)
        except OSError as exc:
            done, error = None, str(exc)
        with session_factory() as session:
            batch = session.get(Batch, batch_id)
            if error:
                batch.status = "partial" if seq[0] else "failed"
                batch.error = error
            else:
                batch.status = "applied"
            if batch.kind == "undo" and batch.status == "applied" and batch.undoes_id:
                target = session.get(Batch, batch.undoes_id)
                target.status = "undone"
                for decision in session.scalars(select(Decision).where(
                        Decision.applied_batch_id == target.id)).all():
                    decision.applied_batch_id = None
            if batch.kind == "intake":
                # A reviewed song is done once all its files have moved.
                for key, paths in (batch.request["payload"].get("songs") or {}).items():
                    decision = session.get(Decision, key)
                    if decision and paths and all(p in moved for p in paths):
                        decision.applied_batch_id = batch.id
            sync_library(session)
            result = {"id": batch.id, "status": batch.status, "error": batch.error, "done": seq[0],
                      "kind": batch.kind}
        if error and not seq[0]:
            raise BatchError(error)
        return result


def discard(session, batch_id):
    batch = session.get(Batch, batch_id)
    if batch and batch.status == "preview":
        batch.status = "discarded"


def batch_dict(session, batch, with_ops=False):
    out = {
        "id": batch.id, "kind": batch.kind, "status": batch.status, "label": batch.label,
        "created_at": batch.created_at, "applied_at": batch.applied_at, "error": batch.error,
        "undoes_id": batch.undoes_id, "legacy_id": batch.legacy_id,
        "plan": batch.plan, "root": str(get_config().root),
        "can_undo": batch.status in ("applied", "partial") and batch.kind != "undo",
    }
    if with_ops:
        out["ops"] = [{"seq": o.seq, "action": o.action, "label": o.label, "source": o.source, "dest": o.dest}
                      for o in session.scalars(select(FileOp).where(FileOp.batch_id == batch.id)
                                               .order_by(FileOp.seq)).all()]
    return out


def rel(path):
    """Path relative to the library root when it is inside it (for display)."""
    try:
        return str(Path(path).relative_to(get_config().root))
    except ValueError:
        return str(path)


@handler("library_scan")
def run_scan(ctx):
    """Read the library from disk into the database, then match the playlists again."""
    from . import playlists

    ctx.progress(0, 0, "Scanning the library")
    with session_scope() as s:
        counts = sync_library(s)
    with session_scope() as s:
        matched = playlists.match_all(s) if s.scalar(select(func.count()).select_from(Playlist)) else None
    message = f"{counts['files']} files ({counts['added']} new, {counts['gone']} gone)"
    return {"message": message, **counts, "matches": matched}
