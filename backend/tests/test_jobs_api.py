"""Job runner robustness and the API's safety checks."""
import os

import pytest

from app.db import session_scope
from app.jobs import HANDLERS, Cancelled, runner
from app.models import Job


@pytest.fixture
def handlers():
    added = []

    def add(name, fn):
        HANDLERS[name] = fn
        added.append(name)
    yield add
    for name in added:
        HANDLERS.pop(name, None)


def status(job_id):
    with session_scope() as s:
        return s.get(Job, job_id).status


def test_failed_job_is_marked_failed_and_logged(env, handlers):
    def boom(ctx):
        raise RuntimeError("nope")
    handlers("t_boom", boom)
    job_id = runner.run_sync("t_boom", echo=lambda *_: None)
    with session_scope() as s:
        job = s.get(Job, job_id)
        assert job.status == "failed" and "nope" in job.message and "Traceback" in job.log
    assert not runner.busy()


def test_ctrl_c_leaves_the_job_interrupted_not_done(env, handlers):
    def stop(ctx):
        raise KeyboardInterrupt
    handlers("t_stop", stop)
    with pytest.raises(KeyboardInterrupt):
        runner.run_sync("t_stop", echo=lambda *_: None)
    with session_scope() as s:
        assert s.query(Job).one().status == "interrupted"
    assert not runner.busy()


def test_cancelled_job_and_missing_job_row_do_not_leave_runner_busy(env, handlers):
    def cancel(ctx):
        raise Cancelled()
    handlers("t_cancel", cancel)
    assert status(runner.run_sync("t_cancel", echo=lambda *_: None)) == "cancelled"
    from app.jobs import JobContext
    runner._contexts[999] = JobContext(999, {})
    runner._run("t_cancel", runner._contexts[999])   # the row does not exist
    assert not runner.busy()


def test_queued_job_cancelled_before_it_starts_never_runs(env, handlers):
    ran = []
    handlers("t_ran", lambda ctx: ran.append(1))
    from app.jobs import JobContext
    with session_scope() as s:
        job = Job(type="t_ran", params={})
        s.add(job)
        s.flush()
        job_id = job.id
    ctx = JobContext(job_id, {})
    ctx._cancel.set()
    runner._contexts[job_id] = ctx
    runner._run("t_ran", ctx)
    assert not ran and status(job_id) == "cancelled"


def test_recover_skips_jobs_of_other_live_processes(env):
    with session_scope() as s:
        s.add_all([Job(type="a", status="running", pid=os.getppid()),     # another live process
                   Job(type="b", status="running", pid=2 ** 22 + 12345),    # a process that is gone
                   Job(type="c", status="queued")])                          # no owner recorded
    runner.recover()
    with session_scope() as s:
        by_type = {j.type: j.status for j in s.query(Job)}
    assert by_type == {"a": "running", "b": "interrupted", "c": "interrupted"}


def test_api_refuses_foreign_hosts_and_origins(env):
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/api/settings").status_code == 200
        assert c.post("/api/jobs/1/cancel", headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.post("/api/jobs/1/cancel", headers={"Origin": "null"}).status_code == 403
        assert c.post("/api/jobs/1/cancel", headers={"Origin": "http://localhost:5173"}).status_code == 200
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/api/settings").status_code == 400   # DNS rebinding: unknown Host header


def test_unknown_api_path_is_404_not_the_app(client):
    assert client.get("/api/nope").status_code == 404


def test_jobs_endpoint_validates_type_and_params(client, env):
    assert client.post("/api/jobs", json={"type": "nope"}).status_code == 400
    assert client.post("/api/jobs", json={"type": "analyze", "params": {}}).status_code == 400
    assert client.post("/api/jobs", json={"type": "analyze", "params": {"paths": [str(env.tmp / "x")]}}).status_code == 400
    assert client.get("/api/jobs?limit=-1").status_code == 422
    assert client.get("/api/batches?limit=100000").status_code == 422


def test_bad_bodies_are_422_or_400_not_500(client):
    assert client.post("/api/batches/preview", json={"kind": "nope", "payload": {}}).status_code == 422
    assert client.post("/api/batches/preview", json={"kind": "apply", "payload": {"items": [1]}}).status_code == 400
    assert client.put("/api/downloads/decisions/x", json={"choice": "maybe"}).status_code in (404, 405, 422)
    assert client.delete("/api/playlists/unknown").status_code == 404


def test_settings_sources_must_be_real_folders(client, env):
    assert client.put("/api/settings", json={"sources": ["/"]}).status_code == 400
    assert client.put("/api/settings", json={"sources": [str(env.tmp / "missing")]}).status_code == 400
    assert client.put("/api/settings", json={"sources": ["relative"]}).status_code == 400


def test_lastfm_errors_never_carry_the_api_key(monkeypatch):
    import urllib.error
    from app.integrations import lastfm

    def boom(request, timeout):
        raise urllib.error.URLError("https://ws.audioscrobbler.com/2.0/?api_key=SECRET")
    monkeypatch.setattr(lastfm.urllib.request, "urlopen", boom)
    with pytest.raises(lastfm.LastfmError) as error:
        lastfm.Lastfm(key="SECRET").top_tracks("DAF")
    assert "SECRET" not in str(error.value) and error.value.__cause__ is None


def test_lastfm_single_result_is_a_list():
    from app.integrations.lastfm import Lastfm
    fake = lambda params: {"toptracks": {"track": {"name": "Only One"}}}   # noqa: E731
    assert Lastfm(key="k", fetch=fake).top_tracks("x") == ["Only One"]


def test_scan_skips_files_that_vanish(env, monkeypatch):
    from app.core import library as core
    from .conftest import fake_audio
    fake_audio(env.root / "00 Inbox" / "A - One.mp3")
    fake_audio(env.root / "00 Inbox" / "B - Two.mp3")
    real = core.quick_fingerprint

    def flaky(path):
        if "B - Two" in str(path):
            raise FileNotFoundError(path)
        return real(path)
    monkeypatch.setattr(core, "quick_fingerprint", flaky)
    assert [t["path"] for t in core.scan(env.root)] == ["00 Inbox/A - One.mp3"]


def test_cli_exits_non_zero_when_a_batch_is_missing(env):
    from app import cli
    with pytest.raises(SystemExit) as error:
        cli.main(["undo", "--batch", "999"])
    assert "not found" in str(error.value)


def test_models_and_migrations_agree(env):
    """After running every migration, the database has exactly what models.py describes."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import engine
    from app.models import Base
    with engine().connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": False})
        assert compare_metadata(context, Base.metadata) == []


def test_batched_lookups_match_the_single_ones(env):
    from app.models import File, Measurement
    from app.services import analysis

    with session_scope() as s:
        s.add(File(path="/x/a.mp3", area="download", size=5, mtime_ns="7", sha256="aaa"))
        s.add(File(path="/x/b.mp3", area="download", size=5, mtime_ns="7", sha256="bbb"))
        s.add(Measurement(path="/x/a.mp3", sha256="aaa", status="OK", full=True, extra={"ffmpeg_version": "v1"}))
        s.add(Measurement(path="/x/b.mp3", sha256="bbb", status="OK", full=True, extra={"ffmpeg_version": "v2"}))
    items = [{"path": "/x/a.mp3", "size": 5, "mtime_ns": "7"}, {"path": "/x/b.mp3", "size": 6, "mtime_ns": "7"},
             {"path": "/x/none.mp3", "size": 1, "mtime_ns": "1"}]
    with session_scope() as s:
        analysis.cached_shas(s, items)
        assert [i["sha256"] for i in items] == ["aaa", None, None]   # b changed size, none is unknown
        found = analysis.reusable_many(s, ["aaa", "bbb", None], True, "v1")
        assert set(found) == {"aaa"}   # bbb was measured with another ffmpeg
        assert found["aaa"].id == analysis.reusable(s, "aaa", True, "v1").id


def test_rms_levels_parser():
    from app.core.audio import rms_levels
    text = "x\n[Parsed_astats_9] RMS level dB: -20.5\nnoise\n[Parsed_astats_9] RMS level dB: -inf\n[a] RMS level dB: nan?\n"
    assert rms_levels(text) == [-20.5, float("-inf"), float("-inf")]


def _id3(major, frames):
    """A minimal ID3 tag: frames are (id, flag byte, payload)."""
    body = b""
    for frame_id, flag, payload in frames:
        size = len(payload)
        raw = bytes([(size >> 21) & 127, (size >> 14) & 127, (size >> 7) & 127, size & 127]) if major == 4 \
            else size.to_bytes(4, "big")
        body += frame_id.encode() + raw + bytes([0, flag]) + payload
    n = len(body)
    return b"ID3" + bytes([major, 0, 0]) + bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127]) + body


def test_id3_flags_depend_on_the_version(tmp_path):
    from app.core.tags import read_tags
    text = lambda s: b"\x00" + s.encode("latin-1")   # noqa: E731
    v23 = tmp_path / "a.mp3"
    # In v2.3 0x08 is not "compressed" (it is 0x80), so this title must be read; 0x80 must be skipped.
    v23.write_bytes(_id3(3, [("TIT2", 0x08, text("Kept")), ("TPE1", 0x80, text("Skipped"))]) + b"x" * 50)
    assert read_tags(v23) == {"title": "Kept"}
    v24 = tmp_path / "b.mp3"
    # In v2.4 0x08 is compression (skip), 0x80 means nothing, and a data-length frame has 4 extra bytes first.
    v24.write_bytes(_id3(4, [("TIT2", 0x08, text("Skipped")), ("TPE1", 0x01, b"\x00\x00\x00\x05" + text("Artist"))])
                    + b"x" * 50)
    assert read_tags(v24) == {"artist": "Artist"}


def test_numeric_genre_references(tmp_path):
    from app.core.tags import read_tags
    text = lambda s: b"\x00" + s.encode("latin-1")   # noqa: E731
    path = tmp_path / "g.mp3"
    path.write_bytes(_id3(3, [("TCON", 0, text("(17)Rock")), ("TIT2", 0, text("T"))]) + b"x" * 50)
    assert read_tags(path) == {"genre": "Rock", "title": "T"}
    path.write_bytes(_id3(3, [("TCON", 0, text("(17)")), ("TIT2", 0, text("T"))]) + b"x" * 50)
    assert read_tags(path) == {"title": "T"}


def test_moved_file_keeps_its_hash_and_first_seen(env):
    from app.models import File
    from app.services import library
    from .conftest import fake_audio

    song = fake_audio(env.root / "00 Inbox" / "A - One.mp3")
    with session_scope() as s:
        library.sync_library(s)
        row = s.query(File).filter_by(path=str(song)).one()
        row.sha256 = "abc"
        first = row.first_seen
    batch = None
    with session_scope() as s:
        batch = library.preview(s, "apply", {"items": [{"source": "00 Inbox/A - One.mp3",
                                                        "to": "Genres/EBM & Industrial", "action": "move"}]}).id
    library.apply(session_scope, batch)
    with session_scope() as s:
        moved = s.query(File).filter(File.path.like("%Genres%A - One.mp3")).one()
        assert moved.sha256 == "abc" and moved.first_seen == first


def test_a_move_keeps_the_file_row_and_its_loudness_shows_in_the_table(client, env):
    from app.models import File, Measurement
    from app.services import library
    from .conftest import fake_audio

    song = fake_audio(env.root / "00 Inbox" / "A - One.mp3")
    with session_scope() as s:
        library.sync_library(s)
        row = s.query(File).filter_by(path=str(song)).one()
        row.sha256 = "abc"
        file_id, first = row.id, row.first_seen
        s.add(Measurement(path=str(song), sha256="abc", status="OK", integrated_lufs=-9.5, full=False))
    with session_scope() as s:
        batch = library.preview(s, "apply", {"items": [{"source": "00 Inbox/A - One.mp3",
                                                        "to": "Genres/EBM & Industrial", "action": "move"}]}).id
    library.apply(session_scope, batch)
    with session_scope() as s:
        moved = s.get(File, file_id)   # the same row, not a new one
        assert moved.path.endswith("Genres/EBM & Industrial/A - One.mp3") and moved.first_seen == first
        assert s.query(File).count() == 1
    shown = client.get("/api/library/files", params={"kind": "genre"}).json()
    assert shown[0]["id"] == file_id and shown[0]["loudness"]["integrated_lufs"] == -9.5   # found by hash
    undo = client.post(f"/api/batches/{batch}/undo").json()["id"]
    library.apply(session_scope, undo)
    with session_scope() as s:
        assert s.get(File, file_id).path == str(song) and s.query(File).count() == 1   # and back again
