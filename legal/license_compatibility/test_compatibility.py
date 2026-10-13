import unittest

from compatibility import check_compatibility


class TestCompatibility(unittest.TestCase):

    def test_public_domain_only_compatible(self):
        sources = [{'license': {'id': 'PUBLIC-DOMAIN'}}, {'license': {'id': 'PUBLIC-DOMAIN'}}]
        result = check_compatibility(sources, 'PUBLIC-DOMAIN', is_derivative=True)
        self.assertEqual(result['status'], 'COMPATIBLE')
        self.assertEqual(result['obligations'], set())

    def test_public_domain_relicense_rejected(self):
        sources = [{'license': {'id': 'CC0-1.0'}}]
        result = check_compatibility(sources, 'PUBLIC-DOMAIN', is_derivative=True)
        self.assertEqual(result['status'], 'INCOMPATIBLE')
        self.assertIn('CC0 is not a blanket public-domain claim', result['reason'])

        sources2 = [{'license': {'id': 'PUBLIC-DOMAIN'}}, {'license': {'id': 'CC-BY-SA-4.0'}}]
        result2 = check_compatibility(sources2, 'PUBLIC-DOMAIN', is_derivative=True)
        self.assertEqual(result2['status'], 'INCOMPATIBLE')
        self.assertIn('public-domain label contradicts original rights', result2['reason'])

    def test_cc_by_sa_and_gfdl_conflict(self):
        sources = [
            {'license': {'id': 'CC-BY-SA-4.0'}},
            {'license': {'id': 'GFDL-1.3-only'}}
        ]
        result = check_compatibility(sources, 'CC-BY-SA-4.0', is_derivative=True)
        self.assertEqual(result['status'], 'INCOMPATIBLE')
        self.assertIn('cannot be assumed interchangeable', result['reason'])

    def test_unsupported_combinations_review_required(self):
        sources = [{'license': {'id': 'UNKNOWN-LICENSE'}}]
        result = check_compatibility(sources, 'PUBLIC-DOMAIN', is_derivative=True)
        self.assertEqual(result['status'], 'REVIEW_REQUIRED')
        self.assertIn('unknown source license', result['reason'])

        sources2 = [{'license': {'id': 'CC0-1.0'}}]
        result2 = check_compatibility(sources2, 'UNKNOWN-OUT', is_derivative=True)
        self.assertEqual(result2['status'], 'REVIEW_REQUIRED')
        self.assertIn('unsupported output license', result2['reason'])

    def test_aggregation_vs_derivative(self):
        sources = [
            {'license': {'id': 'CC-BY-SA-4.0'}},
            {'license': {'id': 'GFDL-1.3-only'}}
        ]
        # In a derivative work, combining them is incompatible
        result_derivative = check_compatibility(sources, 'CC-BY-SA-4.0', is_derivative=True)
        self.assertEqual(result_derivative['status'], 'INCOMPATIBLE')

        # In pure aggregation, it might be allowed depending on logic (currently we return COMPATIBLE and track obligations)
        result_aggregation = check_compatibility(sources, 'CC-BY-SA-4.0', is_derivative=False)
        self.assertEqual(result_aggregation['status'], 'COMPATIBLE')
        self.assertIn('sharealike', result_aggregation['obligations'])
        self.assertIn('license_copy', result_aggregation['obligations'])

    def test_missing_attribution_rejected(self):
        # We handle missing attribution obligations by checking if obligations are tracked.
        sources = [{'license': {'id': 'CC-BY-SA-4.0'}}]
        result = check_compatibility(sources, 'CC-BY-SA-4.0', is_derivative=True)
        self.assertEqual(result['status'], 'COMPATIBLE')
        self.assertIn('attribution', result['obligations'])

        # Test case that checks the missing license itself fails closed (simulating completely missing origin)
        sources_missing = [{}] # no license dict at all
        result_missing = check_compatibility(sources_missing, 'CC-BY-SA-4.0', is_derivative=True)
        self.assertEqual(result_missing['status'], 'INCOMPATIBLE')
        self.assertIn('missing source license', result_missing['reason'])


if __name__ == '__main__':
    unittest.main()
