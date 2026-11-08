"""Spotify playlists, their match against the library, 'downloaded' ticks and the Spotify login."""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from ..config import get_config
from ..core import spotify
from ..jobs import runner
from ..models import Playlist
from ..services import playlists
from . import get_session

router = APIRouter()
_login_states = set()


class PlaylistBody(BaseModel):
    value: str
    project: str = ""


class PlaylistPatch(BaseModel):
    project: str | None = None
    tracked: bool | None = None
    position: int | None = None


class MarkBody(BaseModel):
    downloaded: bool


@router.get("/playlists")
def overview(session=Depends(get_session)):
    return playlists.overview(session)


@router.get("/playlists/tracks")
def tracks(playlist: str | None = None, session=Depends(get_session)):
    return playlists.tracks(session, playlist if playlist and playlist != "all" else None)


@router.post("/playlists")
def add(body: PlaylistBody, session=Depends(get_session)):
    try:
        row = playlists.add_playlist(session, body.value, body.project)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    session.commit()
    return {"id": row.id, "job": runner.submit("spotify_refresh", {"ids": [row.id]})}


@router.patch("/playlists/{playlist_id}")
def patch(playlist_id: str, body: PlaylistPatch, session=Depends(get_session)):
    row = session.get(Playlist, playlist_id)
    if row is None:
        raise HTTPException(404, "Playlist not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    return {"ok": True}


@router.delete("/playlists/{playlist_id}")
def remove(playlist_id: str, session=Depends(get_session)):
    row = session.get(Playlist, playlist_id)
    if row is not None:
        session.delete(row)
    return {"ok": True}


@router.post("/playlists/refresh")
def refresh():
    return {"id": runner.submit("spotify_refresh")}


@router.put("/playlists/marks/{spotify_id}")
def mark(spotify_id: str, body: MarkBody, session=Depends(get_session)):
    playlists.set_mark(session, spotify_id, body.downloaded)
    return {"ok": True}


# --- Spotify login --------------------------------------------------------------------


@router.get("/spotify/status")
def spotify_status():
    client_id, client_secret = spotify.app_keys()
    return {"keys": bool(client_id and client_secret), "logged_in": spotify.has_saved_login(),
            "redirect_uri": spotify.APP_REDIRECT_URI}


@router.get("/spotify/login")
def spotify_login():
    client_id, client_secret = spotify.app_keys()
    if not (client_id and client_secret):
        raise HTTPException(400, "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET before starting the app")
    state = secrets.token_urlsafe(16)
    _login_states.add(state)
    return RedirectResponse(spotify.authorize_url(client_id, state, spotify.APP_REDIRECT_URI))


@router.get("/spotify/callback")
def spotify_callback(state: str = "", code: str | None = None, error: str | None = None):
    if state not in _login_states:
        raise HTTPException(404, "Unknown login")
    _login_states.discard(state)
    if not code:
        return HTMLResponse(f"<p>Spotify login failed ({error}). You can close this tab.</p>", status_code=400)
    try:
        spotify.exchange_code(code, spotify.APP_REDIRECT_URI)
    except (spotify.SpotifyLoginError, OSError, ValueError, KeyError) as exc:
        return HTMLResponse(f"<p>Spotify login failed ({type(exc).__name__}). You can close this tab.</p>",
                            status_code=400)
    return RedirectResponse(get_config().frontend_url.rstrip("/") + "/settings?spotify=connected")
