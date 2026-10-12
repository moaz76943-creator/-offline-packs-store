import os
import json
import gzip
import hashlib
import pytest

from perfect_public_store import create_minified_pack

def test_create_minified_pack_happy_path(tmp_path, monkeypatch):
    # Change working directory to tmp_path to avoid creating 'packs' in the real repo
    monkeypatch.chdir(tmp_path)
    os.makedirs('packs', exist_ok=True)

    data = {"key": "value", "number": 123}
    filename = "test_pack.json.gz"

    file_size, file_hash = create_minified_pack(filename, data)

    # Verify file exists
    expected_path = os.path.join('packs', filename)
    assert os.path.exists(expected_path)

    # Verify file size and hash
    assert file_size == os.path.getsize(expected_path)
    with open(expected_path, 'rb') as f:
        content = f.read()
        assert file_hash == hashlib.sha256(content).hexdigest()

    # Verify content
    with gzip.open(expected_path, 'rt', encoding='utf-8') as f:
        loaded_data = json.load(f)
        assert loaded_data == data

def test_create_minified_pack_unicode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs('packs', exist_ok=True)

    # Test with non-ASCII characters to ensure ensure_ascii=False works
    data = {"ar": "مرحبا", "de": "äöüß", "emoji": "🚀"}
    filename = "unicode_pack.json.gz"

    create_minified_pack(filename, data)

    expected_path = os.path.join('packs', filename)

    with gzip.open(expected_path, 'rt', encoding='utf-8') as f:
        # Check that it wasn't escaped (ensure_ascii=False)
        raw_content = f.read()
        assert "مرحبا" in raw_content
        assert "äöüß" in raw_content

        # Load back to dict
        loaded_data = json.loads(raw_content)
        assert loaded_data == data

def test_create_minified_pack_minification(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs('packs', exist_ok=True)

    data = {"a": 1, "b": [2, 3]}
    filename = "minified_pack.json.gz"

    create_minified_pack(filename, data)

    expected_path = os.path.join('packs', filename)
    with gzip.open(expected_path, 'rt', encoding='utf-8') as f:
        raw_content = f.read()
        # Verify no spaces after commas or colons
        assert " " not in raw_content
        assert raw_content == '{"a":1,"b":[2,3]}'

def test_create_minified_pack_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs('packs', exist_ok=True)

    data = {}
    filename = "empty_pack.json.gz"

    create_minified_pack(filename, data)

    expected_path = os.path.join('packs', filename)
    with gzip.open(expected_path, 'rt', encoding='utf-8') as f:
        raw_content = f.read()
        assert raw_content == '{}'
