"""Download the versions of a song from Soulseek into the download folder (the review picks the best one)."""
from ..config import get_config
from ..core import soulseek as rules
from ..core.library import GENRES
from ..db import session_scope
from ..integrations import soulseek
from ..jobs import handler
from . import settings


def download(query, echo=print, progress=lambda files: None):
    """Search `query` and download the best candidates. Returns the integration's result plus the rules used."""
    with session_scope() as s:
        rule, folder = settings.soulseek(s), settings.soulseek_folder(s)
    pick = lambda results: rules.choose(results, query, rule["min_bitrate"], rule["candidates"])
    genres = get_config().root / GENRES   # the sorted library; Inbox, Rejected and Sessions (copies) stay private
    result = soulseek.fetch(query, pick, folder, share=[genres] if genres.is_dir() else [], echo=echo, progress=progress)
    result["folder"] = str(folder)
    return result


@handler("soulseek_download")
def run_download(ctx):
    """params: {"query": "Artist Title"}. Downloads into <download folder>/Soulseek; no library file changes."""
    query = (ctx.params.get("query") or "").strip()
    if not query:
        raise ValueError("Give the artist and title to search")
    try:
        result = download(query, echo=lambda m: ctx.progress(message=m),
                          progress=lambda files: ctx.set_summary(files=files))
    except soulseek.SoulseekError as exc:
        raise ValueError(str(exc))
    done = sum(f["done"] for f in result["files"])
    return {"message": f"{done} of {len(result['files'])} file(s) downloaded to {result['folder']}",
            "found": result["found"], "files": result["files"], "folder": result["folder"]}
