"""Dual-license notices are allowed only when explicitly co-offered. NC/ND stay conflicts."""
import tempfile
import unittest
from pathlib import Path

from license_notice import detected_licenses, license_notice_conflicts


def _notice(text):
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(text.encode('utf-8'))
    tmp.close()
    return Path(tmp.name)


class LicenseNoticeTests(unittest.TestCase):
    def conflicts(self, text, declared, co_offered=()):
        path = _notice(text)
        self.addCleanup(path.unlink)
        return license_notice_conflicts(path, declared, co_offered)

    def test_unversioned_cc_by_sa_and_gfdl_conflicts_until_co_offered(self):
        notice = 'made available under the same licenses as Wiktionary - both CC-BY-SA and GFDL'
        self.assertEqual(
            detected_licenses(notice),
            frozenset({'CC-BY-SA-4.0', 'GFDL-1.3-only'}),
        )
        self.assertTrue(self.conflicts(notice, 'CC-BY-SA-4.0'))
        self.assertFalse(self.conflicts(
            notice, 'CC-BY-SA-4.0', ['GFDL-1.3-only']))

    def test_versioned_dual_license_same_rule(self):
        notice = 'Available under CC BY-SA 4.0 and the GNU Free Documentation License 1.3.'
        self.assertTrue(self.conflicts(notice, 'CC-BY-SA-4.0'))
        self.assertFalse(self.conflicts(
            notice, 'CC-BY-SA-4.0', ('GFDL-1.3-only',)))

    def test_nc_and_nd_cannot_be_waived_by_co_offered_licenses(self):
        notice = 'Official license: CC BY-NC-SA 4.0 and GFDL 1.3'
        self.assertTrue(self.conflicts(
            notice, 'CC-BY-SA-4.0', ['GFDL-1.3-only']))
        self.assertTrue(self.conflicts(
            'Attribution-NonCommercial-ShareAlike 4.0', 'CC0-1.0', ['CC-BY-SA-4.0']))
        self.assertTrue(self.conflicts('CC BY-ND 4.0', 'CC0-1.0'))
        self.assertTrue(self.conflicts(
            'CC BY-SA 4.0', 'CC-BY-SA-4.0', ['CC-BY-NC-4.0']))

    def test_single_declared_license_is_not_a_conflict(self):
        self.assertFalse(self.conflicts('Publisher states CC0 1.0.', 'CC0-1.0'))
        self.assertFalse(self.conflicts('CC BY-SA 4.0 only.', 'CC-BY-SA-4.0'))
        self.assertTrue(self.conflicts('CC BY-SA 4.0 only.', 'CC0-1.0'))

    def test_cc_by_sa_3_0_is_not_relabeled_as_4_0(self):
        found = detected_licenses('CC BY-SA 3.0 Unported')
        self.assertNotIn('CC-BY-SA-4.0', found)
        self.assertIn('CC-BY-SA-3.0', found)

    def test_unknown_nc_version_conflicts_with_cc0(self):
        self.assertEqual(detected_licenses('CC BY-NC 3.0'), frozenset({'CC-BY-NC-3.0'}))
        self.assertTrue(self.conflicts('CC BY-NC 3.0', 'CC0-1.0'))
        self.assertTrue(self.conflicts('CC BY-ND 3.0', 'CC0-1.0'))
        # NC/ND stay conflicts even when the declared id is that same unknown version.
        self.assertTrue(self.conflicts('CC BY-NC 3.0', 'CC-BY-NC-3.0'))

    def test_unknown_sa_version_conflicts_unless_it_is_the_declared_license(self):
        self.assertEqual(detected_licenses('CC BY-SA 3.0'), frozenset({'CC-BY-SA-3.0'}))
        self.assertTrue(self.conflicts('CC BY-SA 3.0', 'CC-BY-SA-4.0'))
        self.assertFalse(self.conflicts('CC BY-SA 3.0', 'CC-BY-SA-3.0'))

    def test_wikidata_attribution_sharealike_3_0_wording_still_passes_for_cc0(self):
        # The public Wikidata copyright page names Attribution-ShareAlike 3.0 in a
        # wiki link beside the CC0 dedication. That wording is not a CC-BY-SA id.
        notice = (
            'All structured data from the main, Property, Lexeme, and EntitySchema '
            'namespaces is available under the [[Wikidata:Text of the Creative Commons '
            'Public Domain Dedication|Creative Commons CC0 License]]; text in the other '
            'namespaces is available under the [[Wikidata:Text of Creative Commons '
            'Attribution-ShareAlike 3.0 Unported License|Creative Commons '
            'Attribution-ShareAlike License]]; additional terms may apply.'
        )
        found = detected_licenses(notice)
        self.assertNotIn('CC-BY-SA-3.0', found)
        self.assertNotIn('CC-BY-SA-4.0', found)
        self.assertFalse(self.conflicts(notice, 'CC0-1.0'))
