"""Settings and the home summary."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from ..config import get_config
from ..core import audio
from ..jobs import job_dict
from ..models import Batch, Decision, File, Job, Match, Mark
from ..services import downloads, settings
from . import get_session

router = APIRouter()


class SettingsBody(BaseModel):
    sources: list[str] | None = None


@router.get("/settings")
def get_settings(session=Depends(get_session, scope="function")):
    cfg = get_config()
    return {"root": str(cfg.root), "trash": str(cfg.trash), "db": str(cfg.db_path),
            "sources": [str(p) for p in settings.sources(session)], "sources_locked": settings.sources_locked(),
            "settle_seconds": cfg.settle_seconds, "workers": cfg.workers, "missing_tools": audio.missing_tools()}


@router.put("/settings")
def put_settings(body: SettingsBody, session=Depends(get_session, scope="function")):
    if body.sources is not None:
        if settings.sources_locked():
            raise HTTPException(400, "DJ_SOURCES is set in the environment; change it there")
        paths = [Path(p.strip()).expanduser() for p in body.sources if p.strip()]
        bad = [str(p) for p in paths if not p.is_absolute()]
        if bad:
            raise HTTPException(400, f"Use absolute paths: {', '.join(bad)}")
        # Download folders are where files may be moved from, so they must be real, specific folders.
        bad = [str(p) for p in paths if len(p.resolve().parts) < 3 or not p.is_dir()]
        if bad:
            raise HTTPException(400, f"Not an existing folder (and not a top-level one): {', '.join(bad)}")
        settings.put(session, "sources", [str(p) for p in paths])
    return get_settings(session)


@router.get("/summary")
def summary(session=Depends(get_session, scope="function")):
    """Counts for the home page."""
    count = lambda *where: session.scalar(select(func.count()).select_from(File).where(*where))
    library = (File.area == "library", File.present.is_(True))
    marks = {m.spotify_id for m in session.scalars(select(Mark)).all()}
    matches = session.scalars(select(Match)).all()
    review = downloads.review_view(session)
    pending = [s for s in (review or {}).get("songs", []) if not s.get("decision")]
    decided = [s for s in (review or {}).get("songs", []) if s.get("decision")
               and s["decision"]["choice"] in ("keep", "reject")]
    return {
        "library_files": count(*library, File.kind != "rejected"),
        "inbox": count(*library, File.kind == "inbox"),
        "rejected": count(*library, File.kind == "rejected"),
        "unsorted": count(*library, File.kind == "unsorted"),
        "missing": sum(m.status == "missing" and m.spotify_id not in marks for m in matches),
        "check": sum(m.status == "maybe" for m in matches),
        "waiting_downloads": sum(m.status != "have" and bool(m.download_song_key) for m in matches),
        "marked_downloaded": sum(m.status != "have" and m.spotify_id in marks for m in matches),
        "review_songs": len((review or {}).get("songs", [])),
        "review_pending": len(pending), "review_decided": len(decided),
        "review_generated": (review or {}).get("generated"),
        "recent_jobs": [job_dict(j) for j in session.scalars(select(Job).order_by(Job.id.desc()).limit(6)).all()],
        "recent_batches": [{"id": b.id, "label": b.label, "status": b.status, "created_at": b.created_at,
                            "kind": b.kind}
                           for b in session.scalars(select(Batch).where(Batch.status != "discarded",
                                                                        Batch.status != "preview")
                                                    .order_by(Batch.id.desc()).limit(6)).all()],
        "decisions": session.scalar(select(func.count()).select_from(Decision)),
    }
