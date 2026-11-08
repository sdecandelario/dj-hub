"""FastAPI app. Serves the API under /api and, when built, the frontend from frontend/dist.

Run with `make dev` (API + Vite dev server) or `make start` (one server on port 8000).
Listens on 127.0.0.1 only: the API moves files.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import analysis, downloads, jobs, library, playlists, settings
from .jobs import runner
from .services import analysis as _a, downloads as _d, library as _l, playlists as _p  # noqa: F401 (job handlers)

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app):
    db.migrate()
    runner.recover()
    yield


app = FastAPI(title="DJ Hub", lifespan=lifespan)
for module in (library, jobs, analysis, downloads, playlists, settings):
    app.include_router(module.router, prefix="/api")


if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        """The single-page app: real files from dist, everything else gets index.html."""
        target = (DIST / path).resolve()
        if path and DIST in target.parents and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
