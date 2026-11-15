"""Rekordbox export logs: tracks it could not find, and where their files are now (read only)."""
from fastapi import APIRouter, Depends

from ..services import rekordbox
from . import get_session

router = APIRouter()


@router.get("/rekordbox")
def review(session=Depends(get_session)):
    return rekordbox.review(session)
