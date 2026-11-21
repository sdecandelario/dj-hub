"""Rekordbox export logs reviewed against the library. Read only: the logs and the Rekordbox
library are never changed; the page tells you where each file is now so you can relocate it."""
import re
from pathlib import Path

from sqlalchemy import select

from ..config import get_config
from ..core import rekordbox as rb
from ..models import Batch, File, FileOp
from . import library


def read_logs():
    """All export logs, oldest first: [{'name', 'entries'}]."""
    folder = get_config().rekordbox_dir
    logs = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.txt")):
            entries = rb.parse_log(rb.decode(path.read_bytes()))
            if entries:
                logs.append({"name": path.name, "date": (re.search(r"\d{4}-\d{2}-\d{2}", path.name) or [""])[0],
                             "entries": entries})
    return logs


def review(session):
    """Every track Rekordbox could not export, with where its file is now."""
    cfg = get_config()
    logs = read_logs()
    tracks = library.scan(session)
    by_abs = {t["abs"]: t for t in tracks}
    ops = [{"id": o.id, "source": o.source, "dest": o.dest, "label": o.label, "batch_id": o.batch_id,
            "batch_status": status, "batch_kind": kind, "batch_label": label}
           for o, status, kind, label in session.execute(
               select(FileOp, Batch.status, Batch.kind, Batch.label).join(Batch, Batch.id == FileOp.batch_id)
               .order_by(FileOp.id)).all()]
    files = {f.path: f for f in session.scalars(select(File).where(File.area == "library", File.present.is_(True)))}
    merged = {}
    for log in logs:
        for entry in log["entries"]:
            row = merged.setdefault(entry["path"], {**entry, "logs": []})
            row["logs"].append(log["date"] or log["name"])
    root = cfg.root
    out = []
    for path, entry in merged.items():
        final, hops = rb.follow_trail(ops, path)
        exists_now = Path(path).is_file()
        current = by_abs.get(final) if Path(final).is_file() else None
        trashed = bool(hops) and not current and (hops[-1]["label"] == "trash" or not Path(final).exists())
        found = [] if exists_now or current else rb.candidates(entry, tracks)
        if exists_now:
            status, new = "ok", path
        elif current:
            status, new = "moved", current["abs"]
        elif found:
            status, new = "replaced" if trashed else "similar", found[0]["abs"]
        else:
            status, new = "missing", ""
        out.append({
            "title": entry["title"], "old_path": path, "reason": rb.REASONS.get(entry["reason"], ""),
            "logs": entry["logs"], "status": status, "new_path": new,
            "new_rel": _rel(new, root), "file_id": files[new].id if new in files else None,
            "candidates": [{"path": c["abs"], "rel_path": c["path"], "kind": c["kind"],
                            "file_id": files[c["abs"]].id if c["abs"] in files else None} for c in found],
            "trail": [{"batch_id": h["batch_id"], "batch": h["batch_label"] or h["batch_kind"],
                       "status": h["batch_status"], "action": "Sent to the Trash" if h["label"] == "trash" else "Moved",
                       "dest": h["dest"]} for h in hops],
        })
    order = {"missing": 0, "similar": 1, "replaced": 2, "moved": 3, "ok": 4}
    out.sort(key=lambda r: (order[r["status"]], r["old_path"]))
    return {"folder": str(cfg.rekordbox_dir), "logs": [{"name": log["name"], "tracks": len(log["entries"])} for log in logs],
            "tracks": out}


def _rel(path, root):
    try:
        return str(Path(path).relative_to(root)) if path else ""
    except ValueError:
        return path
