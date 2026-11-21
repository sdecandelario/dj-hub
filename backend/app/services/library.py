"""Library state in the database, and the preview -> apply -> undo flow for file changes."""
import threading
from pathlib import Path

from sqlalchemy import func, select

from ..config import get_config
from ..core import library as lib
from ..db import session_scope
from ..jobs import handler
from ..models import Batch, Decision, File, FileOp, Playlist, now
from . import discovery, playlists, settings

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
    # A moved file shows up as a new path. Rows whose path is gone still know its hash and first-seen date
    # (a move keeps size and modification time), so the new row can take them over instead of starting empty.
    listed = {t["abs"] for t in tracks}
    left_behind = {(r.quick_fp, r.size, str(r.mtime_ns)): r for r in existing.values()
                   if r.path not in listed and r.quick_fp}
    for t in tracks:
        row = existing.get(t["abs"])
        previous = None
        if row is None:
            row = File(path=t["abs"], area="library", first_seen=stamp)
            session.add(row)
            added += 1
            previous = left_behind.pop((t["fp"], t["size"], str(t["mtime_ns"])), None)
        if row.quick_fp != t["fp"] or row.size != t["size"] or str(row.mtime_ns) != str(t["mtime_ns"]):
            row.sha256 = None   # the file changed: a stored hash would describe the old bytes
        if previous is not None:
            row.sha256, row.first_seen = previous.sha256, previous.first_seen
        row.kind, row.folder, row.rel_path = t["kind"], t["folder"], t["path"]
        row.size, row.mtime_ns, row.quick_fp = t["size"], t["mtime_ns"], t["fp"]
        row.artist, row.title, row.genre_tag, row.bpm = t["artist"], t["title"], t["genre_tag"], t["bpm"]
        row.present = True
        seen.add(t["abs"])
    gone = 0
    for path, row in existing.items():
        if path not in seen and row.present:
            row.present = False
            gone += 1
    session.flush()
    discovery.complete_wanted(session)
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


def make_plan(session, kind, payload):
    """Plan without storing it (dry run). payload depends on kind:
    apply: {"items": [...]}, remove: {"paths": [...]}, intake: {"picks": [...]}, undo: {"batch_id": id}."""
    cfg = get_config()
    if kind == "undo":
        target = session.get(Batch, payload.get("batch_id"))
        if target is None:
            raise BatchError("Batch not found")
        if target.status not in ("applied", "partial"):
            raise BatchError(f"Batch {target.id} is {target.status}; only applied batches can be undone")
        if target.kind == "undo":
            raise BatchError("An undo cannot be undone; plan the change again instead")
        ops = session.scalars(select(FileOp).where(FileOp.batch_id == target.id).order_by(FileOp.seq)).all()
        return lib.plan_undo(cfg.root, cfg.trash, str(target.id),
                             [{"action": o.action, "source": o.source, "dest": o.dest,
                               "trash": o.label == "trash", "tags_before": o.tags_before} for o in ops])
    tracks = scan(session)
    if kind == "apply":
        return lib.plan_apply(cfg.root, tracks, payload.get("items") or [], trash=cfg.trash)
    if kind == "remove":
        return lib.plan_remove(cfg.root, cfg.trash, tracks, payload.get("paths") or [])
    if kind == "rename":
        return lib.plan_rename(cfg.root, tracks, payload.get("items") or [])
    if kind == "retag":
        return lib.plan_retag(cfg.root, tracks, payload.get("items") or [])
    if kind == "tags":
        return lib.plan_tags(cfg.root, tracks, genre=bool(payload.get("genre")))
    if kind == "intake":
        return lib.plan_intake(cfg.root, settings.sources(session), tracks, payload.get("picks") or [])
    raise BatchError(f"Unknown batch kind {kind!r}")


def preview(session, kind, payload, label=""):
    """Plan a change and store it as a batch waiting for confirmation."""
    plan = make_plan(session, kind, payload)
    batch = Batch(kind=kind, status="preview", label=label or default_label(kind, plan),
                  request={"payload": payload}, plan=plan.to_dict(),
                  undoes_id=payload.get("batch_id") if kind == "undo" else None)
    session.add(batch)
    session.flush()
    return batch


KIND_TITLES = {"apply": "Library change", "remove": "Send to Trash", "intake": "Downloads to Inbox/Rejected",
               "tags": "Fix tags", "retag": "Correct tags", "rename": "Rename files", "undo": "Undo"}


def default_label(kind, plan):
    counts = {}
    for step in plan.runnable():
        counts[step.label or step.action] = counts.get(step.label or step.action, 0) + 1
    detail = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "nothing to do"
    return KIND_TITLES.get(kind, kind) + f" ({detail})"


def apply(session_factory, batch_id):
    """Run a previewed batch exactly as it was shown. `lib.execute` checks the whole plan against the disk
    first (every source exists, no destination is taken), so a library that changed since the preview
    fails the batch before any file is touched.

    `session_factory` is a context manager giving a session (each step is logged in
    its own transaction, so a crash half way still leaves an accurate history)."""
    with _apply_lock:
        with session_factory() as session:
            batch = session.get(Batch, batch_id)
            if batch is None:
                raise BatchError("Batch not found")
            if batch.status != "preview":
                raise BatchError(f"Batch {batch.id} is already {batch.status}")
            plan = lib.Plan.from_dict(batch.plan)
            batch.status = "running"
            batch.applied_at = now()
        state = {"seq": 0, "done": 0, "op": None}
        moved = set()
        warnings = []

        def intend(step):
            # Written down before the file is touched, so a crash cannot leave a move the history does not know.
            state["seq"] += 1
            with session_factory() as s:
                op = FileOp(batch_id=batch_id, seq=state["seq"], action=step.action, label=step.label,
                            source=step.source, dest=step.dest)
                s.add(op)
                s.flush()
                state["op"] = op.id

        def log(step):
            state["done"] += 1
            moved.add(step.source)
            if step.note.startswith('Tags not written'):
                warnings.append(f'{Path(step.dest).name}: {step.note}')
            with session_factory() as s:
                s.get(FileOp, state["op"]).tags_before = step.tags_before or None
            state["op"] = None

        error = ""
        try:
            lib.execute(get_config().root, plan, on_done=log, on_start=intend)
        except Exception as exc:   # whatever went wrong, the batch must not stay "running"
            error = str(exc) or type(exc).__name__
            if state["op"] is not None:   # the step that failed: keep its row only if it really happened
                with session_factory() as s:
                    forget_unexecuted_ops(s, batch_id, only=state["op"])
        with session_factory() as session:
            batch = session.get(Batch, batch_id)
            if error:
                batch.status = "partial" if state["done"] else "failed"
                batch.error = error
            elif batch.kind == "undo" and plan.problems:
                batch.status = "partial"
                batch.error = "Not everything could be undone: " + "; ".join(plan.problems[:3])
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
            follow_moves(session, batch_id)
            sync_library(session)
            result = {"id": batch.id, "status": batch.status, "error": batch.error, "done": state["done"],
                      "kind": batch.kind, "warnings": warnings, "replaced": _replaced(batch.kind, plan, moved)}
        if error and not state["done"]:
            raise BatchError(error)
        return result


def _replaced(kind, plan, moved):
    """Files an apply batch put where an old copy was sent to the Trash: they are measured right away."""
    done = [step for step in plan.runnable() if step.source in moved]
    if kind != "apply" or not any(step.label == "trash" for step in done):
        return []
    return [step.dest for step in done if step.action == "move" and step.label != "trash"]


def forget_unexecuted_ops(session, batch_id, only=None):
    """Drop logged steps whose file change never happened (the intent was written, then the step failed
    or the app stopped). A move or copy happened when its destination exists."""
    query = select(FileOp).where(FileOp.batch_id == batch_id)
    if only is not None:
        query = query.where(FileOp.id == only)
    for op in session.scalars(query).all():
        if op.action != "tags" and not Path(op.dest).exists():
            session.delete(op)
    session.flush()


def follow_moves(session, batch_id):
    """A moved file is the same file: its row in the files table gets the new path instead of a new row
    appearing, so its id (links, selections), stored hash and first-seen date stay with it. Follows the
    batch's move log in order, so a file moved twice ends at its last place."""
    ops = session.scalars(select(FileOp).where(FileOp.batch_id == batch_id, FileOp.action == "move")
                          .order_by(FileOp.seq)).all()
    for op in ops:
        row = session.scalar(select(File).where(File.path == op.source, File.area == "library"))
        if row is None:
            continue
        there = session.scalar(select(File).where(File.path == op.dest))
        if there is not None and there.id != row.id:
            if there.present and there.area == "library" and Path(op.dest).exists() and not Path(op.source).exists():
                pass   # a live row already tracks the destination; the next scan reconciles the old one
            else:
                session.delete(there)   # a leftover row of a file that was here before and left
                session.flush()
        if session.scalar(select(File).where(File.path == op.dest)) is None:
            row.path = op.dest
            session.flush()


def recover_batches(session):
    """Batches left 'running' by a crash: keep what was logged, so the history stays accurate
    and whatever did move can still be undone."""
    stuck = session.scalars(select(Batch).where(Batch.status == "running")).all()
    for batch in stuck:
        forget_unexecuted_ops(session, batch.id)
        logged = session.scalar(select(func.count()).select_from(FileOp).where(FileOp.batch_id == batch.id))
        batch.status = "partial" if logged else "failed"
        batch.error = batch.error or "Interrupted before it finished"
    return len(stuck)


def discard(session, batch_id):
    batch = session.get(Batch, batch_id)
    if batch and batch.status == "preview":
        batch.status = "discarded"


def batch_dict(session, batch, with_ops=False):
    out = {
        "id": batch.id, "kind": batch.kind, "status": batch.status, "label": batch.label,
        "created_at": batch.created_at, "applied_at": batch.applied_at, "error": batch.error,
        "undoes_id": batch.undoes_id,
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
    ctx.progress(0, 0, "Scanning the library")
    with session_scope() as s:
        counts = sync_library(s)
    ctx.check()
    with session_scope() as s:
        matched = playlists.match_all(s) if s.scalar(select(func.count()).select_from(Playlist)) else None
    message = f"{counts['files']} files ({counts['added']} new, {counts['gone']} gone)"
    return {"message": message, **counts, "matches": matched}
