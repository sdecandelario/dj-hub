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
