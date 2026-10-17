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
import io
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
SENSE_NUMBER = re.compile(r'^S([1-9][0-9]*)$')
HARD_MAX_BYTES = 256 * 1024 * 1024
_DECOMPRESS_CHUNK = 8192
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


class _GzipStream:
    """Pull bounded decompressed output, one gzip member at a time.

    Each read returns at most _DECOMPRESS_CHUNK plaintext bytes. Complete is
    true only after the final member ends and no compressed bytes remain. A
    truncated member keeps earlier plaintext and leaves gzip_complete false.
    """

    def __init__(self, fileobj):
        self._fh = fileobj
        self._z = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self._pending = b''
        self._input_done = False
        self._finished = False
        self._member_open = False
        self._saw_end = False
        self.gzip_complete = False
        self.decompressed_bytes = 0

    def read(self):
        if self._finished:
            return b''
        while not self._finished:
            if not self._pending and not self._input_done:
                nxt = self._fh.read(_DECOMPRESS_CHUNK)
                if nxt:
                    self._pending = nxt
                else:
                    self._input_done = True
            if not self._pending and self._input_done:
                self._finished = True
                self.gzip_complete = self._saw_end and not self._member_open
                return b''
            before = self._pending
            try:
                piece = self._z.decompress(self._pending, _DECOMPRESS_CHUNK)
            except zlib.error as exc:
                self._finished = True
                self.gzip_complete = False
                if self.decompressed_bytes == 0:
                    raise ExtractError('lexeme dump is not gzip data') from exc
                return b''
            self._pending = self._z.unconsumed_tail
            self._member_open = True
            if self._z.eof:
                # flush() appends a duplicate of unused_data; keep the pre-flush tail.
                unused = self._z.unused_data
                try:
                    piece += self._z.flush()
                except zlib.error as exc:
                    self._finished = True
                    self.gzip_complete = False
                    if piece:
                        self.decompressed_bytes += len(piece)
                        return piece
                    if self.decompressed_bytes == 0:
                        raise ExtractError('lexeme dump gzip trailer is invalid') from exc
                    return b''
                self._pending = unused
                self._z = zlib.decompressobj(16 + zlib.MAX_WBITS)
                self._member_open = False
                self._saw_end = True
                if piece:
                    self.decompressed_bytes += len(piece)
                    return piece
                continue
            if piece:
                self.decompressed_bytes += len(piece)
                return piece
            if self._pending == before:
                if self._input_done:
                    self._finished = True
                    self.gzip_complete = False
                    return b''
                more = self._fh.read(_DECOMPRESS_CHUNK)
                if not more:
                    self._input_done = True
                    continue
                self._pending += more
        return b''

    def close(self):
        self._fh = None
        self._z = None


class GzipLineReader:
    """Decode newline-terminated text incrementally. The trailing partial line is remainder."""

    def __init__(self, source):
        self._owned = None
        if isinstance(source, (str, Path)):
            self._owned = open(source, 'rb')
            fileobj = self._owned
        else:
            fileobj = source
        self._stream = _GzipStream(fileobj)
        self._text = codecs.getincrementaldecoder('utf-8')()
        self._pending = ''
        self._lines_done = False
        self.remainder = ''

    def close(self):
        self._stream.close()
        if self._owned is not None:
            self._owned.close()
            self._owned = None

    @property
    def gzip_complete(self):
        return self._stream.gzip_complete

    @property
    def decompressed_bytes(self):
        return self._stream.decompressed_bytes

    def __iter__(self):
        return self

    def __next__(self):
        if self._lines_done:
            raise StopIteration
        while '\n' not in self._pending:
            piece = self._stream.read()
            if not piece:
                self._lines_done = True
                try:
                    self._pending += self._text.decode(b'', final=self._stream.gzip_complete)
                except UnicodeError as exc:
                    raise ExtractError('lexeme dump is not UTF-8') from exc
                self.remainder = self._pending
                self._pending = ''
                raise StopIteration
            try:
                self._pending += self._text.decode(piece, final=False)
            except UnicodeError as exc:
                raise ExtractError('lexeme dump is not UTF-8') from exc
        line, self._pending = self._pending.split('\n', 1)
        return line


def gunzip_bytes(raw):
    """Decompress every gzip member.

    Wikidata dumps are concatenated gzip members. Complete is true only when
    the final member ends cleanly. A truncated or range-limited download stays
    incomplete so the caller cannot treat the publisher checksum as verified.
    """
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return '', False
    stream = _GzipStream(io.BytesIO(bytes(raw)))
    chunks = []
    try:
        while True:
            piece = stream.read()
            if not piece:
                break
            chunks.append(piece)
        complete = stream.gzip_complete
    finally:
        stream.close()
    return _decode_plaintext(b''.join(chunks), complete), complete


def _decode_plaintext(text, complete):
    if complete:
        try:
            return text.decode('utf-8')
        except UnicodeError as exc:
            raise ExtractError('lexeme dump is not UTF-8') from exc
    return codecs.getincrementaldecoder('utf-8')().decode(text, final=False)


def _entity_from_line(line, strict):
    row = line.strip().rstrip(',')
    if not row or row in {'[', ']'}:
        return None
    try:
        entity = json.loads(row)
    except json.JSONDecodeError as exc:
        if strict:
            raise ExtractError('lexeme dump contains a malformed JSON line') from exc
        return None
    return entity if isinstance(entity, dict) else None


def iter_entities(reader):
    """Yield one JSON object per complete line. A truncated tail is not parsed."""
    for line in reader:
        entity = _entity_from_line(line, strict=True)
        if entity is not None:
            yield entity
    if reader.gzip_complete and reader.remainder:
        entity = _entity_from_line(reader.remainder, strict=True)
        if entity is not None:
            yield entity


def sense_identity(lexeme_id, sense):
    """Return (number, source id) when sense['id'] is {lexeme}-S<nonzero>."""
    if not isinstance(sense, dict):
        return None
    sense_id = sense.get('id')
    if not isinstance(sense_id, str):
        return None
    prefix = f'{lexeme_id}-'
    if not sense_id.startswith(prefix):
        return None
    match = SENSE_NUMBER.fullmatch(sense_id[len(prefix):])
    if not match:
        return None
    return match.group(1), sense_id


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
    seen_sense_ids = set()
    for sense in senses:
        identity = sense_identity(lexeme_id, sense)
        if identity is None or identity[1] in seen_sense_ids:
            return 'quarantine', 'invalid_sense_id'
        seen_sense_ids.add(identity[1])
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
        for sense in entity.get('senses') or []:
            identity = sense_identity(locator, sense)
            if identity is None:
                continue
            number, sense_id = identity
            status, qids = sense_items(sense)
            if status != 'ok':
                continue
            gloss = gloss_of(sense)
            if not gloss:
                continue
            concept = f'concept.{qids[0].lower()}' if qids else f'concept.de.{token}.s{number}'
            senses.append({
                'sense_id': f'sense.de.{token}.s{number}',
                'lexeme_id': f'lex.de.{token}',
                'concept_id': concept,
                'definition': gloss,
                'source': source_record(dataset_version, origin_url, sense_id, artifact_sha256),
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


def _digest_file(path):
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            sha1.update(chunk)
            sha256.update(chunk)
    return sha1.hexdigest(), sha256.hexdigest()


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
    local_sha1, file_sha256 = _digest_file(dump_path)
    expected = publisher_sha1(Path(checksum_path).read_text(encoding='utf-8'), dump_path.name)
    blocked_concepts, blocked_lemmas = load_blocklist(blocklist_path)
    reader = GzipLineReader(dump_path)
    kept = []
    excluded = []
    quarantined = []
    seen = 0
    stopped_early = False
    try:
        for entity in iter_entities(reader):
            decision, reason = classify_lexeme(entity, blocked_concepts, blocked_lemmas)
            if decision == 'skip':
                continue
            seen += 1
            record = {'id': entity.get('id'), 'lemma': lemma_of(entity), 'reason': reason}
            if decision == 'exclude':
                excluded.append(record)
            elif decision == 'quarantine':
                quarantined.append(record)
            else:
                kept.append(entity)
            if seen >= max_lexemes:
                stopped_early = True
                break
    finally:
        decompressed_bytes = reader.decompressed_bytes
        reader.close()
    gzip_complete = (not stopped_early) and reader.gzip_complete
    checksum_verified = gzip_complete and local_sha1 == expected
    if gzip_complete and local_sha1 != expected:
        raise ExtractError('complete dump does not match the publisher SHA-1')
    artifact_sha256 = file_sha256 if checksum_verified else None
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
        'decompressed_bytes': decompressed_bytes,
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
