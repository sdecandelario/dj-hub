"""FastAPI app. Serves the API under /api and, when built, the frontend from frontend/dist.

Run with `make dev` (API + Vite dev server) or `make start` (one server on port 8000).
Listens on 127.0.0.1 only: the API moves files.
"""
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import analysis, discovery, downloads, jobs, library, playlists, settings
from .jobs import runner
from .services import analysis as _a, discovery as _disc, downloads as _d, library as _l, playlists as _p, soulseek as _s  # noqa: F401 (job handlers)

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app):
    db.migrate()
    runner.recover()
    with db.session_scope() as session:
        _l.recover_batches(session)
    yield


LOCAL_HOSTNAMES = ("127.0.0.1", "localhost", "::1")
LOCAL_HOSTS = [h if ":" not in h else f"[{h}]" for h in LOCAL_HOSTNAMES]

app = FastAPI(title="DJ Hub", lifespan=lifespan)
# The API moves files, so only this computer may talk to it: a web page open in the browser must not be
# able to call it (cross-site requests), nor reach it through another host name (DNS rebinding).
app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOCAL_HOSTS)


@app.middleware("http")
async def same_machine_only(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin is not None \
            and (urlparse(origin).hostname or "") not in LOCAL_HOSTNAMES:
        return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
    return await call_next(request)


for module in (library, jobs, analysis, downloads, playlists, discovery, settings):
    app.include_router(module.router, prefix="/api")


if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        """The single-page app: real files from dist, everything else gets index.html."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        target = (DIST / path).resolve()
        if path and DIST in target.parents and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
