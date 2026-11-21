"""Rekordbox export logs: parsing, following dj-hub's file history, and the review."""
from app.core import rekordbox as rb
from app.db import session_scope
from app.services import library

from .conftest import fake_audio

LOG = ("One or more files were not exported. \n[1] - The file doesn't exist.\n\n    Track Title\tLocation\n"
       "[1] Born Killer\t/Music/Genres/Synth-Pop/11 Born Killer.mp3\n\n"
       "[1] Born Killer\t/Music/Genres/Synth-Pop/11 Born Killer.mp3\n"
       "[2] Other\t/Music/Genres/X/Other.mp3\n")


def test_parse_log_reads_utf16_and_counts_a_track_once():
    raw = b"\xff\xfe" + LOG.encode("utf-16-le")
    entries = rb.parse_log(rb.decode(raw))
    assert [(e["title"], e["reason"]) for e in entries] == [("Born Killer", "1"), ("Other", "2")]
    assert entries[0]["path"] == "/Music/Genres/Synth-Pop/11 Born Killer.mp3"


def test_follow_trail_replays_moves_in_order():
    ops = [{"id": 1, "source": "/a/x.mp3", "dest": "/b/x.mp3", "label": ""},
           {"id": 2, "source": "/b/x.mp3", "dest": "/c/x.mp3", "label": ""},
           {"id": 3, "source": "/c/x.mp3", "dest": "/b/x.mp3", "label": ""}]   # undone: back in /b
    assert rb.follow_trail(ops, "/a/x.mp3")[0] == "/b/x.mp3"
    assert rb.follow_trail(ops, "/zzz.mp3") == ("/zzz.mp3", [])


def test_candidates_try_the_name_both_ways_and_skip_other_songs():
    tracks = [{"path": "Genres/A/Home Front - Born Killer.mp3", "abs": "/x", "artist": "Home Front", "title": "Born Killer", "kind": "genre"},
              {"path": "Genres/A/Home Front - Other.mp3", "abs": "/y", "artist": "Home Front", "title": "Other", "kind": "genre"},
              {"path": "00 Rejected/s/Born Killer.mp3", "abs": "/z", "artist": "Home Front", "title": "Born Killer", "kind": "rejected"}]
    entry = {"title": "Born Killer - Home Front", "path": "/old/Born Killer - Home Front.mp3"}
    assert [c["path"] for c in rb.candidates(entry, tracks)] == ["Genres/A/Home Front - Born Killer.mp3"]


def test_review_follows_batches_and_finds_missing_files(env, client):
    env.rekordbox.mkdir()
    old = env.root / "Genres" / "EBM & Industrial" / "DAF - Kebab.mp3"
    nothing = env.root / "Genres" / "EBM & Industrial" / "Nobody - Nothing.mp3"
    (env.rekordbox / "Export Log 2026-11-13.txt").write_bytes(f"[1] Kebab\t{old}\n[1] Nothing\t{nothing}\n".encode("utf-16"))
    fake_audio(old, content=b"a")
    with session_scope() as s:
        library.sync_library(s)
        batch = library.preview(s, "apply", {"items": [{"source": "Genres/EBM & Industrial/DAF - Kebab.mp3",
                                                        "to": "Genres/Synth-Pop & New Wave", "action": "move"}]}).id
    library.apply(session_scope, batch)

    data = client.get("/api/rekordbox").json()
    by_title = {t["title"]: t for t in data["tracks"]}
    assert data["logs"] == [{"name": "Export Log 2026-11-13.txt", "tracks": 2}]
    kebab = by_title["Kebab"]
    assert kebab["status"] == "moved" and kebab["new_rel"] == "Genres/Synth-Pop & New Wave/DAF - Kebab.mp3"
    assert kebab["trail"][0]["batch_id"] == batch and kebab["file_id"] is not None
    assert by_title["Nothing"]["status"] == "missing" and by_title["Nothing"]["new_path"] == ""
    assert [t["title"] for t in data["tracks"]] == ["Nothing", "Kebab"]      # still missing first


def test_a_file_back_at_its_old_path_is_ok(env, client):
    env.rekordbox.mkdir()
    song = fake_audio(env.root / "Genres" / "EBM & Industrial" / "DAF - Kebab.mp3")
    (env.rekordbox / "Export Log 2026-11-13.txt").write_bytes(f"[1] Kebab\t{song}\n".encode("utf-16"))
    assert client.get("/api/rekordbox").json()["tracks"][0]["status"] == "ok"
