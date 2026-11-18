from app.core.soulseek import Result, choose, is_wanted

QUERY = "Joy Division Love Will Tear Us Apart"


def result(user="u", path="Music\\Joy Division\\Joy Division - Love Will Tear Us Apart.mp3", bitrate=320,
           free=True, queue=0, speed=100, size=8_000_000):
    return Result(user, path, size, bitrate, free, queue, speed)


def test_only_mp3_at_the_minimum_bitrate():
    assert is_wanted(result(), QUERY, 320)
    assert not is_wanted(result(bitrate=256), QUERY, 320)
    assert not is_wanted(result(bitrate=None), QUERY, 320)
    assert not is_wanted(result(path=result().path.replace(".mp3", ".flac")), QUERY, 320)


def test_path_must_hold_every_word_of_the_query():
    assert is_wanted(result(path="x\\JOY DIVISION - love will tear us apart (1979).mp3"), QUERY, 320)
    assert not is_wanted(result(path="x\\Joy Division - Disorder.mp3"), QUERY, 320)


def test_other_versions_are_dropped_unless_asked_for():
    remix = result(path="x\\Joy Division - Love Will Tear Us Apart (Remix).mp3")
    assert not is_wanted(remix, QUERY, 320)
    assert is_wanted(remix, QUERY + " remix", 320)


def test_choose_keeps_one_per_peer_ranked_by_slots_queue_and_speed():
    results = [result("busy", queue=50), result("free-slow", speed=10), result("free-fast", speed=500),
               result("no-slots", free=False),
               result("free-fast", path="y\\Joy Division - Love Will Tear Us Apart.mp3"),
               result("low", bitrate=192)]
    picked = choose(results, QUERY, 320, count=10)
    assert [r.username for r in picked] == ["free-fast", "free-slow", "busy", "no-slots"]
    assert [r.username for r in choose(results, QUERY, 320, count=2)] == ["free-fast", "free-slow"]


def test_settings_default_and_change(client):
    assert client.get("/api/settings").json()["soulseek"] == {"min_bitrate": 320, "candidates": 10}
    body = client.put("/api/settings", json={"soulseek_candidates": 5}).json()
    assert body["soulseek"] == {"min_bitrate": 320, "candidates": 5}
    assert client.put("/api/settings", json={"soulseek_min_bitrate": 64}).status_code == 422


def test_download_uses_the_settings_and_the_first_download_folder(env, monkeypatch):
    from app.integrations import soulseek as client
    from app.services import soulseek as service
    seen = {}

    def fake_fetch(query, pick, dest, share=(), echo=print):
        seen.update(query=query, dest=dest, share=list(share), picked=pick([result(f"u{i}") for i in range(15)]))
        return {"found": 15, "files": []}

    monkeypatch.setattr(client, "fetch", fake_fetch)
    out = service.download(QUERY)
    assert seen["dest"] == env.downloads / "Soulseek" and out["folder"] == str(env.downloads / "Soulseek")
    assert len(seen["picked"]) == 10
    assert seen["share"] == [env.root / "Genres"]   # only the sorted library is shared


def test_missing_login_says_what_to_do(env):
    import pytest
    from app.integrations import soulseek as client
    with pytest.raises(client.SoulseekError, match="SOULSEEK_USERNAME"):
        client.credentials()
