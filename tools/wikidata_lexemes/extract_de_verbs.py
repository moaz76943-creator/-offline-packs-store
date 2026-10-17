#!/usr/bin/env python3
"""Stream a Wikidata lexeme dump into a non-production German-verb SQLite candidate.

The dump is CC0. This tool does not admit a source, does not edit
legal/ledger/sources.json or manifest.json, and never marks the candidate
publication-approved. A publisher SHA-1 is recorded as verified only when the
local file is the complete dump and matches wikidata-YYYYMMDD-sha1sums.txt.
"""
import argparse
import codecs
import hashlib
import json
import re
import sys
import unicodedata
import zlib
from pathlib import Path

GERMAN = 'Q188'
VERB = 'Q24905'
SENSE_ITEM = 'P5137'
MEDIA_PROPERTIES = frozenset({'P443', 'P18'})
QID = re.compile(r'^Q[1-9][0-9]*$')
LEXEME_ID = re.compile(r'^L[1-9][0-9]*$')
HARD_MAX_BYTES = 256 * 1024 * 1024
HERE = Path(__file__).resolve().parent
LEXICAL_DIR = HERE.parents[1] / 'standards' / 'lexical'
FORBIDDEN_OUTPUTS = {'manifest.json', 'legal/ledger/sources.json'}


class ExtractError(ValueError):
    pass


def load_blocklist(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    concepts = data.get('blocked_concepts')
    lemmas = data.get('blocked_lemmas')
    if not isinstance(concepts, list) or not isinstance(lemmas, list):
        raise ExtractError('blocklist needs blocked_concepts and blocked_lemmas arrays')
    concept_ids = set()
    for item in concepts:
        if not isinstance(item, str) or not QID.fullmatch(item):
            raise ExtractError('blocklist concepts must be Wikidata item QIDs')
        concept_ids.add(item)
    lemma_ids = set()
    for item in lemmas:
        if not isinstance(item, str) or not item.strip():
            raise ExtractError('blocklist lemmas must be non-empty strings')
        lemma_ids.add(unicodedata.normalize('NFKC', item).casefold())
    return concept_ids, lemma_ids


def publisher_sha1(checksum_text, filename):
    found = None
    for line in checksum_text.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r'[0-9a-fA-F]{40}', parts[0]):
            continue
        name = parts[1][1:] if parts[1].startswith('*') else parts[1]
        if name == filename:
            if found is not None and found != parts[0].lower():
                raise ExtractError('publisher checksum file lists conflicting SHA-1 values')
            found = parts[0].lower()
    if found is None:
        raise ExtractError(f'publisher checksum file has no SHA-1 for {filename}')
    return found


def gunzip_bytes(raw):
    """Decompress every gzip member.

    Wikidata dumps are concatenated gzip members. Complete is true only when
    the final member ends on eof and leaves no unused bytes. A truncated or
    range-limited download stays incomplete so the caller cannot treat the
    publisher checksum as verified.
    """
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return _decode_plaintext(b'', False), False
    chunks = []
    remaining = bytes(raw)
    while remaining:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            piece = decoder.decompress(remaining)
        except zlib.error as exc:
            if not chunks:
                raise ExtractError('lexeme dump is not gzip data') from exc
            return _decode_plaintext(b''.join(chunks), False), False
        if not decoder.eof:
            chunks.append(piece)
            return _decode_plaintext(b''.join(chunks), False), False
        try:
            piece += decoder.flush()
        except zlib.error as exc:
            raise ExtractError('lexeme dump gzip trailer is invalid') from exc
        chunks.append(piece)
        unused = decoder.unused_data
        if not unused:
            return _decode_plaintext(b''.join(chunks), True), True
        if len(unused) >= len(remaining):
            return _decode_plaintext(b''.join(chunks), False), False
        remaining = unused
    return _decode_plaintext(b''.join(chunks), False), False


def _decode_plaintext(text, complete):
    if complete:
        try:
            return text.decode('utf-8')
        except UnicodeError as exc:
            raise ExtractError('lexeme dump is not UTF-8') from exc
    return codecs.getincrementaldecoder('utf-8')().decode(text, final=False)


def iter_entities(plaintext, gzip_complete):
    """Yield JSON objects from a Wikidata JSON array, one entity per line."""
    lines = plaintext.splitlines()
    if not lines:
        return
    start = 1 if lines[0].strip() == '[' else 0
    end = len(lines)
    if lines[-1].strip() == ']':
        end -= 1
    elif not gzip_complete:
        end -= 1
    for line in lines[start:end]:
        row = line.strip().rstrip(',')
        if not row:
            continue
        try:
            entity = json.loads(row)
        except json.JSONDecodeError as exc:
            if gzip_complete:
                raise ExtractError('lexeme dump contains a malformed JSON line') from exc
            break
        if isinstance(entity, dict):
            yield entity


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def lemma_of(entity):
    lemmas = entity.get('lemmas')
    if not isinstance(lemmas, dict):
        return ''
    german = lemmas.get('de')
    if not isinstance(german, dict):
        return ''
    return _text(german.get('value'))


def sense_items(sense):
    """Return (status, qids). status is ok, blocked-ready ok, or ambiguous."""
    claims = sense.get('claims') if isinstance(sense, dict) else None
    if not isinstance(claims, dict):
        return 'ambiguous', []
    statements = claims.get(SENSE_ITEM, [])
    if statements is None:
        statements = []
    if not isinstance(statements, list):
        return 'ambiguous', []
    qids = []
    ambiguous = False
    for statement in statements:
        if not isinstance(statement, dict):
            return 'ambiguous', []
        snak = statement.get('mainsnak')
        if not isinstance(snak, dict):
            return 'ambiguous', []
        kind = snak.get('snaktype')
        if kind == 'value':
            value = (snak.get('datavalue') or {}).get('value') if isinstance(snak.get('datavalue'), dict) else None
            qid = value.get('id') if isinstance(value, dict) else None
            if not isinstance(qid, str) or not QID.fullmatch(qid):
                return 'ambiguous', qids
            qids.append(qid)
        elif kind in {'somevalue', 'novalue'} or kind:
            ambiguous = True
    return ('ambiguous' if ambiguous else 'ok'), qids


def gloss_of(sense):
    glosses = sense.get('glosses') if isinstance(sense, dict) else None
    if not isinstance(glosses, dict) or not glosses:
        return ''
    order = []
    if 'de' in glosses:
        order.append('de')
    if 'en' in glosses:
        order.append('en')
    order.extend(sorted(key for key in glosses if key not in {'de', 'en'}))
    for key in order:
        entry = glosses.get(key)
        if isinstance(entry, dict):
            text = _text(entry.get('value'))
            if text:
                return text
    return ''


def forms_of(entity):
    forms = []
    raw_forms = entity.get('forms')
    if not isinstance(raw_forms, list):
        return forms
    for form in raw_forms:
        if not isinstance(form, dict):
            continue
        representations = form.get('representations')
        surface = ''
        if isinstance(representations, dict) and isinstance(representations.get('de'), dict):
            surface = _text(representations['de'].get('value'))
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


def classify_lexeme(entity, blocked_concepts, blocked_lemmas):
    """Return keep, exclude, quarantine, or skip, plus a reason."""
    if entity.get('language') != GERMAN or entity.get('lexicalCategory') != VERB:
        return 'skip', 'not_german_verb'
    lexeme_id = entity.get('id')
    if not isinstance(lexeme_id, str) or not LEXEME_ID.fullmatch(lexeme_id):
        return 'skip', 'bad_id'
    lemma = lemma_of(entity)
    if not lemma:
        return 'quarantine', 'missing_german_lemma'
    senses = entity.get('senses')
    if senses is None:
        senses = []
    if not isinstance(senses, list):
        return 'quarantine', 'unreadable_senses'
    lemma_hit = unicodedata.normalize('NFKC', lemma).casefold() in blocked_lemmas
    blocked_senses = 0
    allowed_senses = 0
    ambiguous = False
    for sense in senses:
        status, qids = sense_items(sense)
        linked = any(qid in blocked_concepts for qid in qids)
        if linked:
            blocked_senses += 1
        if status == 'ambiguous':
            ambiguous = True
            continue
        if linked:
            continue
        if gloss_of(sense) or qids:
            allowed_senses += 1
        else:
            ambiguous = True
    if blocked_senses and not allowed_senses and not ambiguous:
        return 'exclude', 'blocked_concept'
    if blocked_senses and (allowed_senses or ambiguous):
        return 'quarantine', 'mixed_blocked_and_allowed_senses'
    if ambiguous or lemma_hit:
        return 'quarantine', 'ambiguous_sense_or_lemma'
    return 'keep', 'german_verb'


def source_record(dataset_version, origin_url, locator, artifact_sha256):
    return {
        'source_id': 'wikidata.lexemes',
        'origin_url': origin_url,
        'publisher': 'Wikimedia Foundation',
        'dataset_version': dataset_version,
        'retrieval_id': f'wikidata-{dataset_version}-lexemes.json.gz',
        'license_id': 'CC0-1.0',
        'record_locator': locator,
        'artifact_sha256': artifact_sha256,
        'publication_approved': False,
        'fixture_only': False,
    }


def to_document(entities, dataset_version, origin_url, artifact_sha256):
    lexemes = []
    senses = []
    for entity in entities:
        locator = entity['id']
        token = locator.lower()
        lemma = lemma_of(entity)
        source = source_record(dataset_version, origin_url, locator, artifact_sha256)
        lexemes.append({
            'lexeme_id': f'lex.de.{token}',
            'language': 'de',
            'script': 'Latn',
            'lemma': lemma,
            'surface': lemma,
            'pos': 'verb',
            'direction': 'ltr',
            'morphology': {'conjugations': forms_of(entity)},
            'source': source,
        })
        for index, sense in enumerate(entity.get('senses') or [], start=1):
            status, qids = sense_items(sense)
            if status != 'ok':
                continue
            gloss = gloss_of(sense)
            if not gloss:
                continue
            concept = f'concept.{qids[0].lower()}' if qids else f'concept.de.{token}.s{index}'
            senses.append({
                'sense_id': f'sense.de.{token}.s{index}',
                'lexeme_id': f'lex.de.{token}',
                'concept_id': concept,
                'definition': gloss,
                'source': source_record(dataset_version, origin_url, f'{locator}-S{index}', artifact_sha256),
            })
    return {
        'contract_version': '1.0.0',
        'document_id': f'candidate.wikidata.de.verbs.{dataset_version}',
        'lexemes': lexemes,
        'senses': senses,
        'translations': [],
        'examples': [],
        'relations': [],
    }


def assert_output_allowed(path, repo_root):
    resolved = path.resolve()
    root = repo_root.resolve()
    if not resolved.is_relative_to(root):
        return
    relative = resolved.relative_to(root).as_posix()
    if relative == 'packs' or relative.startswith('packs/'):
        raise ExtractError('refusing to write under packs/')
    if relative in FORBIDDEN_OUTPUTS:
        raise ExtractError('refusing to write the source ledger or manifest')


def _write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows), encoding='utf-8')


def extract(dump_path, checksum_path, blocklist_path, output, *, max_bytes, max_lexemes,
            dataset_version, origin_url, repo_root):
    if not isinstance(max_bytes, int) or max_bytes < 1 or max_bytes > HARD_MAX_BYTES:
        raise ExtractError(f'max-bytes must be 1..{HARD_MAX_BYTES}')
    if not isinstance(max_lexemes, int) or max_lexemes < 1 or max_lexemes > 2000:
        raise ExtractError('max-lexemes must be 1..2000')
    if not re.fullmatch(r'[0-9]{8}', dataset_version):
        raise ExtractError('dataset version must be YYYYMMDD')
    if not isinstance(origin_url, str) or not origin_url.startswith('https://'):
        raise ExtractError('origin URL must be https')
    dump_path = Path(dump_path)
    output = Path(output)
    assert_output_allowed(output, Path(repo_root))
    size = dump_path.stat().st_size
    if size > max_bytes:
        raise ExtractError(f'dump exceeds max-bytes ({size} > {max_bytes})')
    raw = dump_path.read_bytes()
    local_sha1 = hashlib.sha1(raw).hexdigest()
    expected = publisher_sha1(Path(checksum_path).read_text(encoding='utf-8'), dump_path.name)
    plaintext, gzip_complete = gunzip_bytes(raw)
    checksum_verified = gzip_complete and local_sha1 == expected
    if gzip_complete and local_sha1 != expected:
        raise ExtractError('complete dump does not match the publisher SHA-1')
    artifact_sha256 = hashlib.sha256(raw).hexdigest() if checksum_verified else None
    blocked_concepts, blocked_lemmas = load_blocklist(blocklist_path)
    kept = []
    excluded = []
    quarantined = []
    seen = 0
    for entity in iter_entities(plaintext, gzip_complete):
        decision, reason = classify_lexeme(entity, blocked_concepts, blocked_lemmas)
        if decision == 'skip':
            continue
        seen += 1
        if seen > max_lexemes:
            break
        record = {'id': entity.get('id'), 'lemma': lemma_of(entity), 'reason': reason}
        if decision == 'exclude':
            excluded.append(record)
        elif decision == 'quarantine':
            quarantined.append(record)
        else:
            kept.append(entity)
    document = to_document(kept, dataset_version, origin_url, artifact_sha256)
    if str(LEXICAL_DIR) not in sys.path:
        sys.path.insert(0, str(LEXICAL_DIR))
    from sqlite_v2 import build
    output.parent.mkdir(parents=True, exist_ok=True)
    build(document, output, publication=False)
    _write_jsonl(output.with_suffix('.excluded.jsonl'), excluded)
    _write_jsonl(output.with_suffix('.quarantine.jsonl'), quarantined)
    report = {
        'checksum_verified': checksum_verified,
        'publisher_sha1': expected,
        'local_sha1': local_sha1,
        'bytes': size,
        'gzip_complete': gzip_complete,
        'german_verbs_considered': min(seen, max_lexemes),
        'written': len(kept),
        'excluded': len(excluded),
        'quarantined': len(quarantined),
        'publication_approved': False,
        'ledger_updated': False,
        'manifest_updated': False,
        'output': output.name,
    }
    output.with_suffix('.report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    notice = output.with_name('UNVERIFIED_CANDIDATE.txt')
    notice.write_text(
        'Unverified CC0 candidate. Not a production pack. '
        'legal/ledger/sources.json and manifest.json were not modified.\n',
        encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, required=True)
    parser.add_argument('--checksums', type=Path, required=True)
    parser.add_argument('--blocklist', type=Path, default=HERE / 'blocklist.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-bytes', type=int, required=True)
    parser.add_argument('--max-lexemes', type=int, default=500)
    parser.add_argument('--dataset-version', required=True)
    parser.add_argument('--origin-url', required=True)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    args = parser.parse_args(argv)
    try:
        report = extract(
            args.dump, args.checksums, args.blocklist, args.output,
            max_bytes=args.max_bytes, max_lexemes=args.max_lexemes,
            dataset_version=args.dataset_version, origin_url=args.origin_url,
            repo_root=args.repo_root)
    except (ExtractError, OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
