"""Loudness analysis: runs, the current library view, and starting a run."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import get_config
from ..jobs import runner
from ..services import analysis
from . import get_session

router = APIRouter()


class AnalyzeBody(BaseModel):
    path: str | None = None
    paths: list[str] = []
    reuse: bool = True


@router.get("/analysis")
def overview(session=Depends(get_session, scope="function")):
    return analysis.overview(session)


@router.get("/analysis/runs/{job_id}")
def run(job_id: int, session=Depends(get_session, scope="function")):
    return analysis.run_tracks(session, job_id)


def analysis_params(paths, path=None, reuse=True):
    """Validated job params for an analysis run. Raises ValueError with a message for the user."""
    raw = [p for p in (paths or ([path] if path else [])) if isinstance(p, str) and p.strip()]
    if not raw:
        raise ValueError("Choose at least one file or folder")
    resolved = []
    for item in raw:
        found = Path(item.strip()).expanduser()
        if not found.is_absolute():
            found = get_config().root / found
        if not found.exists():
            raise ValueError(f"Not found: {found}")
        resolved.append(str(found.resolve()))
    return {"paths": resolved, "reuse": bool(reuse)}


@router.post("/analysis")
def start(body: AnalyzeBody):
    try:
        params = analysis_params(body.paths, body.path, body.reuse)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": runner.submit("analyze", params)}
