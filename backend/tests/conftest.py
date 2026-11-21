"""Every test gets its own library, Trash, download folder and database in a temp folder."""
import shutil
import subprocess

import pytest

from app import config, db


@pytest.fixture
def env(tmp_path, monkeypatch):
    root, trash, downloads = tmp_path / "DJ Tracks", tmp_path / "Trash", tmp_path / "Downloads"
    for folder in (root / "00 Inbox", root / "Genres" / "Synth-Pop & New Wave", root / "Genres" / "EBM & Industrial",
                   root / "Sessions" / "Party", trash, downloads):
        folder.mkdir(parents=True)
    monkeypatch.setenv("DJ_TRACKS_ROOT", str(root))
    monkeypatch.setenv("DJ_TRASH", str(trash))
    monkeypatch.setenv("DJ_SOURCES", str(downloads))
    monkeypatch.setenv("DJ_REKORDBOX_DIR", str(tmp_path / "rekordbox"))
    monkeypatch.setenv("DJ_HUB_DB", str(tmp_path / "test.db"))
    for key in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "LASTFM_API_KEY", "SOULSEEK_USERNAME", "SOULSEEK_PASSWORD"):   # never the real .env keys
        monkeypatch.delenv(key, raising=False)
    config.reload_config()
    db.reset_engine()
    db.migrate()
    config.get_config().settle_seconds = 0
    yield type("Env", (), {"root": root, "trash": trash, "downloads": downloads, "tmp": tmp_path,
                           "rekordbox": tmp_path / "rekordbox"})
    db.reset_engine()


def fake_audio(path, content=b"x"):
    """A file with an audio extension (enough for file moves; not decodable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3" + content * 1000)
    return path


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def real_audio(path, seconds=3, frequency=440, bitrate="320k", title=None, artist=None):
    """A real MP3 made with ffmpeg (the test is skipped when ffmpeg is missing)."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}",
           "-b:a", bitrate]
    if title:
        cmd += ["-metadata", f"title={title}"]
    if artist:
        cmd += ["-metadata", f"artist={artist}"]
    subprocess.run(cmd + [str(path)], check=True)
    return path


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, base_url="http://localhost") as c:
        yield c
