"""Stream a lexeme dump slice into per-language overlays. One language, bounded records."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tools.language_production.build_overlay import source_record, write_overlay
from tools.language_production.catalog import ROOT, load_blocklist, registry_by_id
from tools.language_production.levels import estimate_level
from tools.language_production.sections import pos_for, section_for_items, verb_subsection
from tools.wikidata_lexemes.extract_de_verbs import (
    LEXEME_ID,
    QID,
    GzipLineReader,
    iter_entities,
    sense_identity,
    sense_items,
)

FORBIDDEN_OUTPUTS = ('manifest.json', 'legal/ledger/sources.json')


@dataclass(frozen=True)
class HarvestConfig:
    dataset_version: str
    origin_url: str
    max_lexemes: int
    output: str
    blocklist_path: Optional[str] = None
    repo_root: Optional[str] = None


def lemma_for(entity, language_id):
    lemmas = entity.get('lemmas')
    if not isinstance(lemmas, dict):
        return ''
    entry = lemmas.get(language_id)
    if not isinstance(entry, dict):
        return ''
    value = entry.get('value')
    return value.strip() if isinstance(value, str) else ''


def gloss_for(sense, language_id):
    glosses = sense.get('glosses') if isinstance(sense, dict) else None
    if not isinstance(glosses, dict) or not glosses:
        return ''
    order = []
    if language_id in glosses:
        order.append(language_id)
    if 'en' in glosses and 'en' not in order:
        order.append('en')
    order.extend(sorted(key for key in glosses if key not in order))
    for key in order:
        entry = glosses.get(key)
        if isinstance(entry, dict):
            value = entry.get('value')
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ''


def forms_for(entity, language_id):
    forms = []
    raw_forms = entity.get('forms')
    if not isinstance(raw_forms, list):
        return forms
    for form in raw_forms:
        if not isinstance(form, dict):
            continue
        representations = form.get('representations')
        surface = ''
        if isinstance(representations, dict) and isinstance(representations.get(language_id), dict):
            value = representations[language_id].get('value')
            surface = value.strip() if isinstance(value, str) else ''
        if not surface:
            continue
        features = []
        for feature in form.get('grammaticalFeatures') or []:
            if isinstance(feature, str) and QID.fullmatch(feature):
                features.append(feature)
        forms.append({
            'surface': surface,
            'features': {'grammatical_features': ','.join(sorted(set(features)))} if features else {},
            'attested': True,
        })
    return forms


def _blocked(item_qids, blocked_concepts, class_index):
    from tools.language_production.sections import ancestors
    for item in item_qids:
        if item in blocked_concepts:
            return True
        if ancestors(item, class_index) & blocked_concepts:
            return True
    return False


def classify_entity(entity, language, taxonomy, class_index, blocked_concepts, blocked_lemmas, config: HarvestConfig):
    """Return keep/exclude/quarantine/skip plus a record when the lexeme is kept."""
    language_id = language['id']
    if entity.get('language') != language['wikidata']:
        return 'skip', None
    lexeme_qid = entity.get('id')
    if not isinstance(lexeme_qid, str) or not LEXEME_ID.fullmatch(lexeme_qid):
        return 'skip', None
    category = entity.get('lexicalCategory')
    pos = pos_for(category, class_index, taxonomy)
    if pos is None:
        return 'quarantine', {'id': lexeme_qid, 'reason': 'unknown_lexical_category'}
    lemma = lemma_for(entity, language_id)
    if not lemma:
        return 'quarantine', {'id': lexeme_qid, 'reason': 'missing_lemma'}
    senses = entity.get('senses')
    if senses is None:
        senses = []
    if not isinstance(senses, list):
        return 'quarantine', {'id': lexeme_qid, 'reason': 'unreadable_senses'}
    if unicodedata.normalize('NFKC', lemma).casefold() in blocked_lemmas:
        return 'quarantine', {'id': lexeme_qid, 'reason': 'blocked_lemma_without_clear_item'}
    forms = forms_for(entity, language_id)
    level = estimate_level(lemma, len(forms), len(senses))
    token = lexeme_qid.lower()
    locator = lexeme_qid
    kept_senses = []
    blocked_senses = 0
    allowed_senses = 0
    ambiguous = False
    seen_ids = set()
    section_ids = []
    for sense in senses:
        identity = sense_identity(lexeme_qid, sense)
        if identity is None or identity[1] in seen_ids:
            return 'quarantine', {'id': lexeme_qid, 'reason': 'invalid_sense_id'}
        seen_ids.add(identity[1])
        status, item_qids = sense_items(sense)
        if _blocked(item_qids, blocked_concepts, class_index):
            blocked_senses += 1
        if status == 'ambiguous':
            ambiguous = True
            continue
        if _blocked(item_qids, blocked_concepts, class_index):
            continue
        gloss = gloss_for(sense, language_id)
        if not gloss and not item_qids:
            ambiguous = True
            continue
        allowed_senses += 1
        if not gloss:
            continue
        number, sense_id = identity
        section_id = section_for_items(item_qids, class_index, taxonomy)
        section_ids.append(section_id)
        concept = f'concept.{item_qids[0].lower()}' if item_qids else f'concept.{language_id}.{token}.unlinked'
        kept_senses.append({
            'sense_id': f'sense.{language_id}.{token}.s{number}',
            'lexeme_id': f'lex.{language_id}.{token}',
            'concept_id': concept,
            'definition': gloss,
            'domains': [f'section.{section_id}'],
            'subdomains': _subdomains(entity, category, class_index, taxonomy, pos),
            'levels': [level],
            'source': source_record(language_id, config.dataset_version, config.origin_url, sense_id),
        })
    if blocked_senses and not allowed_senses and not ambiguous:
        return 'exclude', {'id': lexeme_qid, 'reason': 'blocked_concept'}
    if blocked_senses and (allowed_senses or ambiguous):
        return 'quarantine', {'id': lexeme_qid, 'reason': 'mixed_blocked_and_allowed_senses'}
    if ambiguous or not kept_senses:
        return 'quarantine', {'id': lexeme_qid, 'reason': 'ambiguous_or_unparsed_senses'}
    registry = language.get('registry') or {}
    lexeme = {
        'lexeme_id': f'lex.{language_id}.{token}',
        'language': language_id,
        'script': registry.get('default_script') or 'Latn',
        'lemma': lemma,
        'surface': lemma,
        'pos': pos,
        'direction': 'rtl' if (registry.get('default_script') in {'Arab', 'Hebr'}) else 'ltr',
        'morphology': {'conjugations': forms} if pos == 'verb' else {'inflections': forms},
        'source': source_record(language_id, config.dataset_version, config.origin_url, locator),
    }
    grammar = None
    if forms:
        topic = 'grammar.conjugation' if pos == 'verb' else 'grammar.inflection'
        grammar = {
            'grammar_id': f'grammar.{language_id}.{token}.{topic.split(".")[-1]}',
            'topic': topic,
            'level_id': level['level_id'],
            'payload': {
                'level_assignment': 'estimated',
                'level_evidence': level['evidence'],
                'forms': forms,
            },
        }
    return 'keep', {
        'lexeme': lexeme,
        'senses': kept_senses,
        'grammar': grammar,
        'sections': sorted(set(section_ids)),
        'level': level['level_id'],
    }


def _subdomains(entity, category, class_index, taxonomy, pos):
    if pos != 'verb':
        return []
    subsection = verb_subsection([category] if isinstance(category, str) else [], class_index, taxonomy)
    return [subsection] if subsection else []


def attach_registry(language, registry=None):
    """Copy registry script metadata onto the language row used for direction."""
    language = dict(language)
    if not language.get('registry'):
        registry = registry if registry is not None else registry_by_id()
        language['registry'] = registry.get(language.get('id')) or {}
    return language


def assert_safe_output(output, repo_root=None):
    """Candidate overlays stay out of packs/, the manifest, and the ledger."""
    root = Path(repo_root or ROOT).resolve()
    path = Path(output).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        return
    if relative in FORBIDDEN_OUTPUTS or relative.startswith('packs/'):
        raise ValueError(f'refusing to write {relative}')


def collect_qids(dump_path, language, max_lexemes):
    """Item and category QIDs for this language, bounded by max_lexemes."""
    reader = GzipLineReader(dump_path)
    found = []
    seen = 0
    try:
        for entity in iter_entities(reader):
            if entity.get('language') != language.get('wikidata'):
                continue
            lexeme_id = entity.get('id')
            if not isinstance(lexeme_id, str) or not LEXEME_ID.fullmatch(lexeme_id):
                continue
            seen += 1
            category = entity.get('lexicalCategory')
            if isinstance(category, str) and QID.fullmatch(category):
                found.append(category)
            senses = entity.get('senses')
            if isinstance(senses, list):
                for sense in senses:
                    _status, item_qids = sense_items(sense)
                    found.extend(item_qids)
            if seen >= max_lexemes:
                break
    finally:
        reader.close()
    return list(dict.fromkeys(found))


def harvest_dump(dump_path, language, config: HarvestConfig, *, taxonomy, class_index=None, fetch=None):
    """Classify one language. A missing class index is fetched with a bounded walk."""
    language = attach_registry(language)
    if class_index is None:
        from tools.language_production.classes import fetch_class_index
        qids = collect_qids(dump_path, language, config.max_lexemes)
        fetch = fetch or fetch_class_index
        class_index = fetch(qids)
    return harvest_language(
        dump_path, language, config, taxonomy=taxonomy, class_index=class_index
    )


def harvest_language(dump_path, language, config: HarvestConfig, *, taxonomy, class_index):
    """Read dump lines until this language reaches max_lexemes, then stop."""
    if not re.fullmatch(r'[0-9]{8}', config.dataset_version):
        raise ValueError('dataset version must be YYYYMMDD')
    language = attach_registry(language)
    assert_safe_output(config.output, config.repo_root)
    blocked_concepts, blocked_lemmas = load_blocklist(config.blocklist_path) if config.blocklist_path else load_blocklist()
    reader = GzipLineReader(dump_path)
    kept = []
    excluded = []
    quarantined = []
    seen = 0
    try:
        for entity in iter_entities(reader):
            decision, payload = classify_entity(
                entity, language, taxonomy, class_index, blocked_concepts, blocked_lemmas, config
            )
            if decision == 'skip':
                continue
            seen += 1
            if decision == 'exclude':
                excluded.append(payload)
            elif decision == 'quarantine':
                quarantined.append(payload)
            else:
                kept.append(payload)
            if seen >= config.max_lexemes:
                break
    finally:
        decompressed = reader.decompressed_bytes
        complete = reader.gzip_complete
        reader.close()
    written = None
    if kept:
        write_overlay(language['id'], kept, config.output, config.dataset_version, config.origin_url)
        written = config.output
    return _summary(language, kept, excluded, quarantined, decompressed, complete, written)


def _summary(language, kept, excluded, quarantined, decompressed, complete, output):
    return {
        'id': language['id'],
        'lexemes': len(kept),
        'sections': sorted({section for record in kept for section in record['sections']}),
        'levels': sorted({record['level'] for record in kept}),
        'quarantined': len(quarantined),
        'excluded': len(excluded),
        'decompressed_bytes': decompressed,
        'gzip_complete': complete,
        'checksum_verified': False,
        'output': None if output is None else Path(output).name,
        'pair_databases': 0,
        'concepts': sorted({
            sense['concept_id']
            for record in kept
            for sense in record.get('senses') or []
            if sense.get('concept_id')
        }),
    }
