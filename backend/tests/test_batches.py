"""File changes: the library rules, dry runs, apply, undo, and refusing stale previews."""
import json

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
