import unittest
from community.review.state_machine import safe_name

class TestStateMachine(unittest.TestCase):
    def test_safe_name_valid(self):
        valid_names = [
            "a", "A", "0", "a_b", "A-B", "a123", "1a",
            "a" * 80, "A" * 80, "0" * 80,
            "user-name_123"
        ]
        for name in valid_names:
            self.assertEqual(safe_name(name), name)

    def test_safe_name_invalid(self):
        invalid_names = [
            "", "_a", "-a", "a" * 81, "a@b", "a/b", "a b", "a\nb", "a\tb", "a.b",
            "a\\b", "a#b", "a$b", "a%b", "a^b", "a&b", "a*b", "a(b", "a)b",
            123, None, {}, [], 12.3
        ]
        for name in invalid_names:
            with self.assertRaises(ValueError, msg=f"Should fail for {name}"):
                safe_name(name)

if __name__ == '__main__':
    unittest.main()
