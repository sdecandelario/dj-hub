"""Jobs: list, start, cancel, resume, and a live stream of progress (Server-Sent Events)."""
import asyncio
import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select

from ..db import session_scope
from ..jobs import HANDLERS, job_dict, runner
from ..models import Job
from . import get_session
from .analysis import analysis_params

router = APIRouter()


# What the app can start through POST /jobs, and the params each type accepts.
STARTABLE = {"analyze", "review_downloads", "spotify_refresh", "library_scan", "match_playlists", "discover", "soulseek_download"}


class JobBody(BaseModel):
    type: str
    params: dict = {}


def clean_params(type_, params):
    if type_ == "analyze":
        return analysis_params(params.get("paths"), params.get("path"), params.get("reuse", True))
    if type_ == "discover":
        genre = params.get("genre")
        return {"genre": genre} if isinstance(genre, str) and genre else {}
    if type_ == "soulseek_download":
        query = params.get("query")
        return {"query": query.strip()} if isinstance(query, str) and query.strip() else {}
    if type_ == "spotify_refresh":
        ids = params.get("ids")
        return {"ids": [i for i in ids if isinstance(i, str)]} if isinstance(ids, list) and ids else {}
    return {}


@router.get("/jobs")
def jobs(type: str | None = None, limit: int = Query(100, ge=1, le=500), session=Depends(get_session, scope="function")):
    query = select(Job).order_by(Job.id.desc()).limit(limit)
    if type:
        query = query.where(Job.type == type)
    return [job_dict(j) for j in session.scalars(query).all()]


@router.get("/jobs/{job_id}")
def job(job_id: int, session=Depends(get_session, scope="function")):
    row = session.get(Job, job_id)
    if row is None:
        raise HTTPException(404, "Job not found")
    return job_dict(row) | {"log": row.log}


@router.post("/jobs")
def start(body: JobBody):
    if body.type not in HANDLERS or body.type not in STARTABLE:
        raise HTTPException(400, f"Unknown job type {body.type!r}")
    try:
        params = clean_params(body.type, body.params)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": runner.submit(body.type, params)}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int):
    return {"ok": runner.cancel(job_id)}


@router.post("/jobs/{job_id}/resume")
def resume(job_id: int, session=Depends(get_session, scope="function")):
    row = session.get(Job, job_id)
    if row is None or row.status not in ("interrupted", "failed", "cancelled"):
        raise HTTPException(400, "Only interrupted, failed or cancelled jobs can be resumed")
    session.commit()
    return {"id": runner.submit(row.type, job_id=job_id)}


def _active_snapshot():
    recent = dt.datetime.now() - dt.timedelta(seconds=15)
    with session_scope() as s:
        rows = s.scalars(select(Job).where(or_(Job.status.in_(("queued", "running")), Job.finished_at >= recent))
                         .order_by(Job.id)).all()
        return [job_dict(j) for j in rows]


@router.get("/events")
async def events(request: Request):
    """Pushes the active and just-finished jobs whenever they change."""
    async def stream():
        last = None
        while not await request.is_disconnected():
            snapshot = json.dumps(jsonable_encoder(await asyncio.to_thread(_active_snapshot)))
            if snapshot != last:
                last = snapshot
                yield f"event: jobs\ndata: {snapshot}\n\n"
            else:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
