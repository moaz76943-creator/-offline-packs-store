import unittest
from community.review.state_machine import safe_name

class TestSafeName(unittest.TestCase):
    def test_valid_safe_name(self):
        valid_names = [
            "a",
            "A",
            "1",
            "abc",
            "a_b-c",
            "A-B_C",
            "A123",
            "a" * 80,
            "1" + "a_b" * 26 + "a", # length 80
        ]
        for name in valid_names:
            with self.subTest(name=name):
                self.assertEqual(safe_name(name), name)

    def test_invalid_safe_name(self):
        invalid_names = [
            "",
            "a" * 81,
            "_abc",
            "-abc",
            "abc!",
            "a/b",
            "a b",
            "a@b",
            "a.b",
        ]
        for name in invalid_names:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "unsafe submission/reviewer identity"):
                    safe_name(name)

    def test_invalid_type(self):
        invalid_types = [
            None,
            123,
            12.3,
            True,
            [],
            {},
        ]
        for val in invalid_types:
            with self.subTest(val=val):
                with self.assertRaisesRegex(ValueError, "unsafe submission/reviewer identity"):
                    safe_name(val)

if __name__ == "__main__":
    unittest.main()
