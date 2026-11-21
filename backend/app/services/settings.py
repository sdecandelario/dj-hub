"""Stored settings. Environment variables win over stored values."""
import os
from pathlib import Path

from ..config import DEFAULT_SOURCES, get_config
from ..models import Setting


def get(session, key, default=None):
    row = session.get(Setting, key)
    return default if row is None else row.value


def put(session, key, value):
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()


def sources(session):
    """Download folders: DJ_SOURCES if set, else the stored list, else the defaults."""
    if os.environ.get("DJ_SOURCES"):
        return list(get_config().sources)
    stored = get(session, "sources")
    if stored:
        return [Path(p).expanduser() for p in stored]
    return [Path(p).expanduser() for p in DEFAULT_SOURCES.split(":")]


def sources_locked():
    return bool(os.environ.get("DJ_SOURCES"))


SOULSEEK_DEFAULTS = {"min_bitrate": 320, "candidates": 10}   # only MP3 files are ever searched


def soulseek(session):
    """Soulseek search rules: minimum MP3 bitrate (kbps) and how many versions of a song to download."""
    return {k: get(session, f"soulseek_{k}", v) for k, v in SOULSEEK_DEFAULTS.items()}


def soulseek_folder(session):
    """Where Soulseek downloads land: inside the first download folder, so the review finds them."""
    return sources(session)[0] / "Soulseek"
