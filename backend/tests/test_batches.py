"""File changes: the library rules, dry runs, apply, undo, and refusing stale previews."""
import json
from pathlib import Path

import pytest

from app.db import session_scope
from app.models import Batch, FileOp
from app.services import legacy, library

from .conftest import fake_audio


def preview(kind, payload):
    with session_scope() as s:
        return library.preview(s, kind, payload).id


def plan(kind, payload):
    with session_scope() as s:
        return library.make_plan(s, kind, payload)


def test_move_from_inbox_to_genre_then_undo(env):
    song = fake_audio(env.root / "00 Inbox" / "Soft Cell - Tainted Love.mp3")
    batch = preview("apply", {"items": [{"source": "00 Inbox/Soft Cell - Tainted Love.mp3",
                                         "to": "Genres/Synth-Pop & New Wave", "action": "move"}]})
    assert song.exists()  # a preview changes nothing
    result = library.apply(session_scope, batch)
    target = env.root / "Genres" / "Synth-Pop & New Wave" / song.name
    assert result["status"] == "applied" and target.exists() and not song.exists()

    undo = preview("undo", {"batch_id": batch})
    library.apply(session_scope, undo)
    assert song.exists() and not target.exists()
    with session_scope() as s:
        assert s.get(Batch, batch).status == "undone"


def test_a_song_keeps_one_genre(env):
    fake_audio(env.root / "Genres" / "EBM & Industrial" / "DAF - Der Mussolini.mp3")
    p = plan("apply", {"items": [{"source": "Genres/EBM & Industrial/DAF - Der Mussolini.mp3",
                                  "to": "Genres/Synth-Pop & New Wave", "action": "copy"}]})
    assert not p.runnable() and "one genre" in p.problems[0]
    p = plan("apply", {"items": [{"source": "Genres/EBM & Industrial/DAF - Der Mussolini.mp3",
                                  "to": "Sessions/Party", "action": "move"}]})
    assert not p.runnable() and "without a genre" in p.problems[0]
    p = plan("apply", {"items": [{"source": "Genres/EBM & Industrial/DAF - Der Mussolini.mp3",
                                  "to": "Party", "action": "copy"}]})
    assert "Sessions/Party" in p.problems[0]


def test_copy_to_session_and_skip_when_already_there(env):
    fake_audio(env.root / "Genres" / "EBM & Industrial" / "DAF - Kebab.mp3")
    item = {"source": "Genres/EBM & Industrial/DAF - Kebab.mp3", "to": "Sessions/Party", "action": "copy"}
    library.apply(session_scope, preview("apply", {"items": [item]}))
    assert (env.root / "Sessions" / "Party" / "DAF - Kebab.mp3").exists()
    assert plan("apply", {"items": [item]}).steps[0].action == "skip"


def test_remove_goes_to_trash_and_protects_the_only_genre_copy(env):
    fake_audio(env.root / "Genres" / "EBM & Industrial" / "Front 242 - Headhunter.mp3")
    fake_audio(env.root / "Sessions" / "Party" / "Front 242 - Headhunter.mp3")
    p = plan("remove", {"paths": ["Genres/EBM & Industrial/Front 242 - Headhunter.mp3"]})
    assert not p.runnable() and "only genre copy" in p.problems[0]
    batch = preview("remove", {"paths": ["Sessions/Party"]})
    library.apply(session_scope, batch)
    assert not (env.root / "Sessions" / "Party" / "Front 242 - Headhunter.mp3").exists()
    assert list(env.trash.rglob("Front 242 - Headhunter.mp3"))
    library.apply(session_scope, preview("undo", {"batch_id": batch}))
    assert (env.root / "Sessions" / "Party" / "Front 242 - Headhunter.mp3").exists()


def test_stale_preview_is_refused(env):
    song = fake_audio(env.root / "00 Inbox" / "Yazoo - Situation.mp3")
    batch = preview("apply", {"items": [{"source": "00 Inbox/Yazoo - Situation.mp3",
                                         "to": "Genres/Synth-Pop & New Wave", "action": "move"}]})
    song.unlink()
    with pytest.raises(library.BatchError, match="changed since the preview"):
        library.apply(session_scope, batch)
    with session_scope() as s:
        assert s.get(Batch, batch).status == "discarded"


def test_intake_moves_keep_to_inbox_and_others_to_rejected(env):
    keep = fake_audio(env.downloads / "a" / "Boy Harsher - Pain.mp3", b"a")
    other = fake_audio(env.downloads / "b" / "Boy Harsher - Pain.mp3", b"b")
    stat = keep.stat()
    picks = [{"song": "Boy Harsher - Pain", "keep": str(keep), "reject": [str(other)],
              "signatures": {str(keep): [stat.st_size, str(stat.st_mtime_ns)]}}]
    library.apply(session_scope, preview("intake", {"picks": picks}))
    assert (env.root / "00 Inbox" / "Boy Harsher - Pain.mp3").exists()
    assert (env.root / "00 Rejected" / "Boy Harsher - Pain" / "Boy Harsher - Pain.mp3").exists()
    assert not keep.exists() and not other.exists()


def test_intake_renames_kept_file_to_artist_title(env):
    keep = fake_audio(env.downloads / "03-boy_harsher-pain_(club_mix)-a1b2c3d4.MP3", b"a")
    other = fake_audio(env.downloads / "b" / "pain 320.mp3", b"b")
    picks = [{"song": "Boy Harsher - Pain", "keep": str(keep), "reject": [str(other)],
              "artist": "Boy Harsher", "title": "Pain (Club Mix)"}]
    library.apply(session_scope, preview("intake", {"picks": picks}))
    assert (env.root / "00 Inbox" / "Boy Harsher - Pain (Club Mix).mp3").exists()
    assert (env.root / "00 Rejected" / "Boy Harsher - Pain" / "pain 320.mp3").exists()   # rejects keep their names


def test_intake_rename_refuses_existing_name(env):
    fake_audio(env.root / "00 Inbox" / "Boy Harsher - Pain.mp3", b"old")
    keep = fake_audio(env.downloads / "boy harsher pain.mp3", b"a")
    picks = [{"song": "Boy Harsher - Pain", "keep": str(keep), "reject": [],
              "artist": "Boy Harsher", "title": "Pain"}]
    p = plan("intake", {"picks": picks})
    assert not p.steps and any("already in 00 Inbox" in x for x in p.problems)


def test_intake_refuses_non_mp3_in_inbox_but_rejects_it(env):
    flac = fake_audio(env.downloads / "Boy Harsher - Pain.flac", b"f")
    p = plan("intake", {"picks": [{"song": "Boy Harsher - Pain", "keep": str(flac), "reject": []}]})
    assert not p.steps and any("only MP3 files go to 00 Inbox" in x for x in p.problems)
    p = plan("intake", {"picks": [{"song": "Boy Harsher - Pain", "keep": None, "reject": [str(flac)]}]})
    assert p.runnable() and p.steps[0].dest.endswith("00 Rejected/Boy Harsher - Pain/Boy Harsher - Pain.flac")


def test_intake_refuses_files_outside_downloads_and_changed_files(env):
    outside = fake_audio(env.tmp / "elsewhere" / "x.mp3")
    keep = fake_audio(env.downloads / "y.mp3")
    picks = [{"song": "X", "keep": str(outside), "reject": []},
             {"song": "Y", "keep": str(keep), "reject": [], "signatures": {str(keep): [1, "1"]}}]
    p = plan("intake", {"picks": picks})
    assert not p.runnable()
    assert any("not inside a download folder" in x for x in p.problems)
    assert any("changed since the review" in x for x in p.problems)


def test_legacy_djlib_log_import_and_undo(env):
    moved = fake_audio(env.root / "Genres" / "EBM & Industrial" / "Nitzer Ebb - Join in the Chant.mp3")
    log = [{"action": "move", "source": "Tracks/Nitzer Ebb - Join in the Chant.mp3",
            "dest": "Genres/EBM & Industrial/Nitzer Ebb - Join in the Chant.mp3", "batch": "2026-11-08_11-21-37"}]
    (env.root / ".djlib-log.jsonl").write_text("\n".join(json.dumps(e) for e in log), encoding="utf-8")
    with session_scope() as s:
        assert legacy.import_djlib_log(s, env.root / ".djlib-log.jsonl") == 1
        assert legacy.import_djlib_log(s, env.root / ".djlib-log.jsonl") == 0   # safe to run twice
        batch = s.query(Batch).filter_by(legacy_id="2026-11-08_11-21-37").one()
        op = s.query(FileOp).filter_by(batch_id=batch.id).one()
        assert op.source == str(env.root / "Tracks" / moved.name)
        batch_id = batch.id
    library.apply(session_scope, preview("undo", {"batch_id": batch_id}))
    assert (env.root / "Tracks" / moved.name).exists() and not moved.exists()


def test_intake_writes_tags_fills_album_and_undo_restores(env):
    from app.core.tags import read_tags
    from .conftest import real_audio
    from mutagen.id3 import ID3

    keep = real_audio(env.downloads / "02 El que.mp3", title="el que", artist="DAF")
    picks = [{"song": "DAF - El Que", "keep": str(keep), "reject": [], "artist": "Deutsch Amerikanische Freundschaft",
              "title": "El Que", "album": "Gold und Liebe", "year": "1981"}]
    result = library.apply(session_scope, preview("intake", {"picks": picks}))
    assert result["warnings"] == []
    moved = env.root / "00 Inbox" / "Deutsch Amerikanische Freundschaft - El Que.mp3"
    assert read_tags(moved) == {"artist": "Deutsch Amerikanische Freundschaft", "title": "El Que"}
    frames = ID3(moved)
    assert str(frames["TALB"]) == "Gold und Liebe" and str(frames["TDRC"]) == "1981"
    library.apply(session_scope, preview("undo", {"batch_id": result["id"]}))
    assert read_tags(keep) == {"artist": "DAF", "title": "el que"}
    assert "TALB" not in ID3(keep)


def test_fix_tags_from_filename_and_genre_folder_then_undo(env):
    from app.core.tags import read_tags

    from .conftest import real_audio

    genre = real_audio(env.root / "Genres" / "Electro & Nu Rave" / "Crystal Castles - Not In Love.mp3")
    session_copy = env.root / "Sessions" / "Party" / genre.name
    session_copy.parent.mkdir(parents=True, exist_ok=True)
    session_copy.write_bytes(genre.read_bytes())
    good = real_audio(env.root / "Genres" / "Electro & Nu Rave" / "Vitalic - Poison Lips.mp3",
                      title="Poison Lips", artist="Vitalic", frequency=500)
    from app.core.tags import write_tags
    write_tags(good, {"genre": "Electro & Nu Rave"})

    assert plan("tags", {"genre": False}).runnable()[0].tags == {"artist": "Crystal Castles", "title": "Not In Love"}
    p = plan("tags", {"genre": True})
    assert sorted(Path(s.source).name for s in p.runnable()) == [genre.name, genre.name]

    batch = preview("tags", {"genre": True})
    result = library.apply(session_scope, batch)
    assert result["status"] == "applied" and not result["warnings"]
    for path in (genre, session_copy):
        assert read_tags(path) == {"artist": "Crystal Castles", "title": "Not In Love",
                                   "genre": "Electro & Nu Rave"}
    assert plan("tags", {"genre": True}).runnable() == []  # nothing left to fix, and both copies still match

    library.apply(session_scope, preview("undo", {"batch_id": batch}))
    assert read_tags(genre).get("artist") is None and read_tags(genre).get("genre") is None


def test_rename_inbox_file_changes_name_and_tags_then_undo(env):
    from app.core.tags import read_tags

    from .conftest import real_audio

    song = real_audio(env.root / "00 Inbox" / "Somos La Herencia - Hombres Libres.mp3",
                      title="Hombres Libres", artist="Somos La Herencia")
    item = {"source": "00 Inbox/Somos La Herencia - Hombres Libres.mp3", "artist": "Dolo", "title": "Hombres Libres"}
    batch = preview("rename", {"items": [item]})
    result = library.apply(session_scope, batch)
    new = env.root / "00 Inbox" / "Dolo - Hombres Libres.mp3"
    assert result["status"] == "applied" and new.exists() and not song.exists()
    assert read_tags(new)["artist"] == "Dolo"

    library.apply(session_scope, preview("undo", {"batch_id": batch}))
    assert song.exists() and read_tags(song)["artist"] == "Somos La Herencia"

    p = plan("rename", {"items": [{"source": "Genres/X/a.mp3", "artist": "A", "title": "B"}]})
    assert "only files in 00 Inbox" in p.problems[0]


def test_move_from_inbox_applies_name_edits(env):
    from app.core.tags import read_tags

    from .conftest import real_audio

    real_audio(env.root / "00 Inbox" / "VVV - Invierno nuclear.mp3", title="Invierno nuclear", artist="VVV")
    item = {"source": "00 Inbox/VVV - Invierno nuclear.mp3", "to": "Genres/Post-Punk & Dark Wave",
            "action": "move", "artist": "VVV [Trippin'you]", "title": "Invierno nuclear"}
    batch = preview("apply", {"items": [item]})
    library.apply(session_scope, batch)
    new = env.root / "Genres" / "Post-Punk & Dark Wave" / "VVV [Trippin'you] - Invierno nuclear.mp3"
    assert new.exists() and read_tags(new)["artist"] == "VVV [Trippin'you]"
    library.apply(session_scope, preview("undo", {"batch_id": batch}))
    old = env.root / "00 Inbox" / "VVV - Invierno nuclear.mp3"
    assert old.exists() and read_tags(old)["artist"] == "VVV"


def test_move_from_inbox_rejects_empty_title(env):
    from .conftest import real_audio

    real_audio(env.root / "00 Inbox" / "A - B.mp3", title="B", artist="A")
    item = {"source": "00 Inbox/A - B.mp3", "to": "Genres/X", "action": "move", "artist": "A2", "title": " "}
    p = plan("apply", {"items": [item]})
    assert "title cannot be empty" in p.problems[0]


def test_intake_refuses_two_rejects_with_the_same_name(env):
    a = fake_audio(env.downloads / "a" / "Boy Harsher - Pain.mp3", b"a")
    b = fake_audio(env.downloads / "b" / "Boy Harsher - Pain.mp3", b"b")
    p = plan("intake", {"picks": [{"song": "Boy Harsher - Pain", "keep": None, "reject": [str(a), str(b)]}]})
    assert not p.steps and any("already in" in x for x in p.problems)
    p = plan("intake", {"picks": [{"song": "Boy Harsher - Pain", "keep": None, "reject": [str(a), str(a)]}]})
    assert not p.steps and p.problems


def test_remove_lists_each_file_once_and_keeps_one_genre_copy(env):
    fake_audio(env.root / "Genres" / "EBM & Industrial" / "DAF - Kebab.mp3")
    fake_audio(env.root / "Sessions" / "Party" / "DAF - Kebab.mp3")
    p = plan("remove", {"paths": ["Sessions/Party/DAF - Kebab.mp3", "Sessions/Party"]})
    assert len(p.steps) == 1
    # Two genre copies of one song: both listed, only one may go.
    one = env.root / "Genres" / "EBM & Industrial" / "Front 242 - Headhunter.mp3"
    two = env.root / "Genres" / "Synth-Pop & New Wave" / "Front 242 - Headhunter.mp3"
    fake_audio(one, b"h")
    two.write_bytes(one.read_bytes())
    p = plan("remove", {"paths": [str(one.relative_to(env.root)), str(two.relative_to(env.root))]})
    assert len(p.steps) == 1 and "only genre copy" in p.problems[0]


def test_execute_checks_everything_before_moving_anything(env):
    from app.core import library as core

    first = fake_audio(env.root / "00 Inbox" / "A - One.mp3", b"1")
    second = fake_audio(env.root / "00 Inbox" / "B - Two.mp3", b"2")
    taken = fake_audio(env.root / "Genres" / "EBM & Industrial" / "B - Two.mp3", b"3")
    plan_ = core.Plan("apply", steps=[
        core.Step("move", str(first), str(env.root / "Genres" / "EBM & Industrial" / first.name)),
        core.Step("move", str(second), str(taken))])
    with pytest.raises(FileExistsError):
        core.execute(env.root, plan_)
    assert first.exists() and second.exists()   # the first step did not run either


def test_stuck_running_batch_is_recovered(env):
    with session_scope() as s:
        s.add(Batch(kind="apply", status="running", label="x", request={}, plan={"steps": []}))
    with session_scope() as s:
        assert library.recover_batches(s) == 1
        assert s.query(Batch).one().status == "failed"


def test_undo_with_problems_is_partial(env):
    song = fake_audio(env.root / "00 Inbox" / "A - One.mp3")
    other = fake_audio(env.root / "00 Inbox" / "B - Two.mp3")
    items = [{"source": f"00 Inbox/{n}", "to": "Genres/EBM & Industrial", "action": "move"}
             for n in (song.name, other.name)]
    batch = preview("apply", {"items": items})
    library.apply(session_scope, batch)
    (env.root / "Genres" / "EBM & Industrial" / song.name).unlink()
    undo = preview("undo", {"batch_id": batch})
    result = library.apply(session_scope, undo)
    assert result["status"] == "partial"
    with session_scope() as s:
        assert s.get(Batch, batch).status == "applied"   # not marked undone


def test_rename_edge_cases(env):
    from .conftest import real_audio
    from app.core.tags import read_tags

    real_audio(env.root / "00 Inbox" / "Some Band - Song.mp3", title="Song", artist="Some Band")
    src = "00 Inbox/Some Band - Song.mp3"
    p = plan("rename", {"items": [{"source": src, "artist": "Some Band", "title": "..."}]})
    assert not p.problems   # a title that cleans to nothing keeps the file name instead of crashing
    # No artist key: the artist tag is left alone.
    batch = preview("rename", {"items": [{"source": src, "title": "New Song"}]})
    library.apply(session_scope, batch)
    new = next((env.root / "00 Inbox").glob("*New Song*"))
    assert read_tags(new) == {"artist": "Some Band", "title": "New Song"}
    # A case-only rename works.
    batch = preview("rename", {"items": [{"source": "00 Inbox/" + new.name, "artist": "SOME BAND", "title": "New Song"}]})
    library.apply(session_scope, batch)
    assert read_tags(next((env.root / "00 Inbox").glob("*New Song*")))["artist"] == "SOME BAND"


def test_write_tags_keeps_id3v24(env):
    from mutagen.id3 import ID3, TIT2
    from app.core.tags import write_tags
    from .conftest import real_audio

    path = real_audio(env.tmp / "x.mp3", title="x", artist="y")
    tag = ID3(path)
    tag.add(TIT2(encoding=3, text=["x"]))
    tag.save(path, v2_version=4)
    write_tags(path, {"title": "z"})
    assert ID3(path).version[:2] == (2, 4)


def test_scan_sync_clears_hash_when_file_changes(env):
    from app.models import File
    from sqlalchemy import select

    song = fake_audio(env.root / "00 Inbox" / "A - One.mp3")
    with session_scope() as s:
        library.sync_library(s)
        row = s.scalar(select(File).where(File.path == str(song)))
        row.sha256 = "abc"
    song.write_bytes(song.read_bytes()[:-1] + b"y")   # same size, different mtime
    import os
    os.utime(song, ns=(1, 1))
    with session_scope() as s:
        library.sync_library(s)
        assert s.scalar(select(File).where(File.path == str(song))).sha256 is None


def test_intent_is_logged_before_a_move_and_dropped_when_it_fails(env, monkeypatch):
    from app.core import library as core

    a = fake_audio(env.root / "00 Inbox" / "A - One.mp3", b"1")
    b = fake_audio(env.root / "00 Inbox" / "B - Two.mp3", b"2")
    items = [{"source": f"00 Inbox/{p.name}", "to": "Genres/EBM & Industrial", "action": "move"} for p in (a, b)]
    batch = preview("apply", {"items": items})
    real_move = core.shutil.move
    seen = []

    def flaky(source, dest):
        with session_scope() as s:   # the intent is already in the database when the file moves
            seen.append(s.query(FileOp).filter_by(batch_id=batch).count())
        if "B - Two" in str(source):
            raise OSError("disk went away")
        return real_move(source, dest)
    monkeypatch.setattr(core.shutil, "move", flaky)
    result = library.apply(session_scope, batch)
    assert seen == [1, 2] and result["status"] == "partial"
    with session_scope() as s:
        ops = s.query(FileOp).filter_by(batch_id=batch).all()
        assert [Path(o.source).name for o in ops] == ["A - One.mp3"]   # the failed move left no row
    assert b.exists() and not a.exists()


def test_recovery_keeps_moves_that_happened_and_drops_those_that_did_not(env):
    done = fake_audio(env.root / "Genres" / "EBM & Industrial" / "A - One.mp3")
    with session_scope() as s:
        batch = Batch(kind="apply", status="running", label="x", request={}, plan={"steps": []})
        s.add(batch)
        s.flush()
        s.add(FileOp(batch_id=batch.id, seq=1, action="move", source=str(env.root / "00 Inbox" / "A - One.mp3"),
                     dest=str(done)))
        s.add(FileOp(batch_id=batch.id, seq=2, action="move", source=str(env.root / "00 Inbox" / "B - Two.mp3"),
                     dest=str(env.root / "Genres" / "EBM & Industrial" / "B - Two.mp3")))
    with session_scope() as s:
        assert library.recover_batches(s) == 1
    with session_scope() as s:
        assert s.query(Batch).one().status == "partial"
        assert s.query(FileOp).count() == 1
