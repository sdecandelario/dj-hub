"""Soulseek client (aioslsk): search for a song and download the chosen results.

It connects only while a call runs, so it is slower to get queue slots than an always-on client.
The login comes from SOULSEEK_USERNAME and SOULSEEK_PASSWORD (the project's .env file) and is never
printed. The folders in `share` are shared (read-only) while it is connected.
"""
import asyncio
import logging
import os
from pathlib import Path

from aioslsk.client import SoulSeekClient
from aioslsk.exceptions import AioSlskException
from aioslsk.protocol.primitives import AttributeKey
from aioslsk.settings import CredentialsSettings, Settings, SharedDirectorySettingEntry
from aioslsk.transfer.state import TransferState

from ..core.soulseek import Result


# Peers that cannot be reached are normal on Soulseek and fill the terminal with warnings.
logging.getLogger("aioslsk").setLevel(logging.CRITICAL)


class SoulseekError(RuntimeError):
    pass


def credentials():
    user = os.environ.get("SOULSEEK_USERNAME", "").strip()
    password = os.environ.get("SOULSEEK_PASSWORD", "")
    if not user or not password:
        raise SoulseekError("SOULSEEK_USERNAME and SOULSEEK_PASSWORD are not set in .env. "
                            "Logging in with a new username creates the account.")
    return CredentialsSettings(username=user, password=password)


def _results(request):
    found = []
    for peer in request.results:
        for f in peer.shared_items:
            found.append(Result(peer.username, f.filename, f.filesize,
                                f.get_attribute_map().get(AttributeKey.BITRATE),
                                peer.has_free_slots, peer.queue_size, peer.avg_speed))
    return found


def _snapshot(result, transfer):
    done = transfer.state.VALUE == TransferState.COMPLETE
    return {"username": result.username, "path": result.path, "size": result.size,
            "bytes": transfer.bytes_transfered, "speed": round(transfer.get_speed()),
            "done": done, "local_path": transfer.local_path if done else None,
            "state": transfer.state.VALUE.name.lower()}


async def _fetch(query, pick, dest, share, search_wait, timeout, echo, progress):
    settings = Settings(credentials=credentials())
    settings.shares.download = str(dest)
    settings.shares.directories = [SharedDirectorySettingEntry(path=str(p)) for p in share]
    async with SoulSeekClient(settings) as client:
        try:
            await client.login()
        except AioSlskException as error:
            raise SoulseekError(f"Soulseek login failed: {error}") from None
        echo(f"Searching Soulseek for '{query}' ({search_wait}s)")
        request = await client.searches.search(query)
        await asyncio.sleep(search_wait)
        results = _results(request)
        chosen = pick(results)
        echo(f"{len(results)} files found, {len(chosen)} chosen")
        transfers = [(r, await client.transfers.download(r.username, r.path)) for r in chosen]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline and not all(t.is_finalized() for _, t in transfers):
            progress([_snapshot(r, t) for r, t in transfers])
            await asyncio.sleep(2)
        for _, transfer in transfers:
            if not transfer.is_finalized():
                await client.transfers.abort(transfer)   # also removes the partial file
        out = [_snapshot(r, t) for r, t in transfers]
        return {"found": len(results), "files": out}


def fetch(query, pick, dest, share=(), search_wait=20, timeout=600, echo=print, progress=lambda files: None):
    """Search `query`, let `pick` choose results, download them into `dest` and wait up to `timeout` seconds,
    sharing the `share` folders meanwhile. `progress` gets the file list (as below) every couple of seconds.
    Returns {"found": n, "files": [{"username", "path", "size", "bytes", "speed", "done", "local_path", "state"}]}."""
    Path(dest).mkdir(parents=True, exist_ok=True)
    return asyncio.run(_fetch(query, pick, dest, share, search_wait, timeout, echo, progress))
