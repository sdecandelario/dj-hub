import io
import json
import os
import socket
import stat
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

import app.core.spotify as c


def http_error(code, body=None, headers=None):
    payload = io.BytesIO(json.dumps(body or {}).encode())
    return urllib.error.HTTPError("https://example.test", code, "error", headers or {}, payload)


def api_track(track_id, name, key="item", kind="track"):
    return {key: {"id": track_id, "name": name, "type": kind, "artists": [{"name": "Artist"}], "duration_ms": 1000}}


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        token_path = Path(self.tmp.name) / "sub" / "spotify_token.json"
        for patcher in (
            mock.patch.object(c, "TOKEN_PATH", token_path),
            mock.patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "id", "SPOTIFY_CLIENT_SECRET": "secret"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.token_path = token_path

    def save(self, text):
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(text, encoding="utf-8")

    def test_no_keys_returns_none(self):
        with mock.patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "", "SPOTIFY_CLIENT_SECRET": ""}):
            self.assertIsNone(c.spotify_token())

    def test_refresh_saves_rotated_token_with_private_mode(self):
        self.save(json.dumps({"refresh_token": "old"}))
        with mock.patch.object(c, "_request_token", return_value={"access_token": "A", "refresh_token": "new"}) as req:
            self.assertEqual(c.spotify_token(interactive=False), "A")
        self.assertEqual(req.call_args[0][2]["refresh_token"], "old")
        self.assertEqual(json.loads(self.token_path.read_text())["refresh_token"], "new")
        self.assertEqual(stat.S_IMODE(self.token_path.stat().st_mode), 0o600)
        self.assertFalse(self.token_path.with_name(self.token_path.name + ".tmp").exists())

    def test_refresh_keeps_token_when_not_rotated(self):
        self.save(json.dumps({"refresh_token": "old"}))
        with mock.patch.object(c, "_request_token", return_value={"access_token": "A"}):
            c.spotify_token(interactive=False)
        self.assertEqual(json.loads(self.token_path.read_text())["refresh_token"], "old")

    def test_damaged_or_missing_token_logs_in_again(self):
        for text in ("{not json", json.dumps({"other": 1}), json.dumps(["x"]), None):
            with self.subTest(text=text):
                if text is None:
                    self.token_path.unlink(missing_ok=True)
                else:
                    self.save(text)
                with mock.patch.object(c, "_request_token") as req, \
                        mock.patch.object(c, "_login_in_browser", return_value={"access_token": "B", "refresh_token": "R"}), \
                        mock.patch("sys.stderr", io.StringIO()):
                    self.assertEqual(c.spotify_token(interactive=True), "B")
                req.assert_not_called()
                self.assertEqual(json.loads(self.token_path.read_text())["refresh_token"], "R")

    def test_revoked_token_logs_in_again(self):
        self.save(json.dumps({"refresh_token": "old"}))
        with mock.patch.object(c, "_request_token", side_effect=http_error(400, {"error": "invalid_grant"})), \
                mock.patch.object(c, "_login_in_browser", return_value={"access_token": "B", "refresh_token": "R"}) as login, \
                mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(c.spotify_token(interactive=True), "B")
        login.assert_called_once()

    def test_other_refresh_errors_do_not_open_browser(self):
        self.save(json.dumps({"refresh_token": "old"}))
        for error in (http_error(400, {"error": "invalid_client"}), http_error(500), http_error(429)):
            with self.subTest(code=error.code), \
                    mock.patch.object(c, "_request_token", side_effect=error), \
                    mock.patch.object(c, "_login_in_browser") as login:
                with self.assertRaises(c.SpotifyLoginError):
                    c.spotify_token(interactive=True)
                login.assert_not_called()

    def test_non_interactive_never_opens_browser(self):
        with mock.patch.object(c, "_login_in_browser") as login:
            with self.assertRaises(c.SpotifyLoginError):
                c.spotify_token(interactive=False)
        login.assert_not_called()


class BrowserLoginTest(unittest.TestCase):
    def run_login(self, request_path=None):
        """Run _login_in_browser on a free port; optionally hit the callback with request_path."""
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        uri = f"http://127.0.0.1:{port}/callback"

        def fake_open(auth_url):
            if request_path is None:
                return
            state = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)["state"][0]

            def hit():
                for path in request_path(state):
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5).read()
                    except urllib.error.HTTPError as error:
                        self.statuses.append(error.code)
                    else:
                        self.statuses.append(200)
            self.thread = threading.Thread(target=hit, daemon=True)
            self.thread.start()

        self.statuses = []
        self.thread = None
        with mock.patch.object(c, "SPOTIFY_REDIRECT_URI", uri), \
                mock.patch.object(c.webbrowser, "open", side_effect=fake_open), \
                mock.patch.object(c, "_request_token", return_value={"access_token": "A", "refresh_token": "R"}), \
                mock.patch("sys.stdout", io.StringIO()):
            try:
                return c._login_in_browser("id", "secret")
            finally:
                if self.thread:
                    self.thread.join(5)

    def test_wrong_state_is_rejected_then_right_state_works(self):
        result = self.run_login(lambda state: ["/callback?code=X&state=wrong", f"/callback?code=X&state={state}"])
        self.assertEqual(result["access_token"], "A")
        self.assertEqual(self.statuses, [404, 200])

    def test_denied_access_raises(self):
        with self.assertRaises(c.SpotifyLoginError):
            self.run_login(lambda state: [f"/callback?error=access_denied&state={state}"])

    def test_timeout_raises(self):
        with mock.patch.object(c, "LOGIN_TIMEOUT_SECONDS", 0):
            with self.assertRaises(c.SpotifyLoginError):
                self.run_login()

    def test_port_in_use_raises(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            port = sock.getsockname()[1]
            with mock.patch.object(c, "SPOTIFY_REDIRECT_URI", f"http://127.0.0.1:{port}/callback"), \
                    mock.patch.object(c.webbrowser, "open") as browser:
                with self.assertRaises(c.SpotifyLoginError):
                    c._login_in_browser("id", "secret")
            browser.assert_not_called()


class FetchPlaylistTest(unittest.TestCase):
    META = json.dumps({"name": "List", "owner": {"display_name": "me"}, "images": []})

    def fake_get(self, responses):
        def get(url, headers=None, data=None):
            for prefix, response in responses:
                if url.startswith(prefix):
                    if isinstance(response, Exception):
                        raise response
                    return response
            raise AssertionError(f"unexpected URL {url}")
        return get

    def test_pagination_keys_and_skipped_entries(self):
        base = "https://api.spotify.com/v1/playlists/P"
        page1 = {"items": [api_track("1", "One"), api_track("2", "Two", key="track"), None,
                           api_track("3", "Episode", kind="episode"), {"item": {"type": "track", "id": None}}],
                 "next": "https://api.spotify.com/next"}
        page2 = {"items": [api_track("4", "Four")], "next": None}
        responses = [(f"{base}?", self.META), (f"{base}/items", json.dumps(page1)),
                     ("https://api.spotify.com/next", json.dumps(page2))]
        with mock.patch.object(c, "http_get", side_effect=self.fake_get(responses)):
            playlist = c.fetch_playlist_api("P", "T")
        self.assertEqual([t["spotify_id"] for t in playlist["tracks"]], ["1", "2", "4"])
        self.assertEqual(playlist["source"], "api")

    def test_items_404_falls_back_to_tracks_endpoint(self):
        base = "https://api.spotify.com/v1/playlists/P"
        responses = [(f"{base}?", self.META), (f"{base}/items", http_error(404)),
                     (f"{base}/tracks", json.dumps({"items": [api_track("1", "One")], "next": None}))]
        with mock.patch.object(c, "http_get", side_effect=self.fake_get(responses)):
            self.assertEqual(len(c.fetch_playlist_api("P", "T")["tracks"]), 1)

    def test_429_waits_and_retries_once(self):
        calls = []

        def get(url, headers=None, data=None):
            calls.append(url)
            if len(calls) == 1:
                raise http_error(429, headers={"Retry-After": "2"})
            return "ok"
        with mock.patch.object(c, "http_get", side_effect=get), mock.patch.object(c.time, "sleep") as sleep:
            self.assertEqual(c.api_get("https://api.spotify.com/x", {}), "ok")
        sleep.assert_called_once_with(2)
        self.assertEqual(len(calls), 2)

    def test_api_errors_fall_back_to_embed(self):
        for error in (http_error(401), http_error(403), urllib.error.URLError("offline"), TimeoutError("slow")):
            with self.subTest(error=error), \
                    mock.patch.object(c, "fetch_playlist_api", side_effect=error), \
                    mock.patch.object(c, "fetch_playlist_embed", return_value={"source": "embed"}) as embed, \
                    mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(c.fetch_playlist("P", "T")["source"], "embed")
                embed.assert_called_once_with("P")

    def test_no_token_uses_embed(self):
        with mock.patch.object(c, "fetch_playlist_api") as api, \
                mock.patch.object(c, "fetch_playlist_embed", return_value={"source": "embed"}):
            self.assertEqual(c.fetch_playlist("P", None)["source"], "embed")
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
