"""Fixtures for testing multilingual lexical quality validator.
Includes multilingual fixtures for German, Arabic, Hebrew, Chinese, Japanese, Thai and other scripts.
"""

VALID_ENTRIES = [
    {
        "id": "eng-US-1",
        "surface": "color",
        "language": "eng-US",
        "pos": "noun"
    },
    {
        "id": "eng-1",
        "surface": "hello",
        "language": "eng",
        "pos": "interjection",
        "translations": [
            {"language": "deu", "text": "hallo"},
            {"language": "jpn", "text": "こんにちは"}
        ],
        "examples": [
            {"text": "Hello, world!"}
        ]
    },
    {
        # German fixture
        "id": "deu-1",
        "surface": "Hund",
        "language": "deu",
        "pos": "noun",
        "plural": "Hunde",
        "translations": [
            {"language": "eng", "text": "dog"}
        ]
    },
    {
        # Arabic fixture
        "id": "ara-1",
        "surface": "كتاب",
        "language": "ara",
        "pos": "noun",
        "plural": "كتب"
    },
    {
        # Hebrew fixture
        "id": "heb-1",
        "surface": "שָׁלוֹם",
        "language": "heb",
        "pos": "noun"
    },
    {
        # Chinese fixture
        "id": "zho-1",
        "surface": "苹果",
        "language": "zho",
        "pos": "noun",
        "translations": [
            {"language": "eng", "text": "apple"}
        ]
    },
    {
        # Thai fixture
        "id": "tha-1",
        "surface": "สวัสดี",
        "language": "tha",
        "pos": "interjection"
    },
    {
        # Japanese fixture
        "id": "jpn-1",
        "surface": "食べる",
        "language": "jpn",
        "pos": "verb",
        "conjugations": {
            "past": "食べた"
        }
    }
]

INVALID_ENTRIES = [
    {
        # Missing ID
        "surface": "test",
        "language": "eng",
        "pos": "noun"
    },
    {
        # Missing surface
        "id": "eng-2",
        "language": "eng",
        "pos": "noun"
    },
    {
        # Empty surface
        "id": "eng-3",
        "surface": "   ",
        "language": "eng",
        "pos": "noun"
    },
    {
        # Invalid Unicode (surrogates) cannot easily be represented in JSON string directly,
        # but we can construct it dynamically in tests if needed, or put a literal null byte.
        "id": "eng-4",
        "surface": "hello\u0000world",
        "language": "eng",
        "pos": "noun"
    },
    {
        # Invalid language code
        "id": "eng-5",
        "surface": "test",
        "language": "ENG_UPPERCASE",
        "pos": "noun"
    },
    {
        # Malformed translations
        "id": "eng-6",
        "surface": "test",
        "language": "eng",
        "pos": "noun",
        "translations": "not a list"
    },
    {
        # Malformed translation element
        "id": "eng-7",
        "surface": "test",
        "language": "eng",
        "pos": "noun",
        "translations": [
            {"language": "deu"} # missing text
        ]
    },
    {
        # Malformed examples
        "id": "eng-8",
        "surface": "test",
        "language": "eng",
        "pos": "noun",
        "examples": [
            {"not_text": "hello"}
        ]
    },
    {
        # Invalid POS type (should be string)
        "id": "eng-9",
        "surface": "test",
        "language": "eng",
        "pos": 123
    }
]

REVIEW_REQUIRED_ENTRIES = [
    {
        # Noun with conjugations
        "id": "eng-10",
        "surface": "running",
        "language": "eng",
        "pos": "noun",
        "conjugations": {"past": "ran"}
    },
    {
        # Verb with plural
        "id": "eng-11",
        "surface": "run",
        "language": "eng",
        "pos": "verb",
        "plural": "runs"
    }
]

INVALID_ENTRIES.extend([
    {
        # Strict POS enforcement
        "id": "eng-invalid-pos",
        "surface": "test",
        "language": "eng",
        "pos": "not-a-valid-pos"
    },
    {
        # Language mismatch
        "id": "deu-mismatch",
        "surface": "test",
        "language": "eng",
        "pos": "noun"
    },
    {
        # Isolating language with plural
        "id": "zho-plural",
        "surface": "苹果",
        "language": "zho",
        "pos": "noun",
        "plural": "苹果s"
    },
    {
        # Isolating language with conjugation
        "id": "tha-conj",
        "surface": "สวัสดี",
        "language": "tha",
        "pos": "verb",
        "conjugations": {"past": "test"}
    }
])

INVALID_ENTRIES.extend([
    {
        # Arabic invalid structure
        "id": "ara-invalid",
        "surface": "كتاب",
        "language": "ara",
        "pos": "not-a-valid-pos"
    },
    {
        # Hebrew missing surface
        "id": "heb-missing-surface",
        "language": "heb",
        "pos": "noun"
    },
    {
        # Japanese invalid language mismatch
        "id": "jpn-mismatch",
        "surface": "食べる",
        "language": "eng",
        "pos": "verb"
    }
])
