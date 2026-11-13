"""Paths and settings, read from environment variables.

DJ_TRACKS_ROOT  library root (default ~/Documents/DJ Tracks)
DJ_TRASH        where removed files go (default ~/.Trash)
DJ_SOURCES      download folders, ':'-separated (default Nicotine downloads and ~/Downloads)
DJ_HUB_DB       SQLite file (default ~/.local/share/dj-hub/dj-hub.db)
DJ_HUB_FRONTEND where to send the browser after the Spotify login (default http://127.0.0.1:8000)
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SOURCES = "~/.local/share/nicotine/downloads:~/Downloads"


def _path(value):
    return Path(value).expanduser()


@dataclass
class Config:
    root: Path = field(default_factory=lambda: _path(os.environ.get("DJ_TRACKS_ROOT", "~/Documents/DJ Tracks")))
    trash: Path = field(default_factory=lambda: _path(os.environ.get("DJ_TRASH", "~/.Trash")))
    sources: list = field(default_factory=lambda: [
        _path(p) for p in os.environ.get("DJ_SOURCES", DEFAULT_SOURCES).split(":") if p])
    db_path: Path = field(default_factory=lambda: _path(
        os.environ.get("DJ_HUB_DB", "~/.local/share/dj-hub/dj-hub.db")))
    frontend_url: str = field(default_factory=lambda: os.environ.get("DJ_HUB_FRONTEND", "http://127.0.0.1:8000"))
    settle_seconds: int = 0
    workers: int = field(default_factory=lambda: max(1, min(4, (os.cpu_count() or 2) // 2)))


_config = None


def get_config():
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config():
    """Re-read the environment (used by tests)."""
    global _config
    _config = Config()
    return _config
