"""Organization catalog. Validates with no packs and no license ledger."""

import json
from pathlib import Path

from tools.language_production.catalog import REGISTRY_PATH, ROOT, load_json

GRAPH_PATH = ROOT / 'catalog' / 'organization' / 'concept_graph.v1.json'
FRAMEWORKS_PATH = ROOT / 'catalog' / 'organization' / 'frameworks.v1.json'
PROFILES_PATH = ROOT / 'catalog' / 'organization' / 'language_profiles.v1.json'
LEVELS = ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')
RIGHT_TO_LEFT = {'Arab', 'Hebr', 'Thaa', 'Nkoo', 'Adlm', 'Syrc'}


def load_graph(path=GRAPH_PATH):
    return load_json(path)


def load_frameworks(path=FRAMEWORKS_PATH):
    return load_json(path)


def load_profiles(path=PROFILES_PATH):
    return load_json(path)


def iter_concepts(graph):
    for section in graph.get('sections') or []:
        for subsection in section.get('subsections') or []:
            for concept in subsection.get('concepts') or []:
                yield section, subsection, concept


def index_concepts(graph):
    """Map a Wikidata item id to its concept slot. The first section keeps the item."""
    index = {}
    for section, subsection, concept in iter_concepts(graph):
        qid = concept.get('wikidata')
        if isinstance(qid, str) and qid not in index:
            index[qid] = {
                'concept_id': concept.get('id'),
                'section': section.get('id'),
                'subsection': subsection.get('id'),
            }
    return index


def build_profiles(registry):
    """Derive one profile per registry language. Display fields follow the registry script."""
    scripts = registry.get('scripts') or {}
    profiles = []
    for language in registry.get('languages') or []:
        if not isinstance(language, dict) or not language.get('id'):
            continue
        script = language.get('default_script') or ''
        script_info = scripts.get(script) if isinstance(scripts.get(script), dict) else {}
        direction = script_info.get('direction') or ''
        features = []
        morphology = language.get('morphology') if isinstance(language.get('morphology'), dict) else {}
        if isinstance(morphology.get('features'), list):
            features = [item for item in morphology['features'] if isinstance(item, str)]
        proficiency = language.get('proficiency') if isinstance(language.get('proficiency'), dict) else {}
        profiles.append({
            'id': language['id'],
            'script': script,
            'direction': direction,
            'rtl': direction == 'rtl' or script in RIGHT_TO_LEFT,
            'transliteration_needed': script != 'Latn',
            'vertical': direction.startswith('ttb') if isinstance(direction, str) else False,
            'gender': _feature_slot(features, 'gender', morphology.get('review_status')),
            'case': _feature_slot(features, 'case', morphology.get('review_status')),
            'number': _feature_slot(features, 'number', morphology.get('review_status')),
            'plural': _feature_slot(features, 'number', morphology.get('review_status')),
            'honorifics': _feature_slot(features, 'honorifics', morphology.get('review_status')),
            'verb_classes': {
                'applicability': 'unknown',
                'note': 'Verb subclass slots stay unknown until a source distinguishes them. No class list is invented.',
            },
            'morphology_features': features,
            'morphology_review_status': morphology.get('review_status'),
            'proficiency_framework_ids': list(proficiency.get('framework_ids') or []),
            'proficiency_mapping_status': proficiency.get('mapping_status') or 'not_mapped',
        })
    return {
        'schema_version': '1.0.0',
        'independent_of': ['packs', 'legal/ledger', 'manifest'],
        'note': (
            'Derived from catalog/language_registry.v1.json. Script, direction, and morphology '
            'features are copied from that registry. A feature that is absent stays unknown; '
            'this file does not invent a gender, case, plural, or honorific system.'
        ),
        'languages': profiles,
    }


def _feature_slot(features, name, review_status):
    if name in features:
        return {
            'applicability': 'applicable',
            'evidence': 'registry.morphology.features',
            'review_status': review_status,
        }
    return {
        'applicability': 'unknown',
        'evidence': 'registry.morphology.features does not list this feature',
        'review_status': review_status,
    }


def display_hints(profile):
    """How a language's sections and levels are displayed. This does not create words."""
    return {
        'script': profile.get('script'),
        'direction': profile.get('direction'),
        'rtl': bool(profile.get('rtl')),
        'transliteration_needed': bool(profile.get('transliteration_needed')),
        'vertical': bool(profile.get('vertical')),
    }


def validate_organization(graph, frameworks, profiles, registry, blocked_concepts=()):
    """Return human-readable problems. Does not open packs or the license ledger."""
    problems = []
    blocked = set(blocked_concepts or [])
    section_ids = []
    concept_ids = set()
    for section in graph.get('sections') or []:
        section_id = section.get('id')
        section_ids.append(section_id)
        if not section.get('subsections'):
            problems.append(f'{section_id} has no subsections')
        for subsection in section.get('subsections') or []:
            if not str(subsection.get('id') or '').startswith(f'{section_id}.'):
                problems.append(f"subsection {subsection.get('id')} is outside {section_id}")
            for concept in subsection.get('concepts') or []:
                qid = concept.get('wikidata')
                concept_id = concept.get('id')
                if not isinstance(qid, str) or concept_id != f'concept.{qid.lower()}':
                    problems.append(f'concept id does not match its Wikidata item: {concept_id}')
                    continue
                if qid in blocked:
                    problems.append(f'blocked concept was kept: {qid}')
                if concept_id in concept_ids:
                    problems.append(f'duplicate concept id: {concept_id}')
                concept_ids.add(concept_id)
                label = concept.get('anchor_label')
                if label is not None and (not isinstance(label, str) or not label.strip()):
                    problems.append(f'blank anchor label should be null: {concept_id}')
    if len(section_ids) != len(set(section_ids)):
        problems.append('duplicate section id')
    if frameworks.get('framework_id') != 'cefr':
        problems.append('framework_id must stay cefr')
    if frameworks.get('mapping_status') != 'not_mapped':
        problems.append('framework mapping_status must stay not_mapped')
    if list(frameworks.get('levels') or []) != list(LEVELS):
        problems.append('framework levels must be A1..C2')
    for track, slots in (frameworks.get('tracks') or {}).items():
        if not isinstance(slots, list) or not slots:
            problems.append(f'{track} has no slots')
            continue
        for slot in slots:
            if slot.get('level_id') not in LEVELS:
                problems.append(f"slot {slot.get('id')} has no CEFR level")
            if 'text' in slot or 'lemma' in slot:
                problems.append(f"slot {slot.get('id')} must not contain a word")
    registry_ids = [item.get('id') for item in registry.get('languages') or [] if isinstance(item, dict)]
    profile_ids = [item.get('id') for item in profiles.get('languages') or [] if isinstance(item, dict)]
    if profile_ids != registry_ids:
        problems.append('language profiles must list every registry language in registry order')
    expected = build_profiles(registry)
    if profiles.get('languages') != expected.get('languages'):
        problems.append('language profiles drifted from the registry derivation')
    return problems


def write_profiles(registry_path=REGISTRY_PATH, output=PROFILES_PATH):
    profiles = build_profiles(load_json(registry_path))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return output
