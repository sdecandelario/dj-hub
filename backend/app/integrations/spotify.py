"""Read Spotify playlists.

With SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET and a saved login, the Web API reads
full playlists. Otherwise the public embed page is used (first 100 tracks only).
The login is saved next to the database (readable only by the user) and is never printed.
"""
import base64
import http.server
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from ..config import get_config

SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"   # terminal login (djhub spotify-login)
APP_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/api/spotify/callback")
SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative"
LOGIN_TIMEOUT_SECONDS = 300
MAX_RETRY_WAIT_SECONDS = 30
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DJHub/1.0"


def warn(message):
    print(f"  {message}", file=sys.stderr)


def parse_playlist_id(value):
    value = value.strip()
    match = re.search(r"playlist[/:]([A-Za-z0-9]{22})", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{22}", value):
        return value
    raise ValueError(f"Not a Spotify playlist ID or URL: {value!r}")


def http_get(url, headers=None, data=None):
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def fetch_playlist_embed(playlist_id):
    """Read a public playlist from the Spotify embed page. No credentials needed,
    but Spotify only includes the first 100 tracks."""
    html = http_get(f"https://open.spotify.com/embed/playlist/{playlist_id}")
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not match:
        raise RuntimeError("Spotify embed page has an unexpected format")
    entity = json.loads(match.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    covers = (entity.get("coverArt") or {}).get("sources") or []
    tracks = []
    for item in entity.get("trackList", []):
        uri = item.get("uri", "")
        if not uri.startswith("spotify:track:"):
            continue
        tracks.append({
            "spotify_id": uri.rsplit(":", 1)[-1],
            "title": item.get("title", ""),
            "artists": [a.strip() for a in item.get("subtitle", "").split(",") if a.strip()],
            "duration_ms": item.get("duration"),
        })
    return {
        "id": playlist_id,
        "name": entity.get("name") or entity.get("title") or playlist_id,
        "owner": entity.get("subtitle", ""),
        "cover": max(covers, key=lambda c: c.get("width") or 0)["url"] if covers else None,
        "source": "embed",
        "possibly_truncated": len(tracks) >= 100,
        "tracks": tracks,
    }


class SpotifyLoginError(RuntimeError):
    """The Spotify user login could not be completed."""


def app_keys():
    return os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")


def _request_token(client_id, client_secret, fields):
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = http_get(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data=urllib.parse.urlencode(fields).encode(),
    )
    return json.loads(body)


def _oauth_error(error):
    """Return the OAuth error code (such as "invalid_grant") from an HTTPError, if any."""
    try:
        return json.loads(error.read().decode("utf-8")).get("error")
    except (ValueError, AttributeError, OSError):
        return None


def _read_refresh_token():
    """Return the saved refresh token, or None if the file is missing or damaged."""
    try:
        data = json.loads(token_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        warn("Saved Spotify login is damaged; logging in again")
        return None
    token = data.get("refresh_token") if isinstance(data, dict) else None
    return token if isinstance(token, str) and token else None


def token_path():
    """Where the login is kept: with the rest of the app's data, next to the database."""
    return get_config().db_path.parent / "spotify_token.json"


def has_saved_login():
    return _read_refresh_token() is not None


def _save_refresh_token(refresh_token):
    """Write the token file atomically, readable only by the current user."""
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"refresh_token": refresh_token}, handle)
    os.replace(tmp_path, path)


def authorize_url(client_id, state, redirect_uri):
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SPOTIFY_SCOPES,
        "state": state,
    })


def exchange_code(code, redirect_uri):
    """Finish the in-app login: trade the code for tokens and save the refresh token."""
    client_id, client_secret = app_keys()
    if not (client_id and client_secret):
        raise SpotifyLoginError("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are not set")
    data = _request_token(client_id, client_secret, {
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})
    _save_refresh_token(data["refresh_token"])
    return data["access_token"]


def _login_in_browser(client_id, client_secret):
    """Terminal login: ask the user to approve access in the browser and catch the redirect locally."""
    state = secrets.token_urlsafe(16)
    redirect = urllib.parse.urlparse(SPOTIFY_REDIRECT_URI)
    result = {}

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path != redirect.path or query.get("state", [""])[0] != state:
                self.send_response(404)
                self.end_headers()
                return
            result["code"] = query.get("code", [None])[0]
            result["error"] = query.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            message = "Spotify login complete. You can close this tab." if result["code"] else "Spotify login failed."
            self.wfile.write(message.encode())

        def log_message(self, *args):
            pass

    auth_url = authorize_url(client_id, state, SPOTIFY_REDIRECT_URI)
    try:
        server = http.server.HTTPServer((redirect.hostname, redirect.port), CallbackHandler)
    except OSError as error:
        raise SpotifyLoginError(f"cannot listen on {redirect.hostname}:{redirect.port} ({error.strerror})") from error
    with server:
        server.timeout = 1  # handle_request() returns every second so the deadline is checked.
        print("Opening the browser to log in to Spotify. If it does not open, visit:")
        print(f"  {auth_url}")
        print(f"Waiting up to {LOGIN_TIMEOUT_SECONDS // 60} minutes for approval ...")
        webbrowser.open(auth_url)
        deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
        while "code" not in result:
            if time.monotonic() > deadline:
                raise SpotifyLoginError("timed out waiting for approval in the browser")
            server.handle_request()
    if not result["code"]:
        raise SpotifyLoginError(f"access was not approved ({result['error']})")
    return _request_token(client_id, client_secret, {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": SPOTIFY_REDIRECT_URI,
    })


def spotify_token(interactive=None):
    """Return a user access token, or None when no app keys are set.

    Reuses the saved refresh token. A browser login only happens in an interactive
    terminal; the web app uses its own login page instead."""
    client_id, client_secret = app_keys()
    if not (client_id and client_secret):
        return None
    if interactive is None:
        interactive = sys.stdin.isatty()
    refresh_token = _read_refresh_token()
    if refresh_token:
        try:
            data = _request_token(client_id, client_secret,
                                  {"grant_type": "refresh_token", "refresh_token": refresh_token})
            _save_refresh_token(data.get("refresh_token") or refresh_token)
            return data["access_token"]
        except urllib.error.HTTPError as error:
            reason = _oauth_error(error)
            if reason != "invalid_grant":
                raise SpotifyLoginError(
                    f"Spotify refused the saved login ({error.code} {reason or error.reason})") from error
            warn("Saved Spotify login was revoked or expired; logging in again")
    if not interactive:
        raise SpotifyLoginError("a Spotify login is needed: use Connect Spotify in Settings")
    data = _login_in_browser(client_id, client_secret)
    _save_refresh_token(data["refresh_token"])
    return data["access_token"]


def api_get(url, headers):
    """GET a Spotify API URL, waiting once if Spotify asks to slow down (429)."""
    try:
        return http_get(url, headers)
    except urllib.error.HTTPError as error:
        if error.code != 429:
            raise
        try:
            wait = int(error.headers.get("Retry-After", "5"))
        except ValueError:
            wait = 5
        time.sleep(min(max(wait, 1), MAX_RETRY_WAIT_SECONDS))
        return http_get(url, headers)


def fetch_playlist_api(playlist_id, token):
    """Read a full playlist through the Spotify Web API (user login)."""
    headers = {"Authorization": f"Bearer {token}"}
    meta = json.loads(api_get(
        f"https://api.spotify.com/v1/playlists/{playlist_id}?fields=name,owner(display_name),images", headers))
    tracks = []
    for path in ("items", "tracks"):  # Spotify renamed /tracks to /items; support both.
        try:
            page = json.loads(api_get(f"https://api.spotify.com/v1/playlists/{playlist_id}/{path}?limit=100",
                                      headers))
            break
        except urllib.error.HTTPError as error:
            if error.code != 404 or path == "tracks":
                raise
    while True:
        for entry in page.get("items", []):
            track = (entry or {}).get("item") or (entry or {}).get("track")
            if not track or track.get("type") != "track" or not track.get("id"):
                continue
            tracks.append({
                "spotify_id": track["id"],
                "title": track.get("name", ""),
                "artists": [a["name"] for a in track.get("artists", [])],
                "duration_ms": track.get("duration_ms"),
            })
        if not page.get("next"):
            break
        page = json.loads(api_get(page["next"], headers))
    images = meta.get("images") or []
    return {
        "id": playlist_id,
        "name": meta.get("name") or playlist_id,
        "owner": (meta.get("owner") or {}).get("display_name", ""),
        "cover": images[0]["url"] if images else None,
        "source": "api",
        "possibly_truncated": False,
        "tracks": tracks,
    }


def fetch_playlist(playlist_id, token):
    if token:
        try:
            return fetch_playlist_api(playlist_id, token)
        except urllib.error.HTTPError as error:
            warn(f"Spotify API failed ({error.code}); falling back to the embed page")
        except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
            warn(f"Spotify API failed ({error}); falling back to the embed page")
    return fetch_playlist_embed(playlist_id)
