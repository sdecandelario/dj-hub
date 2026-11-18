"""Picking Soulseek search results to download (pure logic: no network, no database)."""
from dataclasses import dataclass

from .matching import normalize

# A result is a different version of the song unless the query asks for it.
UNWANTED_WORDS = {"remix", "live", "karaoke", "cover", "instrumental", "acapella", "tribute", "demo", "mashup"}


@dataclass(frozen=True)
class Result:
    username: str
    path: str            # as the peer shares it, with backslashes
    size: int
    bitrate: int | None
    free_slots: bool
    queue_size: int
    speed: int

    @property
    def filename(self):
        return self.path.replace("\\", "/").rsplit("/", 1)[-1]


def _words(text):
    return set(normalize(text).split())


def is_wanted(result, query, min_bitrate):
    """MP3 at `min_bitrate` or better, whose path holds every word of the query and none of the
    UNWANTED_WORDS (unless the query itself has it)."""
    if not result.filename.lower().endswith(".mp3") or (result.bitrate or 0) < min_bitrate:
        return False
    words, wanted = _words(result.path), _words(query)
    return wanted <= words and not (UNWANTED_WORDS & (words - wanted))


def choose(results, query, min_bitrate, count):
    """Up to `count` results, one per peer: free slots first, then shortest queue, then fastest."""
    ranked = sorted((r for r in results if is_wanted(r, query, min_bitrate)),
                    key=lambda r: (not r.free_slots, r.queue_size, -r.speed))
    seen, picked = set(), []
    for r in ranked:
        if r.username not in seen:
            seen.add(r.username)
            picked.append(r)
    return picked[:count]
