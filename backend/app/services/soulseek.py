"""Download the versions of songs from Soulseek into the download folder (the review picks the best one)."""
from pathlib import Path

from ..config import get_config
from ..core import soulseek as rules
from ..core.library import GENRES
from ..db import session_scope
from ..integrations import soulseek
from ..jobs import handler
from ..models import Job
from . import settings


def download(queries, echo=print, progress=lambda songs: None, cancelled=lambda: False, skipped=lambda: ()):
    """Search every query in one Soulseek session and download the best candidates of each.
    Returns {"songs": {query: {"found", "files"}}, "folder"}."""
    with session_scope() as s:
        rule, folder = settings.soulseek(s), settings.soulseek_folder(s)
    pick = lambda query, results: rules.choose(results, query, rule["min_bitrate"], rule["candidates"])
    genres = get_config().root / GENRES   # the sorted library; Inbox, Rejected and Sessions (copies) stay private
    songs = soulseek.fetch(queries, pick, folder, share=[genres] if genres.is_dir() else [], echo=echo,
                           progress=progress, cancelled=cancelled, skipped=skipped)
    return {"songs": songs, "folder": str(folder)}


def _already_downloaded(job_id):
    """Songs of an earlier run of this job (before a resume) that have a finished file still on disk."""
    with session_scope() as s:
        job = s.get(Job, job_id)
        songs = (job.summary or {}).get("songs", {}) if job else {}
    kept = {}
    for query, song in songs.items():
        files = [f for f in song["files"] if f.get("done") and f.get("local_path") and Path(f["local_path"]).exists()]
        if files:
            kept[query] = {**song, "files": files}
    return kept


@handler("soulseek_download")
def run_download(ctx):
    """params: {"queries": ["Artist Title", ...]}. Downloads into <download folder>/Soulseek; no library file changes.
    A resumed job only searches the songs that have nothing downloaded yet."""
    queries = ctx.params.get("queries") or []
    if not queries:
        raise ValueError("Give the artist and title to search")
    kept = _already_downloaded(ctx.job_id)
    todo = [q for q in queries if q not in kept]
    songs = {q: kept[q] for q in queries if q in kept}
    ctx.set_summary(songs=songs)
    if todo:
        ctx.progress(message=f"Searching Soulseek for {len(todo)} song(s)")
        try:
            result = download(todo, echo=lambda m: ctx.progress(message=m),
                              progress=lambda live: ctx.set_summary(songs={**songs, **live}),
                              cancelled=ctx.cancelled, skipped=lambda: list(ctx.skipped))
        except soulseek.SoulseekError as exc:
            raise ValueError(str(exc))
        ctx.check()
        songs |= result["songs"]
        folder = result["folder"]
    else:
        with session_scope() as s:
            folder = str(settings.soulseek_folder(s))
    files = [f for song in songs.values() for f in song["files"]]
    nothing = [q for q in queries if not songs.get(q, {}).get("files")]
    note = f". Nothing could be downloaded right now: {', '.join(nothing)}" if nothing else ""
    return {"message": f"{len(files)} file(s) downloaded to {folder}{note}", "songs": songs, "folder": folder}
