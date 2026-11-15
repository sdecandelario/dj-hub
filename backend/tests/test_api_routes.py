"""Routes and CLI commands that had no tests: settings, downloads, file access, Spotify login, the CLI."""
import json

import pytest

from app import cli
from app.db import session_scope
from app.models import File

from .conftest import fake_audio


def indexed(env, path):
    with session_scope() as s:
        s.add(File(path=str(path), area="library", rel_path=path.name))
        s.flush()
        return s.query(File).filter_by(path=str(path)).one().id


# --- settings -------------------------------------------------------------------------


def test_settings_roundtrip(client, env, monkeypatch):
    data = client.get("/api/settings").json()
    assert data["root"] == str(env.root) and data["sources_locked"] is True   # DJ_SOURCES is set by the test env
    assert client.put("/api/settings", json={"sources": [str(env.tmp)]}).status_code == 400   # locked
    monkeypatch.delenv("DJ_SOURCES")
    folder = env.tmp / "More Downloads"
    folder.mkdir()
    saved = client.put("/api/settings", json={"sources": [str(folder), " "]}).json()
    assert saved["sources"] == [str(folder)]


def test_summary_counts_an_empty_app(client):
    summary = client.get("/api/summary").json()
    assert summary["library_files"] == 0 and summary["missing"] == 0 and summary["recent_jobs"] == []


# --- file access ------------------------------------------------------------------------


def test_audio_is_served_only_from_known_folders(client, env):
    inside = fake_audio(env.root / "00 Inbox" / "A - One.mp3")
    outside = fake_audio(env.tmp / "secret" / "x.mp3")
    assert client.get(f"/api/files/{indexed(env, inside)}/audio").status_code == 200
    assert client.get(f"/api/files/{indexed(env, outside)}/audio").status_code == 404
    # a path that climbs out of the library with .. does not count as inside it
    sneaky = env.root / "00 Inbox" / ".." / ".." / "secret" / "x.mp3"
    assert client.get(f"/api/files/{indexed(env, sneaky)}/audio").status_code == 404
    assert client.get("/api/files/99999/audio").status_code == 404


def test_reveal_refuses_outside_files_without_running_open(client, env, monkeypatch):
    from app.api import library as api
    calls = []
    monkeypatch.setattr(api.subprocess, "run", lambda *a, **k: calls.append(a))
    outside = fake_audio(env.tmp / "secret" / "x.mp3")
    assert client.post(f"/api/files/{indexed(env, outside)}/reveal").status_code == 404
    inside = fake_audio(env.root / "00 Inbox" / "A - One.mp3")
    assert client.post(f"/api/files/{indexed(env, inside)}/reveal").status_code == 200
    assert len(calls) == 1 and calls[0][0][:2] == ["open", "-R"]


# --- downloads --------------------------------------------------------------------------


def test_downloads_decisions_and_preview_need_a_review(client):
    assert client.get("/api/downloads").json() is None
    assert client.put("/api/downloads/decisions/x", json={"choice": "maybe"}).status_code == 422
    assert client.put("/api/downloads/decisions/unknown", json={"choice": "reject"}).status_code == 400
    refused = client.post("/api/downloads/preview", json={})
    assert refused.status_code == 400 and "No decided songs" in refused.json()["detail"]


# --- Spotify login ----------------------------------------------------------------------


def test_spotify_status_and_login_without_keys(client, monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    status = client.get("/api/spotify/status").json()
    assert status["keys"] is False and status["logged_in"] is False
    assert client.get("/api/spotify/login").status_code == 400
    assert client.get("/api/spotify/callback?state=nope&code=x").status_code == 404


def test_spotify_callback_escapes_the_error_text(client, monkeypatch):
    from app.api import playlists as api
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    location = client.get("/api/spotify/login", follow_redirects=False).headers["location"]
    state = location.split("state=")[1].split("&")[0]
    response = client.get("/api/spotify/callback", params={"state": state, "error": "<script>alert(1)</script>"})
    assert response.status_code == 400 and "<script>" not in response.text
    api._login_states.clear()


# --- CLI ------------------------------------------------------------------------------------


def run_cli(*argv):
    cli.main(list(argv))


def test_cli_apply_dry_run_then_apply_and_undo(env, capsys):
    song = fake_audio(env.root / "00 Inbox" / "Soft Cell - Tainted Love.mp3")
    plan = env.tmp / "plan.json"
    plan.write_text(json.dumps([{"source": "00 Inbox/Soft Cell - Tainted Love.mp3",
                                 "to": "Genres/Synth-Pop & New Wave", "action": "move"}]), encoding="utf-8")
    run_cli("apply", str(plan))
    assert "Dry run" in capsys.readouterr().out and song.exists()
    run_cli("apply", str(plan), "--apply")
    target = env.root / "Genres" / "Synth-Pop & New Wave" / song.name
    assert target.exists() and not song.exists()
    run_cli("history")
    assert "Library change" in capsys.readouterr().out
    run_cli("undo", "--apply")
    assert song.exists() and not target.exists()
    run_cli("undo")
    assert "Nothing to undo" in capsys.readouterr().out


def test_cli_status_find_scan_and_dupes(env, capsys):
    fake_audio(env.root / "00 Inbox" / "Soft Cell - Tainted Love.mp3")
    run_cli("status")
    assert "1 files" in capsys.readouterr().out
    run_cli("find", "tainted")
    assert "Tainted Love" in capsys.readouterr().out
    run_cli("scan", "00 Inbox")
    assert json.loads(capsys.readouterr().out)[0]["source"] == "00 Inbox/Soft Cell - Tainted Love.mp3"
    run_cli("dupes")
    assert "0 found" in capsys.readouterr().out


def test_cli_stops_when_the_library_is_missing(env, monkeypatch):
    from app import config
    monkeypatch.setenv("DJ_TRACKS_ROOT", str(env.tmp / "nowhere"))
    config.reload_config()
    with pytest.raises(SystemExit) as error:
        run_cli("status")
    assert "Library not found" in str(error.value)


def test_cli_failed_apply_exits_non_zero(env, monkeypatch):
    from app.core import library as core
    fake_audio(env.root / "00 Inbox" / "A - One.mp3")
    plan = env.tmp / "plan.json"
    plan.write_text(json.dumps([{"source": "00 Inbox/A - One.mp3", "to": "Genres/X", "action": "move"}]),
                    encoding="utf-8")
    monkeypatch.setattr(core, "execute", lambda *a, **k: (_ for _ in ()).throw(OSError("disk went away")))
    with pytest.raises(SystemExit) as error:
        run_cli("apply", str(plan), "--apply")
    assert "disk went away" in str(error.value)
