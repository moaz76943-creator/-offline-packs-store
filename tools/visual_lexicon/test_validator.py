import unittest
from tools.visual_lexicon.validator import TokenValidator, ValidationError

class TestTokenValidator(unittest.TestCase):
    def setUp(self):
        self.valid_token = {
            'version': 1,
            'viewBox': '0 0 24 24',
            'paths': ['M12 2L2 22h20L12 2z'],
            'palette': ['#000000'],
            'semantic_label': 'triangle',
            'alt_text': 'A black triangle',
            'author': 'Test Author',
            'source': 'https://example.com',
            'license': 'CC0-1.0'
        }

    def test_valid_token(self):
        TokenValidator.validate(self.valid_token)

    def test_missing_keys(self):
        del self.valid_token['version']
        with self.assertRaises(ValidationError) as ctx:
            TokenValidator.validate(self.valid_token)
        self.assertIn("Missing required keys", str(ctx.exception))

    def test_invalid_license(self):
        self.valid_token['license'] = 'CC-BY-4.0'
        with self.assertRaises(ValidationError) as ctx:
            TokenValidator.validate(self.valid_token)
        self.assertIn("Invalid license", str(ctx.exception))

    def test_too_many_paths(self):
        self.valid_token['paths'] = ['M0 0'] * 51
        with self.assertRaises(ValidationError) as ctx:
            TokenValidator.validate(self.valid_token)
        self.assertIn("Too many paths", str(ctx.exception))

    def test_malicious_path_string(self):
        self.valid_token['paths'] = ['<script>alert(1)</script>']
        with self.assertRaises(ValidationError) as ctx:
            TokenValidator.validate(self.valid_token)
        self.assertIn("cannot contain XML/HTML tags", str(ctx.exception))

        self.valid_token['paths'] = ['url(http://evil.com)']
        with self.assertRaises(ValidationError) as ctx:
            TokenValidator.validate(self.valid_token)
        self.assertIn("External references or scripts", str(ctx.exception))

    def test_malicious_path_dict(self):
        self.valid_token['paths'] = [{'d': 'M0 0', 'onclick': 'alert(1)'}]
        with self.assertRaises(ValidationError) as ctx:
            TokenValidator.validate(self.valid_token)
        self.assertIn("Executable expressions/event handlers", str(ctx.exception))

        self.valid_token['paths'] = [{'d': 'javascript:alert(1)'}]
        with self.assertRaises(ValidationError) as ctx:
            TokenValidator.validate(self.valid_token)
        self.assertIn("Executable expressions are not allowed", str(ctx.exception))
