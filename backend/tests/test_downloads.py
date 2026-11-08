import json
import re
import tempfile
import unittest
from pathlib import Path

from app.core import downloads as rd, names
from app.core.audio import decoder_problems


def item(name, **extra):
    base = {'path': f'/dl/{name}', 'name': name, 'tag_artist': '', 'tag_title': '', 'album': '', 'year': '',
            'has_art': False, 'bitrate_kbps': 320, 'codec': 'mp3', 'status': 'OK', 'corrupt_frames': 0,
            'duration_seconds': 250.0, 'true_peak_dbtp': -0.5, 'hf_gap_19k_db': 60.0, 'sha256': name,
            'audio_md5': name}
    base.update(extra)
    return base


class Names(unittest.TestCase):
    def test_parse_real_filename_shapes(self):
        cases = {
            '02 Port Isabel (1)': ('', 'Port Isabel'),
            'Led Er Est - Port Isabel': ('Led Er Est', 'Port Isabel'),
            '07 - Boy Harsher - Tears': ('Boy Harsher', 'Tears'),
            'Boy Harsher - Careful - 07 - Tears': ('Boy Harsher', 'Tears'),
            '03-kontravoid_chelsey_crowley-losing_game-e91d69c1': ('kontravoid chelsey crowley', 'losing game'),
            '2-05 Dead Souls': ('', 'Dead Souls'),
            '0888 - Sisters Of Mercy - Temple Of Love': ('Sisters Of Mercy', 'Temple Of Love'),
            '3 Take Me Higher - QUAL': ('Take Me Higher', 'QUAL'),
        }
        for stem, expected in cases.items():
            self.assertEqual(names.parse_download_filename(stem), expected, stem)

    def test_split_version(self):
        self.assertEqual(names.split_version('Marian (Remastered)')[:2], ('Marian', 'Remastered'))
        self.assertEqual(names.split_version('Last In The Club (Album Version)')[:2], ('Last In The Club', 'Album Version'))
        self.assertEqual(names.split_version('Losing Game [ft. Chelsey Crowley]')[0], 'Losing Game')
        self.assertEqual(names.split_version('Losing Game feat. Chelsey Crowley')[0], 'Losing Game')
        base, _, remix = names.split_version('Street Pulse Beat [Boy Harsher Remix]')
        self.assertTrue(remix)
        self.assertIn('Remix', base)

    def test_normalize(self):
        self.assertEqual(names.normalize("Ricky’s Hand"), names.normalize("Ricky's Hand"))
        self.assertEqual(names.normalize('Ricky\x92s Hand'), names.normalize("Ricky's Hand"))
        self.assertEqual(names.normalize('The Sisters of Mercy'), names.normalize('Sisters Of Mercy'))
        self.assertEqual(names.normalize('Durdu Dünya'), names.normalize('Durdu Dunya'))
        self.assertEqual(names.normalize('Rendez-Vous'), names.normalize('Rendez Vous'))


class Grouping(unittest.TestCase):
    def test_tags_and_untagged_files_join(self):
        items = [item('02 Port Isabel.mp3', tag_artist='Led Er Est', tag_title='Port Isabel'),
                 item('Led Er Est - Port Isabel.mp3'),
                 item('02 Port Isabel (1).mp3'),
                 item('05 Marian (Remastered).mp3', tag_artist='The Sisters Of Mercy', tag_title='Marian (Remastered)'),
                 item('05 - Marian (Version).mp3', tag_artist='The Sisters of Mercy', tag_title='Marian (Version)'),
                 item('Special Interest - Street Pulse Beat [Boy Harsher Remix].mp3'),
                 item('Special Interest - Street Pulse Beat.mp3')]
        groups = sorted(sorted(i['name'] for i in g) for g in rd.group_files(items))
        self.assertIn(['02 Port Isabel (1).mp3', '02 Port Isabel.mp3', 'Led Er Est - Port Isabel.mp3'], groups)
        self.assertIn(['05 - Marian (Version).mp3', '05 Marian (Remastered).mp3'], groups)
        self.assertIn(['Special Interest - Street Pulse Beat [Boy Harsher Remix].mp3'], groups)


class Suggestion(unittest.TestCase):
    def test_identical_and_same_audio(self):
        a = item('a.mp3', sha256='x', audio_md5='m')
        b = item('b (1).mp3', sha256='x', audio_md5='m')
        c = item('c.mp3', sha256='y', audio_md5='m')
        rd.annotate_group([a, b, c])
        self.assertEqual(a['identical_to'], ['b (1).mp3'])
        self.assertEqual(a['same_audio_as'], ['c.mp3'])
        self.assertEqual(c['same_audio_as'], ['a.mp3', 'b (1).mp3'])

    def test_order(self):
        transcode = item('fake.mp3', hf_gap_19k_db=100.0, tag_artist='A', tag_title='T', album='X', has_art=True)
        broken = item('broken.mp3', corrupt_frames=3)
        edit = item('edit.mp3', duration_seconds=200.0)
        low = item('low.mp3', bitrate_kbps=192)
        compilation = item('comp.mp3', album='Best of the 80s')
        good = item('good.mp3', album='Album')
        copy = item('good (1).mp3', album='Album')
        items = [transcode, broken, edit, low, compilation, copy, good, item('good2.mp3', album='Album')]
        self.assertEqual(rd.annotate_group(items), good['path'])
        ranked = [i['name'] for i in sorted(items, key=lambda i: i['rank'])]
        self.assertEqual(ranked[-1], 'fake.mp3')
        self.assertLess(ranked.index('comp.mp3'), ranked.index('low.mp3'))
        self.assertLess(ranked.index('low.mp3'), ranked.index('edit.mp3'))
        self.assertLess(ranked.index('edit.mp3'), ranked.index('broken.mp3'))
        self.assertLess(ranked.index('good.mp3'), ranked.index('good (1).mp3'))
        self.assertTrue(transcode['likely_transcode'])
        self.assertTrue(edit['other_edit'])
        self.assertIn('From a compilation', compilation['warnings'])


class Analyzer(unittest.TestCase):
    def test_metadata_is_not_a_decoder_problem(self):
        stderr = ('    artist          : Futuro Terror\n    title           : Invalid Love\n'
                  '[mp3float @ 0x1] Header missing\n'
                  '[aist#0:0/mp3 @ 0x2] Error submitting packet to decoder: Invalid data found\n')
        self.assertEqual(decoder_problems(stderr),
                         ['[aist#0:0/mp3 @ 0x2] Error submitting packet to decoder: Invalid data found'])


if __name__ == '__main__':
    unittest.main()
