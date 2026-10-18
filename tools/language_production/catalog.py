import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LANGUAGES_PATH = ROOT / 'catalog' / 'production_languages.v1.json'
SECTIONS_PATH = ROOT / 'catalog' / 'sections.v1.json'
REGISTRY_PATH = ROOT / 'catalog' / 'language_registry.v1.json'
BLOCKLIST_PATH = ROOT / 'tools' / 'wikidata_lexemes' / 'blocklist.json'


def load_json(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'{path} must be a JSON object')
    return data


def load_languages(path=LANGUAGES_PATH):
    data = load_json(path)
    rows = data.get('languages')
    if not isinstance(rows, list) or not rows:
        raise ValueError('production languages need a non-empty languages array')
    return data


def load_sections(path=SECTIONS_PATH):
    data = load_json(path)
    if not isinstance(data.get('sections'), list) or not data['sections']:
        raise ValueError('sections taxonomy needs a sections array')
    return data


def registry_by_id(path=REGISTRY_PATH):
    data = load_json(path)
    return {item['id']: item for item in data.get('languages', []) if isinstance(item, dict) and item.get('id')}


def load_blocklist(path=BLOCKLIST_PATH):
    data = load_json(path)
    concepts = data.get('blocked_concepts') or []
    lemmas = data.get('blocked_lemmas') or []
    return set(concepts), {item.casefold() for item in lemmas}
