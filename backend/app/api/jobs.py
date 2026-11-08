"""Jobs: list, start, cancel, resume, and a live stream of progress (Server-Sent Events)."""
import asyncio
import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select

from ..db import session_scope
from ..jobs import HANDLERS, job_dict, runner
from ..models import Job
from . import get_session

router = APIRouter()


class JobBody(BaseModel):
    type: str
    params: dict = {}


@router.get("/jobs")
def jobs(type: str | None = None, limit: int = 100, session=Depends(get_session)):
    query = select(Job).order_by(Job.id.desc()).limit(limit)
    if type:
        query = query.where(Job.type == type)
    return [job_dict(j) for j in session.scalars(query).all()]


@router.get("/jobs/{job_id}")
def job(job_id: int, session=Depends(get_session)):
    row = session.get(Job, job_id)
    if row is None:
        raise HTTPException(404, "Job not found")
    return job_dict(row) | {"log": row.log}


@router.post("/jobs")
def start(body: JobBody):
    if body.type not in HANDLERS:
        raise HTTPException(400, f"Unknown job type {body.type!r}")
    return {"id": runner.submit(body.type, body.params)}


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int):
    return {"ok": runner.cancel(job_id)}


@router.post("/jobs/{job_id}/resume")
def resume(job_id: int, session=Depends(get_session)):
    row = session.get(Job, job_id)
    if row is None or row.status not in ("interrupted", "failed", "cancelled") or row.legacy_id:
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
