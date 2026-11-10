"""End to end with real audio: analysis history, downloads review, decisions, intake, playlists, API."""
from pathlib import Path

from app.core import audio, history
from app.db import session_scope
from app.jobs import runner
from app.models import Playlist, PlaylistTrack
from app.services import analysis, downloads, library, playlists

from .conftest import real_audio


def test_analysis_is_read_only_reuses_results_and_resumes(env):
    song = real_audio(env.root / "Genres" / "EBM & Industrial" / "DAF - Liebe.mp3")
    before = audio.sha256_file(song)
    job = runner.run_sync("analyze", {"path": str(env.root)}, echo=None)
    second = runner.run_sync("analyze", {"path": str(env.root)}, echo=None)
    assert audio.sha256_file(song) == before
    with session_scope() as s:
        first_rows, second_rows = analysis.run_tracks(s, job), analysis.run_tracks(s, second)
        assert first_rows[0]["status"] == "OK" and first_rows[0]["integrated_lufs"] is not None
        assert second_rows[0]["origin"] == "reused"
        overview = analysis.overview(s)
        assert overview["references"][0]["id"] == second
        assert len(overview["current"]) == 1


def test_current_library_links_renames_by_hash_only(tmp_path):
    old, new = tmp_path / "old.mp3", tmp_path / "new.mp3"
    new.touch()
    row = lambda p, digest: {"path": str(p), "status": "OK", "integrated_lufs": -12.0, "true_peak_dbtp": 0.1,
                             "loudness_range_lu": 3.0, "sha256": digest}
    run = lambda ident, rows, scope="file", manifest=None: {
        "id": ident, "scope": scope, "complete": True, "config": {"input": str(tmp_path)},
        "manifest": manifest if manifest is not None else [r["path"] for r in rows], "tracks": rows}
    current = history.current_library([run(1, [row(old, "abc")], "folder"), run(2, [row(new, "abc")])])
    assert [r["path"] for r in current] == [str(new)]
    current = history.current_library([run(1, [row(old, None)], "folder"), run(2, [row(new, None)])])
    assert len(current) == 2
    current = history.current_library([run(1, [row(new, "abc")], "folder"), run(2, [], "folder", [])])
    assert current[0]["missing"]


def test_downloads_review_pick_and_intake(env):
    good = real_audio(env.downloads / "Boy Harsher - Pain.mp3", bitrate="320k")
    worse = real_audio(env.downloads / "other" / "Boy Harsher - Pain.mp3", bitrate="96k")
    real_audio(env.downloads / "Molchat Doma - Sudno.mp3", frequency=300)
    runner.run_sync("review_downloads", {}, echo=None)
    with session_scope() as s:
        view = downloads.review_view(s)
        pain = next(x for x in view["songs"] if x["title"] == "Pain")
        assert len(view["songs"]) == 2 and len(pain["versions"]) == 2
        assert pain["suggested"] == str(good.resolve())
        downloads.decide(s, pain["id"], "keep", pain["suggested"])
    with session_scope() as s:
        batch = downloads.preview_intake(s).id
    library.apply(session_scope, batch)
    assert (env.root / "00 Inbox" / good.name).exists()
    assert (env.root / "00 Rejected" / "Boy Harsher - Pain" / worse.name).exists()
    with session_scope() as s:
        titles = [x["title"] for x in downloads.review_view(s)["songs"]]
        assert titles == ["Sudno"]   # the applied song leaves the review
    # A second review measures nothing new.
    job = runner.run_sync("review_downloads", {}, echo=None)
    with session_scope() as s:
        from app.models import Job
        assert s.get(Job, job).summary["measured"] == 0


def test_playlist_matching_and_waiting_downloads(env):
    real_audio(env.root / "Genres" / "Synth-Pop & New Wave" / "Soft Cell - Tainted Love.mp3")
    real_audio(env.downloads / "Molchat Doma - Sudno.mp3")
    with session_scope() as s:
        s.add(Playlist(id="P" * 22, name="Test", project="Serge Candel"))
        s.add(PlaylistTrack(playlist_id="P" * 22, position=0, spotify_id="a", title="Tainted Love",
                            artists=["Soft Cell"]))
        s.add(PlaylistTrack(playlist_id="P" * 22, position=1, spotify_id="b", title="Sudno (Boris Ryzhy)",
                            artists=["Molchat Doma"]))
        s.add(PlaylistTrack(playlist_id="P" * 22, position=2, spotify_id="c", title="Take on Me", artists=["a-ha"]))
    runner.run_sync("library_scan", {}, echo=None)
    runner.run_sync("review_downloads", {}, echo=None)
    with session_scope() as s:
        rows = {t["spotify_id"]: t for t in playlists.tracks(s)}
        assert rows["a"]["status"] == "have" and rows["a"]["projects"] == ["Serge Candel"]
        assert rows["b"]["status"] == "missing" and rows["b"]["download"]
        assert rows["c"]["status"] == "missing" and not rows["c"]["download"]
        view = downloads.review_view(s)
        assert view["songs"][0]["wanted_by"][0]["playlists"] == ["Test"]


def test_api_smoke(client, env):
    song = real_audio(env.root / "00 Inbox" / "Yazoo - Situation.mp3")
    client.post("/api/jobs", json={"type": "library_scan"})
    for _ in range(50):
        if not runner.busy():
            break
        import time
        time.sleep(0.1)
    files = client.get("/api/library/files", params={"kind": "inbox"}).json()
    assert [f["name"] for f in files] == [song.name]
    detail = client.get(f"/api/files/{files[0]['id']}").json()
    assert detail["history"] == []
    audio_part = client.get(f"/api/files/{files[0]['id']}/audio", headers={"Range": "bytes=0-99"})
    assert audio_part.status_code == 206 and len(audio_part.content) == 100
    batch = client.post("/api/batches/preview", json={"kind": "apply", "payload": {"items": [
        {"source": "00 Inbox/Yazoo - Situation.mp3", "to": "Genres/Synth-Pop & New Wave", "action": "move"}]}}).json()
    assert batch["status"] == "preview" and len(batch["plan"]["steps"]) == 1
    assert client.post(f"/api/batches/{batch['id']}/apply").json()["status"] == "applied"
    assert client.post(f"/api/batches/{batch['id']}/apply").status_code == 409
    assert client.get("/api/summary").json()["inbox"] == 0
    assert Path(env.root / "Genres" / "Synth-Pop & New Wave" / song.name).exists()
    assert client.get("/api/library/tree").json()["genres"] == ["EBM & Industrial", "Synth-Pop & New Wave"]


def test_analysis_of_several_folders_is_one_run(env):
    ebm = real_audio(env.root / "Genres" / "EBM & Industrial" / "DAF - Liebe.mp3")
    wave = real_audio(env.root / "Genres" / "Post-Punk & Dark Wave" / "Boy Harsher - Pain.mp3", frequency=300)
    real_audio(env.root / "Genres" / "Other" / "Skip - Me.mp3")
    folders = [str(ebm.parent), str(wave.parent), str(ebm.parent)]
    job = runner.run_sync("analyze", {"paths": folders}, echo=None)
    with session_scope() as s:
        assert sorted(r["filename"] for r in analysis.run_tracks(s, job)) == sorted([ebm.name, wave.name])
        run = next(r for r in analysis.runs(s) if r["id"] == job)
        assert run["scope"] == "folder" and run["complete"]
        assert run["config"]["inputs"] == [str(ebm.parent.resolve()), str(wave.parent.resolve())]
    # Nested folders are measured once: the library root covers the genre.
    job = runner.run_sync("analyze", {"paths": [str(env.root), str(ebm.parent)]}, echo=None)
    with session_scope() as s:
        assert len(analysis.run_tracks(s, job)) == 3


def test_missing_files_are_flagged_under_any_input_folder(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    gone = a / "gone.mp3"
    row = {"path": str(gone), "status": "OK", "integrated_lufs": -12.0, "true_peak_dbtp": 0.1,
           "loudness_range_lu": 3.0, "sha256": None}
    first = {"id": 1, "scope": "file", "complete": True, "config": {"input": str(gone)},
             "manifest": [str(gone)], "tracks": [row]}
    second = {"id": 2, "scope": "folder", "complete": True,
              "config": {"input": f"{b}; {a}", "inputs": [str(b), str(a)]}, "manifest": [], "tracks": []}
    assert history.current_library([first, second])[0]["missing"]


def test_downloads_review_compares_with_the_library_copy(env):
    lib_copy = real_audio(env.root / "Genres" / "EBM & Industrial" / "Nitzer Ebb - Join In The Chant.mp3",
                          bitrate="96k", artist="Nitzer Ebb", title="Join In The Chant")
    before = lib_copy.stat().st_mtime_ns
    real_audio(env.downloads / "Nitzer Ebb - Join In The Chant.mp3", bitrate="320k")
    runner.run_sync("review_downloads", {}, echo=None)
    with session_scope() as s:
        song = downloads.review_view(s)["songs"][0]
    assert song["in_library"] == [str(lib_copy.relative_to(env.root))]
    assert [v["path"] for v in song["library_versions"]] == [str(lib_copy.resolve())]
    assert song["library_versions"][0]["file_id"]
    assert song["versions"][0]["vs_library"]["verdict"] == "better"
    assert lib_copy.stat().st_mtime_ns == before   # the library file is only read
