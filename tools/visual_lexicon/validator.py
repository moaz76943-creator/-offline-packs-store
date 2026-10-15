import re

class ValidationError(Exception):
    pass

class TokenValidator:
    REQUIRED_KEYS = {
        'version', 'viewBox', 'paths', 'palette',
        'semantic_label', 'alt_text', 'author', 'source', 'license'
    }

    ALLOWED_LICENSES = {'CC0-1.0', 'PUBLIC-DOMAIN'}
    MAX_PATHS = 50

    @classmethod
    def validate(cls, token: dict):
        if not isinstance(token, dict):
            raise ValidationError("Token must be a dictionary")

        missing_keys = cls.REQUIRED_KEYS - set(token.keys())
        if missing_keys:
            raise ValidationError(f"Missing required keys: {missing_keys}")

        if token['license'] not in cls.ALLOWED_LICENSES:
            raise ValidationError(f"Invalid license: {token['license']}. Must be CC0-1.0 or PUBLIC-DOMAIN")

        if not isinstance(token['paths'], list):
            raise ValidationError("paths must be a list")

        if len(token['paths']) > cls.MAX_PATHS:
            raise ValidationError(f"Too many paths: {len(token['paths'])}. Max is {cls.MAX_PATHS}")

        # Validate paths for executable expressions / malicious content
        # We only expect safe SVG path commands like M, L, C, Z, etc.
        # No scripts, external references, etc.
        # Since it's a declarative format, paths should just be strings of path data or dicts with safe keys.

        for path in token['paths']:
            if isinstance(path, str):
                cls._validate_path_string(path)
            elif isinstance(path, dict):
                # Ensure no script/event handler attributes
                for key, value in path.items():
                    if key.lower().startswith('on'):
                        raise ValidationError("Executable expressions/event handlers are not allowed")
                    if 'javascript:' in str(value).lower():
                        raise ValidationError("Executable expressions are not allowed")
                    if key == 'd':
                        cls._validate_path_string(value)
            else:
                raise ValidationError("Path must be string or dictionary")

    @classmethod
    def _validate_path_string(cls, path_data: str):
        # A simple check for script injection in path data, though usually path data is strictly parsed
        # Reject anything containing '<', '>', 'script', 'url('
        path_data_lower = path_data.lower()
        if '<' in path_data or '>' in path_data:
            raise ValidationError("Paths cannot contain XML/HTML tags")
        if 'javascript:' in path_data_lower or 'url(' in path_data_lower:
            raise ValidationError("External references or scripts are not allowed in path data")
