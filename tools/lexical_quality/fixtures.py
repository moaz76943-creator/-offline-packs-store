"""Fixtures for testing multilingual lexical quality validator."""

VALID_ENTRIES = [
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
        "id": "ara-1",
        "surface": "كتاب",
        "language": "ara",
        "pos": "noun",
        "plural": "كتب"
    },
    {
        "id": "heb-1",
        "surface": "שָׁלוֹם",
        "language": "heb",
        "pos": "noun"
    },
    {
        "id": "zho-1",
        "surface": "苹果",
        "language": "zho",
        "pos": "noun",
        "translations": [
            {"language": "eng", "text": "apple"}
        ]
    },
    {
        "id": "tha-1",
        "surface": "สวัสดี",
        "language": "tha",
        "pos": "interjection"
    },
    {
        "id": "jpn-1",
        "surface": "食べる",
        "language": "jpn",
        "pos": "verb",
        "conjugations": {
            "past": "食べた"
        }
    },
    {
        "id": "rus-1",
        "surface": "книга",
        "language": "rus",
        "pos": "noun",
        "plural": "книги",
        "senses": [{"id": "rus-1-sense-1"}]
    },
    {
        "id": "hin-1",
        "surface": "नमस्ते",
        "language": "hin",
        "pos": "interjection",
        "senses": [{"id": "hin-1-sense-1"}]
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
    },
    {
        # Invalid POS value
        "id": "eng-10",
        "surface": "test",
        "language": "eng",
        "pos": "invalid_pos_value"
    },
    {
        # Duplicate sense ID
        "id": "eng-11",
        "surface": "test",
        "language": "eng",
        "pos": "noun",
        "senses": [{"id": "dup-sense-1"}, {"id": "dup-sense-1"}]
    },
    {
        # Language mismatch (translation language matches entry language)
        "id": "eng-12",
        "surface": "test",
        "language": "eng",
        "pos": "noun",
        "translations": [{"language": "eng", "text": "same"}]
    },
    {
        # Malformed example (non-dictionary)
        "id": "eng-13",
        "surface": "test",
        "language": "eng",
        "pos": "noun",
        "examples": ["just a string"]
    },
    {
        # Absent optional fields (while strictly valid by themselves,
        # testing structurally malformed empty structures for coverage)
        "id": "eng-14",
        "surface": "test",
        "language": "eng",
        "pos": "noun",
        "senses": [{}]
    }
]

REVIEW_REQUIRED_ENTRIES = [
    {
        # Noun with conjugations
        "id": "eng-15",
        "surface": "running",
        "language": "eng",
        "pos": "noun",
        "conjugations": {"past": "ran"}
    },
    {
        # Verb with plural
        "id": "eng-16",
        "surface": "run",
        "language": "eng",
        "pos": "verb",
        "plural": "runs"
    },
    {
        # Isolating language (Chinese) with plural
        "id": "zho-2",
        "surface": "人",
        "language": "zho",
        "pos": "noun",
        "plural": "人们"
    },
    {
        # Isolating language (Thai) with plural
        "id": "tha-2",
        "surface": "แมว",
        "language": "tha",
        "pos": "noun",
        "plural": "แมวทั้งหลาย"
    }
]
