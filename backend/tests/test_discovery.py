import pytest

from app.core import discovery as d
from app.integrations.lastfm import Lastfm
from app.db import session_scope
from app.models import File
from app.services import discovery as service


def local(artist, title):
    return {"artist": artist, "title": title, "filename_artist": "", "filename_title": "",
            "relative_path": f"{artist} - {title}.mp3", "path": f"/x/{artist} - {title}.mp3"}


def test_artist_reached_from_two_seeds_beats_one_seed():
    seeds = {"A": 1, "B": 1}
    similar = {"A": [("X", 0.9), ("Y", 0.9)], "B": [("X", 0.5)]}
    ranked = d.score_artists(seeds, similar)
    assert [r["artist"] for r in ranked] == ["X", "Y"]
    assert ranked[0]["because"] == ["A", "B"]


def test_seed_weight_counts_and_seeds_are_excluded():
    seeds = {"A": 25, "B": 1}
    similar = {"A": [("B", 1.0), ("X", 0.2)], "B": [("Y", 0.9)]}
    ranked = d.score_artists(seeds, similar)
    assert [r["artist"] for r in ranked] == ["X", "Y"]  # B is a seed; sqrt(25)*0.2 > 1*0.9


def test_one_heavy_seed_does_not_beat_several_agreeing_seeds():
    seeds = {"Heavy": 17, "B": 4, "C": 4, "D": 2}
    similar = {"Heavy": [("Offshoot", 1.0), ("Broad", 0.8)],
               "B": [("Broad", 0.8)], "C": [("Broad", 0.8)], "D": [("Broad", 0.8)]}
    ranked = d.score_artists(seeds, similar)
    assert [r["artist"] for r in ranked] == ["Broad", "Offshoot"]


def test_owned_tracks_and_dismissed_are_dropped_and_other_versions_flagged():
    artists = [{"artist": "X", "score": 1.0, "because": ["A"]}]
    tops = {"X": ["Owned Song", "New Song", "Dismissed", "Song (Club Remix)"]}
    library = [local("X", "Owned Song"), local("X", "Song")]
    out = d.candidate_tracks(artists, tops, library, dismissed={("x", "dismissed")})
    assert [c["title"] for c in out] == ["New Song", "Song (Club Remix)"]
    assert out[1]["check"] is not None and out[0]["check"] is None


def fake_fetch(params):
    if params["method"] == "artist.getsimilar":
        return {"similarartists": {"artist": [{"name": "Newcomer", "match": "0.8"}]}}
    return {"toptracks": {"track": [{"name": "Fresh"}, {"name": "Known"}]}}


def test_service_end_to_end_with_fake_lastfm(env):
    with session_scope() as s:
        for title in ("One", "Two"):
            s.add(File(path=f"/lib/Genres/EBM & Industrial/{title}.mp3", area="library", kind="genre",
                       folder="EBM & Industrial", rel_path=f"Genres/EBM & Industrial/{title}.mp3",
                       artist="Seed Band", title=title))
        s.add(File(path="/lib/Genres/Synth-Pop & New Wave/Known.mp3", area="library", kind="genre",
                   folder="Synth-Pop & New Wave", rel_path="Genres/Synth-Pop & New Wave/Known.mp3",
                   artist="Newcomer", title="Known"))
    with session_scope() as s:
        result = service.discover(s, "EBM & Industrial", client=Lastfm(key="k", fetch=fake_fetch))
    assert result["seeds"] == {"Seed Band": 2}
    assert [(c["artist"], c["title"]) for c in result["candidates"]] == [("Newcomer", "Fresh")]
    with session_scope() as s, pytest.raises(service.UnknownGenre):
        service.discover(s, "Nope", client=Lastfm(key="k", fetch=fake_fetch))


def test_split_artists_handles_collaboration_tags():
    assert d.split_artists("Nine Inch Nails & Boyz Noise") == ["Nine Inch Nails", "Boyz Noise"]
    assert d.split_artists("A feat. B, C") == ["A", "B", "C"]
    assert d.split_artists("Nitzer Ebb") == ["Nitzer Ebb"]


def test_acronym_artist_is_recognised_as_owned():
    library = [local("D.A.F.", "Der Mussolini")]
    artists = [{"artist": "Deutsch Amerikanische Freundschaft", "score": 1.0, "because": ["A"]}]
    out = d.candidate_tracks(artists, {artists[0]["artist"]: ["Alle Gegen Alle"]}, library)
    assert out[0]["you_own"] == 1


def test_unknown_collaboration_seed_is_split_first_artist_gets_full_weight(env):
    calls = []

    def fetch(params):
        if params["method"] == "artist.getsimilar":
            calls.append(params["artist"])
            known = {"Nine Inch Nails": [{"name": "Skinny Puppy", "match": "1"}]}
            return {"similarartists": {"artist": known.get(params["artist"], [])}}
        return {"toptracks": {"track": [{"name": "Assimilate"}]}}

    similar, used = service._similar_for(Lastfm(key="k", fetch=fetch),
                                         {"Nine Inch Nails & Boyz Noise": 12, "Nine Inch Nails": 5})
    assert used == {"Nine Inch Nails": 17, "Boyz Noise": 3}  # first artist full weight, others 25%
    assert similar["Nine Inch Nails"] and similar["Boyz Noise"] == []


def test_same_song_under_an_artist_alias_counts_as_owned():
    library = [local("D.A.F.", "Der Mussolini")]
    name = "Deutsch Amerikanische Freundschaft"
    artists = [{"artist": name, "score": 1.0, "because": ["A"]}]
    out = d.candidate_tracks(artists, {name: ["Der Mussolini", "Alle Gegen Alle"]}, library)
    assert [c["title"] for c in out] == ["Alle Gegen Alle"]


def _seed_library(s):
    for title in ("One", "Two"):
        s.add(File(path=f"/lib/Genres/EBM & Industrial/{title}.mp3", area="library", kind="genre",
                   folder="EBM & Industrial", rel_path=f"Genres/EBM & Industrial/{title}.mp3",
                   artist="Seed Band", title=title))


def _run(s):
    result = service.discover(s, "EBM & Industrial", client=Lastfm(key="k", fetch=fake_fetch))
    return service.save(s, result)


def test_save_keeps_status_and_dismissed_never_return(env):
    with session_scope() as s:
        _seed_library(s)
        rows = _run(s)
        assert [(r.artist, r.title, r.status) for r in rows] == [("Newcomer", "Fresh", "new"),
                                                                 ("Newcomer", "Known", "new")]
    with session_scope() as s:
        ids = {r["title"]: r["id"] for r in service.list_candidates(s)}
        service.set_status(s, [ids["Fresh"]], "wanted")
        service.set_status(s, [ids["Known"]], "dismissed")
    with session_scope() as s:
        rows = _run(s)  # a second run: wanted stays wanted, dismissed is not suggested again
        assert [(r.title, r.status) for r in rows] == [("Fresh", "wanted")]
        assert [r["title"] for r in service.list_candidates(s, status="dismissed")] == ["Known"]
    with session_scope() as s, pytest.raises(KeyError):
        service.set_status(s, [9999], "wanted")
    with session_scope() as s, pytest.raises(ValueError):
        service.set_status(s, [ids["Fresh"]], "maybe")


def test_candidates_show_playlists_that_already_have_the_song(env):
    from app.models import Playlist, PlaylistTrack
    with session_scope() as s:
        _seed_library(s)
        s.add(Playlist(id="p" * 22, name="Feel the darkness", project="Serge Candel"))
        s.flush()
        s.add(PlaylistTrack(playlist_id="p" * 22, position=0, spotify_id="s" * 22,
                            title="Fresh - 2011 Remaster", artists=["Newcomer"]))
        _run(s)
        rows = {r["title"]: r for r in service.list_candidates(s)}
        assert rows["Fresh"]["in_playlists"] == [{"playlist": "Feel the darkness", "project": "Serge Candel"}]
        assert rows["Known"]["in_playlists"] == []


def test_candidates_api(client, env):
    with session_scope() as s:
        _seed_library(s)
        _run(s)
    rows = client.get("/api/candidates").json()
    assert [r["title"] for r in rows] == ["Fresh", "Known"]
    assert client.put("/api/candidates/status", json={"ids": [rows[0]["id"]], "status": "wanted"}).json() == {"changed": 1}
    assert [r["title"] for r in client.get("/api/candidates", params={"status": "wanted"}).json()] == ["Fresh"]
    assert client.put("/api/candidates/status", json={"ids": [rows[0]["id"]], "status": "x"}).status_code == 400
    assert client.put("/api/candidates/status", json={"ids": [999], "status": "wanted"}).status_code == 404


def test_discover_job_stores_candidates_and_reports_errors(env, monkeypatch):
    from app.integrations import lastfm
    from app.jobs import runner
    from app.models import Job
    monkeypatch.setattr(lastfm, "http_fetch", fake_fetch)
    monkeypatch.setenv("LASTFM_API_KEY", "k")
    with session_scope() as s:
        _seed_library(s)
    job_id = runner.run_sync("discover", {"genre": "EBM & Industrial"}, echo=None)
    with session_scope() as s:
        job = s.get(Job, job_id)
        assert (job.status, job.summary["candidates"], job.summary["new"]) == ("done", 2, 2)
        assert len(service.list_candidates(s)) == 2
    bad = runner.run_sync("discover", {"genre": "Nope"}, echo=None)
    with session_scope() as s:
        job = s.get(Job, bad)
        assert job.status == "failed" and "No songs in genre folder" in job.message


def test_genres_endpoint_and_missing_genre(client, env):
    with session_scope() as s:
        _seed_library(s)
    assert client.get("/api/candidates/genres").json() == ["EBM & Industrial"]


def test_lastfm_answers_are_cached_for_a_day_without_the_key(env):
    import datetime as dt

    from app.db import session_scope
    from app.models import LastfmCache, now
    from app.services.discovery import cached_fetch

    calls = []

    def fetch(params):
        calls.append(params)
        return {"error": 6, "message": "bad"} if params["artist"] == "bad" else {"ok": params["artist"]}

    cached = cached_fetch(fetch)
    params = {"method": "artist.getsimilar", "api_key": "SECRET", "artist": "DAF", "limit": 30}
    assert cached(params) == {"ok": "DAF"} and cached({**params, "api_key": "OTHER"}) == {"ok": "DAF"}
    assert len(calls) == 1   # the second call came from the cache, whatever the key
    with session_scope() as s:
        row = s.query(LastfmCache).one()
        assert "SECRET" not in row.key and "SECRET" not in str(row.payload)
        row.fetched_at = now() - dt.timedelta(days=2)   # a stale answer is fetched again
    cached(params)
    assert len(calls) == 2
    cached({**params, "artist": "bad"}), cached({**params, "artist": "bad"})
    assert len(calls) == 4   # errors are never cached
