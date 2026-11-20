"""Soulseek client (aioslsk): search for songs and download the chosen results.

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


# Seconds a download may sit in a peer's queue before it is dropped (the song's other versions go on).
QUEUE_GRACE = 30


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


async def _fetch(queries, pick, dest, share, search_wait, timeout, echo, progress, cancelled, skipped):
    settings = Settings(credentials=credentials())
    settings.shares.download = str(dest)
    settings.shares.directories = [SharedDirectorySettingEntry(path=str(p)) for p in share]
    async with SoulSeekClient(settings) as client:
        try:
            await client.login()
        except AioSlskException as error:
            raise SoulseekError(f"Soulseek login failed: {error}") from None
        echo(f"Searching Soulseek for {len(queries)} song(s) ({search_wait}s)")
        requests = {q: await client.searches.search(q) for q in queries}
        for _ in range(search_wait):
            if cancelled():
                return {q: {"found": 0, "files": []} for q in queries}
            await asyncio.sleep(1)
        found, transfers = {}, {}
        for query, request in requests.items():
            results = _results(request)
            chosen = [] if query in skipped() else pick(query, results)
            echo(f"{query}: {len(results)} files found, {len(chosen)} chosen")
            found[query] = len(results)
            transfers[query] = [(r, await client.transfers.download(r.username, r.path)) for r in chosen]
        everything = [t for pairs in transfers.values() for _, t in pairs]
        snapshot = lambda: {q: {"found": found[q], "files": [_snapshot(r, t) for r, t in pairs]}
                            for q, pairs in transfers.items()}
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        started = loop.time()
        while loop.time() < deadline and not cancelled() and not all(t.is_finalized() for t in everything):
            for query in skipped():   # dropped by the user: stop that song's unfinished transfers
                for _, transfer in transfers.get(query, []):
                    if not transfer.is_finalized():
                        await client.transfers.abort(transfer)
            if loop.time() - started > QUEUE_GRACE:   # a peer that still queues us is not worth waiting for
                for transfer in everything:
                    if transfer.state.VALUE == TransferState.QUEUED:
                        await client.transfers.abort(transfer)
            progress(snapshot())
            await asyncio.sleep(2)
        for transfer in everything:
            if not transfer.is_finalized():
                await client.transfers.abort(transfer)   # also removes the partial file
        # What did not arrive (queued and dropped, failed, aborted) is not reported: only finished files count.
        return {q: {**song, "files": [f for f in song["files"] if f["done"]]} for q, song in snapshot().items()}


def fetch(queries, pick, dest, share=(), search_wait=20, timeout=600, echo=print, progress=lambda songs: None,
          cancelled=lambda: False, skipped=lambda: ()):
    """Search every query in one session, let `pick(query, results)` choose results, download them all into `dest`
    and wait up to `timeout` seconds, sharing the `share` folders meanwhile. `progress` gets the result below
    every couple of seconds. Stops early (aborting unfinished transfers) once `cancelled()` is true; `skipped()` lists the queries
    to drop meanwhile.
    Returns, per query, only the files that finished: {query: {"found": n, "files": [{"username", "path", "size", "bytes", "speed", "done", "local_path",
    "state"}]}}."""
    Path(dest).mkdir(parents=True, exist_ok=True)
    return asyncio.run(_fetch(queries, pick, dest, share, search_wait, timeout, echo, progress, cancelled, skipped))
