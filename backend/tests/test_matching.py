import unittest

from app.core import matching as c
from app.core.names import guess_from_filename
from app.integrations.spotify import parse_playlist_id


def local(artist, title, path=None):
    return {"artist": artist, "title": title, "filename_artist": "", "filename_title": "",
            "relative_path": path or f"{artist} - {title}.mp3", "path": f"/x/{artist} - {title}.mp3"}


def spotify(artists, title):
    return {"spotify_id": "x" * 22, "artists": artists, "title": title}


class MatchingTest(unittest.TestCase):
    def match(self, track, library):
        return c.match_track(track, c.build_index(library))["status"]

    def test_exact_match(self):
        self.assertEqual(self.match(spotify(["Soft Cell"], "Tainted Love"), [local("Soft Cell", "Tainted Love")]), "have")

    def test_remaster_suffix_is_same_track(self):
        lib = [local("The Smiths", "There Is A Light That Never Goes Out")]
        self.assertEqual(self.match(spotify(["The Smiths"], "There Is a Light That Never Goes Out - 2011 Remaster"), lib), "have")

    def test_remix_is_flagged(self):
        lib = [local("Daft Punk", "Around the World")]
        self.assertEqual(self.match(spotify(["Daft Punk"], "Around the World - Tom Trago Remix"), lib), "maybe")

    def test_artist_typo_still_matches_by_tag(self):
        lib = [local("Bronski Beat", "Smalltown Boy", "Bronsky Beat - Smalltown Boy.mp3")]
        self.assertEqual(self.match(spotify(["Bronski Beat"], "Smalltown Boy"), lib), "have")

    def test_title_typo_is_possible_match(self):
        self.assertEqual(self.match(spotify(["Billy Idol"], "Rebel Yell"), [local("Billy Idol", "Rebell Yell")]), "maybe")

    def test_shared_article_is_not_artist_match(self):
        lib = [local("The Rapture", "How Deep Is Your Love")]
        self.assertEqual(self.match(spotify(["The Outfield"], "Your Love"), lib), "missing")

    def test_one_shared_word_is_not_the_same_artist(self):
        lib = [local("Beastie Boys", "Domino")]
        self.assertEqual(self.match(spotify(["Pet Shop Boys"], "Domino"), lib), "maybe")   # same title, other artist
        self.assertEqual(self.match(spotify(["John Foxx"], "Domino"), [local("John Lennon", "Domino")]), "maybe")

    def test_featured_and_joint_artists_still_agree(self):
        self.assertEqual(self.match(spotify(["Soft Cell", "Marc Almond"], "Tainted Love"),
                                    [local("Soft Cell", "Tainted Love")]), "have")
        self.assertEqual(self.match(spotify(["Soft Cell"], "Tainted Love"),
                                    [local("Soft Cell & Marc Almond", "Tainted Love")]), "have")
        self.assertEqual(self.match(spotify(["The Cure"], "A Forest"), [local("Cure", "A Forest")]), "have")

    def test_missing(self):
        self.assertEqual(self.match(spotify(["a-ha"], "Take on Me"), [local("Devo", "Whip It")]), "missing")

    def test_filename_parsing(self):
        self.assertEqual(guess_from_filename("60 - Technotronic - Pump Up The Jam"),
                         {"artist": "Technotronic", "title": "Pump Up The Jam"})
        self.assertEqual(guess_from_filename("07 Another World"), {"title": "Another World"})

    def test_playlist_id_parsing(self):
        pid = "37i9dQZF1DX4UtSsGT1Sbe"
        self.assertEqual(parse_playlist_id(f"https://open.spotify.com/playlist/{pid}?si=abc"), pid)
        self.assertEqual(parse_playlist_id(f"spotify:playlist:{pid}"), pid)
        self.assertEqual(parse_playlist_id(pid), pid)


if __name__ == "__main__":
    unittest.main()

