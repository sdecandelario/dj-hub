"""Database tables. Paths are stored absolute."""
import datetime as dt

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return dt.datetime.now().replace(microsecond=0)


class Base(DeclarativeBase):
    pass


class File(Base):
    """Every audio file seen in the library or the download folders."""
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True, index=True)
    area: Mapped[str] = mapped_column(String, index=True)            # library | download | other
    kind: Mapped[str] = mapped_column(String, default="")           # inbox | rejected | genre | session | unsorted
    folder: Mapped[str] = mapped_column(String, default="")
    rel_path: Mapped[str] = mapped_column(String, default="")       # relative to the library root
    size: Mapped[int] = mapped_column(Integer, default=0)
    mtime_ns: Mapped[str] = mapped_column(String, default="")
    quick_fp: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    artist: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String, default="")
    genre_tag: Mapped[str] = mapped_column(String, default="")
    bpm: Mapped[str] = mapped_column(String, default="")
    present: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    first_seen: Mapped[dt.datetime] = mapped_column(default=now)
    last_seen: Mapped[dt.datetime] = mapped_column(default=now)


class Job(Base):
    """A background task: library scan, analysis run, downloads review, Spotify refresh."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String, index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="queued")   # queued|running|done|failed|cancelled|interrupted
    done: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    log: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    legacy_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=now)
    started_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)


class Measurement(Base):
    """One measurement of one file. Analysis runs and downloads reviews both add rows."""
    __tablename__ = "measurements"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True, nullable=True)
    path: Mapped[str] = mapped_column(String, index=True)
    sha256: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mtime_ns: Mapped[str | None] = mapped_column(String, nullable=True)
    measured_at: Mapped[dt.datetime] = mapped_column(default=now)
    full: Mapped[bool] = mapped_column(Boolean, default=False)       # includes the downloads quality checks
    origin: Mapped[str] = mapped_column(String, default="app")       # app | reused | legacy-run | legacy-cache
    status: Mapped[str] = mapped_column(String, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    integrated_lufs: Mapped[float | None] = mapped_column(Float, nullable=True)
    true_peak_dbtp: Mapped[float | None] = mapped_column(Float, nullable=True)
    loudness_range_lu: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    codec: Mapped[str] = mapped_column(String, default="")
    sample_rate_hz: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)          # quality checks, tags from ffprobe, versions


class Batch(Base):
    """A planned or applied set of file changes. Applied batches can be undone."""
    __tablename__ = "batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String)                        # apply | remove | intake | undo
    status: Mapped[str] = mapped_column(String, default="preview")   # preview|applied|partial|undone|discarded|failed
    label: Mapped[str] = mapped_column(String, default="")
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    undoes_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    legacy_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=now)
    applied_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)


class FileOp(Base):
    __tablename__ = "file_ops"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String)                      # copy | move
    label: Mapped[str] = mapped_column(String, default="")           # trash | inbox | reject | ...
    source: Mapped[str] = mapped_column(String)
    dest: Mapped[str] = mapped_column(String)
    tags_before: Mapped[dict | None] = mapped_column(JSON, nullable=True)   # tag values replaced by this step (for undo)


class Review(Base):
    """Result of a downloads review: songs, ranked versions and the suggested pick."""
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(default=now)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Decision(Base):
    """Your choice for one downloaded song: keep a version, reject all, or decide later."""
    __tablename__ = "decisions"
    song_key: Mapped[str] = mapped_column(String, primary_key=True)
    song: Mapped[str] = mapped_column(String, default="")
    choice: Mapped[str] = mapped_column(String)                      # keep | reject | later
    keep_path: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[dt.datetime] = mapped_column(default=now)
    applied_batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"), nullable=True)


class Playlist(Base):
    __tablename__ = "playlists"
    id: Mapped[str] = mapped_column(String, primary_key=True)        # Spotify playlist ID
    name: Mapped[str] = mapped_column(String, default="")
    owner: Mapped[str] = mapped_column(String, default="")
    cover: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="")          # api | embed
    possibly_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    project: Mapped[str] = mapped_column(String, default="")         # DJ project this playlist defines
    position: Mapped[int] = mapped_column(Integer, default=0)
    tracked: Mapped[bool] = mapped_column(Boolean, default=True)
    refreshed_at: Mapped[dt.datetime | None] = mapped_column(nullable=True)


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[str] = mapped_column(ForeignKey("playlists.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    spotify_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, default="")
    artists: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Match(Base):
    """Latest match of a Spotify track against the library and the downloads."""
    __tablename__ = "matches"
    spotify_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)                      # have | maybe | missing
    path: Mapped[str | None] = mapped_column(String, nullable=True)
    relative_path: Mapped[str | None] = mapped_column(String, nullable=True)
    matched_title: Mapped[str] = mapped_column(String, default="")
    matched_artist: Mapped[str] = mapped_column(String, default="")
    note: Mapped[str] = mapped_column(String, default="")
    download_song_key: Mapped[str | None] = mapped_column(String, nullable=True)   # a waiting download
    download_status: Mapped[str] = mapped_column(String, default="")              # have | maybe
    computed_at: Mapped[dt.datetime] = mapped_column(default=now)


class Mark(Base):
    """'Downloaded' tick on a Spotify track (replaces the old browser storage)."""
    __tablename__ = "marks"
    spotify_id: Mapped[str] = mapped_column(String, primary_key=True)
    marked_at: Mapped[dt.datetime] = mapped_column(default=now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
