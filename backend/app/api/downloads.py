"""Downloads review: the latest review, your decisions, and the move to Inbox/Rejected."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..jobs import runner
from ..services import downloads, library
from . import get_session

router = APIRouter()


class DecisionBody(BaseModel):
    choice: Literal["keep", "reject", "later", "clear"]
    keep_path: str | None = None


class ApplyBody(BaseModel):
    song_keys: list[str] | None = None


@router.get("/downloads")
def review(session=Depends(get_session, scope="function")):
    return downloads.review_view(session)


@router.post("/downloads/review")
def start_review():
    return {"id": runner.submit("review_downloads")}


@router.put("/downloads/decisions/{song_key}")
def decide(song_key: str, body: DecisionBody, session=Depends(get_session, scope="function")):
    try:
        downloads.decide(session, song_key, body.choice, body.keep_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@router.post("/downloads/preview")
def preview(body: ApplyBody, session=Depends(get_session, scope="function")):
    try:
        batch = downloads.preview_intake(session, body.song_keys)
    except library.BatchError as exc:
        raise HTTPException(400, str(exc))
    return library.batch_dict(session, batch)
