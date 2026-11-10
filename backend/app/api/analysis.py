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
def overview(session=Depends(get_session)):
    return analysis.overview(session)


@router.get("/analysis/runs/{job_id}")
def run(job_id: int, session=Depends(get_session)):
    return analysis.run_tracks(session, job_id)


@router.post("/analysis")
def start(body: AnalyzeBody):
    raw = body.paths or ([body.path] if body.path else [])
    if not raw:
        raise HTTPException(400, "Choose at least one file or folder")
    paths = []
    for item in raw:
        path = Path(item).expanduser()
        if not path.is_absolute():
            path = get_config().root / path
        if not path.exists():
            raise HTTPException(400, f"Not found: {path}")
        paths.append(str(path))
    return {"id": runner.submit("analyze", {"paths": paths, "reuse": body.reuse})}
