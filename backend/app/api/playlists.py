"""Spotify playlists, their match against the library, 'downloaded' ticks and the Spotify login."""
import html
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..config import get_config
from ..integrations import spotify
from ..jobs import runner
from ..models import Playlist
from ..services import playlists
from . import get_session

router = APIRouter()
_login_states = {}   # state -> time asked, oldest dropped first (a login must finish within minutes)
MAX_LOGIN_STATES = 20
LOGIN_STATE_SECONDS = 600


class PlaylistBody(BaseModel):
    value: str
    project: str = ""


class PlaylistPatch(BaseModel):
    project: str | None = None
    tracked: bool | None = None
    position: int | None = Field(None, ge=0)


class MarkBody(BaseModel):
    downloaded: bool


@router.get("/playlists")
def overview(session=Depends(get_session, scope="function")):
    return playlists.overview(session)


@router.get("/playlists/tracks")
def tracks(playlist: str | None = None, session=Depends(get_session, scope="function")):
    return playlists.tracks(session, playlist if playlist and playlist != "all" else None)


@router.post("/playlists")
def add(body: PlaylistBody, session=Depends(get_session, scope="function")):
    try:
        row = playlists.add_playlist(session, body.value, body.project)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    session.commit()
    return {"id": row.id, "job": runner.submit("spotify_refresh", {"ids": [row.id]})}


@router.patch("/playlists/{playlist_id}")
def patch(playlist_id: str, body: PlaylistPatch, session=Depends(get_session, scope="function")):
    row = session.get(Playlist, playlist_id)
    if row is None:
        raise HTTPException(404, "Playlist not found")
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(row, key, value)
    return {"ok": True}


@router.delete("/playlists/{playlist_id}")
def remove(playlist_id: str, session=Depends(get_session, scope="function")):
    row = session.get(Playlist, playlist_id)
    if row is None:
        raise HTTPException(404, "Playlist not found")
    session.delete(row)
    return {"ok": True}


@router.put("/playlists/marks/{spotify_id}")
def mark(spotify_id: str, body: MarkBody, session=Depends(get_session, scope="function")):
    playlists.set_mark(session, spotify_id, body.downloaded)
    return {"ok": True}


# --- Spotify login --------------------------------------------------------------------


@router.get("/spotify/status")
def spotify_status():
    client_id, client_secret = spotify.app_keys()
    return {"keys": bool(client_id and client_secret), "logged_in": spotify.has_login(),
            "permanent": spotify.has_permanent_login(),
            "redirect_uri": spotify.APP_REDIRECT_URI}


@router.get("/spotify/login")
def spotify_login():
    client_id, client_secret = spotify.app_keys()
    if not (client_id and client_secret):
        raise HTTPException(400, "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET before starting the app")
    state = secrets.token_urlsafe(16)
    _login_states[state] = time.monotonic()
    while len(_login_states) > MAX_LOGIN_STATES:
        _login_states.pop(next(iter(_login_states)))
    return RedirectResponse(spotify.authorize_url(client_id, state, spotify.APP_REDIRECT_URI))


@router.get("/spotify/callback")
def spotify_callback(state: str = "", code: str | None = None, error: str | None = None):
    asked = _login_states.pop(state, None)
    if asked is None or time.monotonic() - asked > LOGIN_STATE_SECONDS:
        raise HTTPException(404, "Unknown or expired login")
    if not code:
        return HTMLResponse(f"<p>Spotify login failed ({html.escape(str(error))}). You can close this tab.</p>", status_code=400)
    try:
        keep = spotify.exchange_code(code, spotify.APP_REDIRECT_URI)
    except (spotify.SpotifyLoginError, OSError, ValueError, KeyError) as exc:
        return HTMLResponse(f"<p>Spotify login failed ({type(exc).__name__}). You can close this tab.</p>",
                            status_code=400)
    back = get_config().frontend_url.rstrip("/") + "/settings?spotify=connected"
    # The login is only held in memory; the line below keeps it across restarts. It is shown here, in the
    # browser of the person who just logged in, and never written to a file or a log.
    return HTMLResponse(
        "<h1>Spotify is connected</h1>"
        "<p>It works until the app restarts. To keep it, add this line to <code>~/.zshrc</code> "
        "and restart the app:</p>"
        f"<pre>{html.escape(keep)}</pre>"
        f'<p><a href="{html.escape(back)}">Back to Settings</a></p>')
