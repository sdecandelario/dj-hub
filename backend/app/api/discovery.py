"""New-song candidates found by discovery: list them and mark wanted / dismissed."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..services import discovery
from . import get_session

router = APIRouter()


class StatusBody(BaseModel):
    ids: list[int]
    status: str


@router.get("/candidates/genres")
def genres(session=Depends(get_session)):
    return discovery.genre_names(session)


@router.get("/candidates")
def candidates(status: str | None = None, genre: str | None = None, session=Depends(get_session)):
    return discovery.list_candidates(session, status=status, genre=genre)


@router.put("/candidates/status")
def set_status(body: StatusBody, session=Depends(get_session)):
    try:
        rows = discovery.set_status(session, body.ids, body.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0]))
    return {"changed": len(rows)}
