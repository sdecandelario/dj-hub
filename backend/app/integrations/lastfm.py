"""Last.fm client: similar artists and top tracks (the candidate source for discovery).

The API key comes from LASTFM_API_KEY (the project's .env file) and is never printed.
`fetch` is injectable so tests never touch the network.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API_URL = "https://ws.audioscrobbler.com/2.0/"
USER_AGENT = "DJHub/1.0"


class LastfmError(RuntimeError):
    pass


def api_key():
    key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not key:
        raise LastfmError("LASTFM_API_KEY is not set in .env. Create a free key at https://www.last.fm/api/account/create")
    return key


RETRY_CODES = (429, 500, 502, 503, 504)   # Last.fm throttles bursts and has short outages
RETRIES = 3


def http_fetch(params):
    url = API_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in RETRY_CODES and attempt < RETRIES:
                time.sleep(2 ** attempt)
                continue
            raise LastfmError(f"Last.fm request failed (HTTP {error.code})") from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            # Not `from error`: its text can carry the request URL, which contains the API key.
            raise LastfmError(f"Last.fm request failed ({type(error).__name__})") from None


def _as_list(value):
    """Last.fm returns a single result as an object instead of a one-item list."""
    return [] if not value else value if isinstance(value, list) else [value]


class Lastfm:
    def __init__(self, key=None, fetch=None):
        self.key = key or api_key()
        self.fetch = fetch or http_fetch

    def _call(self, method, **params):
        data = self.fetch({"method": method, "api_key": self.key, "format": "json", **params})
        if "error" in data:
            raise LastfmError(data.get("message", f"Last.fm error {data['error']}"))
        return data

    def similar_artists(self, artist, limit=30):
        """[(name, match 0..1)] for artists similar to `artist`."""
        data = self._call("artist.getsimilar", artist=artist, limit=limit, autocorrect=1)
        return [(a["name"], float(a.get("match", 0))) for a in _as_list(data.get("similarartists", {}).get("artist"))]

    def top_tracks(self, artist, limit=10):
        """[title] for the artist's most played tracks."""
        data = self._call("artist.gettoptracks", artist=artist, limit=limit, autocorrect=1)
        return [t["name"] for t in _as_list(data.get("toptracks", {}).get("track"))]
