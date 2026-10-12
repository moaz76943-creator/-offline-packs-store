"""Deterministic append-only CVT1 media fixtures. Never registers a release pack.

Usage:
    python3 tools/semantic_vectors/build.py --root media/semantic_vectors --day 2026-10-12
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from compact import VectorError, compile_svg, decode_token, render_svg

ID = re.compile(r'concept\.[a-z0-9]+(?:\.[a-z0-9_]+){2,7}\Z')
SENSE = re.compile(r'[a-z0-9]+(?:\.[a-z0-9_]+){2,7}\Z')
NAME = re.compile(r'[a-z][a-z0-9_-]*\.svg\Z')
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+\Z')
LANG = re.compile(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')


class BuildError(ValueError):
    """Media input failed validation; existing manifest remains untouched."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise BuildError(f'Invalid JSON: {path.name}') from exc


def _relative(path, base):
    try:
        return path.relative_to(base).as_posix()
    except ValueError as exc:
        raise BuildError('Token output must be within media root') from exc


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.cvtmp-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_inside(root, filename):
    if not isinstance(filename, str) or '/' in filename or '\\' in filename or filename.startswith('.') or not NAME.fullmatch(filename):
        raise BuildError('unsafe source filename')
    path = root / filename
    if path.is_symlink() or not path.is_file():
        raise BuildError('missing or symlinked source')
    return path


def _rights(provenance, parent):
    if provenance.get('schema_version') != 1 or not isinstance(provenance.get('sources'), list):
        raise BuildError('unsupported provenance contract')
    contracts = {}
    for item in provenance['sources']:
        if not isinstance(item, dict):
            raise BuildError('invalid rights record')
        key = item.get('license_id')
        evidence = item.get('evidence')
        if not isinstance(key, str) or key in contracts or not re.fullmatch(r'[a-z0-9-]+', key):
            raise BuildError('duplicate or invalid license id')
        if item.get('spdx_license') != 'CC0-1.0' or item.get('origin_type') not in ('project_original', 'verified_cc0') or item.get('rights_confirmed') is not True:
            raise BuildError('CC0 evidence not approved')
        if not isinstance(item.get('author'), str) or not item['author'].strip() or not VERSION.fullmatch(str(item.get('source_version', ''))):
            raise BuildError('missing author or source version')
        if not isinstance(evidence, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.md', evidence):
            raise BuildError('unsafe rights evidence path')
        file = parent / evidence
        if file.is_symlink() or not file.is_file() or not SHA.fullmatch(str(item.get('evidence_sha256', ''))) or digest(file.read_bytes()) != item['evidence_sha256']:
            raise BuildError('unverifiable rights evidence')
        contracts[key] = item
    return contracts


def _validate_concept(item, seen, terms):
    if not isinstance(item, dict):
        raise BuildError('invalid concept entry')
    concept, sense = item.get('concept_id'), item.get('sense_id')
    if not isinstance(concept, str) or not ID.fullmatch(concept) or concept in seen:
        raise BuildError('unstable or duplicate concept id')
    if not isinstance(sense, str) or not SENSE.fullmatch(sense):
        raise BuildError('missing lexical sense id')
    seen.add(concept)
    if item.get('domain') not in ('home','food','transport','education','healthcare'):
        raise BuildError('domain not allowed')
    if not VERSION.fullmatch(str(item.get('source_version', ''))):
        raise BuildError('invalid source version')
    labels = item.get('labels')
    if not isinstance(labels, dict) or not labels or 'en' not in labels:
        raise BuildError('accessible English fallback required')
    for language, label in labels.items():
        if not isinstance(language, str) or not LANG.fullmatch(language) or not isinstance(label, str) or not 1 <= len(label.strip()) <= 120 or any(ord(c) < 32 for c in label):
            raise BuildError('invalid accessibility label')
    lexemes = item.get('lexemes')
    if not isinstance(lexemes, list) or not lexemes:
        raise BuildError('missing semantic word mapping')
    for lexeme in lexemes:
        if not isinstance(lexeme, dict) or lexeme.get('sense_id') != sense or not isinstance(lexeme.get('language'), str) or not LANG.fullmatch(lexeme['language']) or not isinstance(lexeme.get('lemma'), str) or not 1 <= len(lexeme['lemma']) <= 100:
            raise BuildError('ambiguous lexeme or sense mapping')
        key = (lexeme['language'], lexeme['lemma'], sense)
        if key in terms:
            raise BuildError('duplicate lexeme/sense mapping')
        terms.add(key)


def build_pack(meta_path, rights_path, sources_dir, output_dir, manifest_path, day):
    meta_path, rights_path, sources_dir = Path(meta_path), Path(rights_path), Path(sources_dir)
    output_dir, manifest_path = Path(output_dir), Path(manifest_path)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise BuildError('day must be YYYY-MM-DD')
    # Real calendar validation, not lexical date acceptance.
    from datetime import date
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise BuildError('invalid addition date') from exc
    parent = manifest_path.parent
    if output_dir.parent != parent or output_dir.name != 'fixtures':
        raise BuildError('fixtures must be manifest-relative')
    spec = _load(meta_path)
    contracts = _rights(_load(rights_path), rights_path.parent)
    if spec.get('schema_version') != 1 or not isinstance(spec.get('concepts'), list):
        raise BuildError('unsupported concept registry version')
    previous = _load(manifest_path) if manifest_path.is_file() else None
    existing = {}
    if previous:
        if previous.get('release_status') != 'decoder_pending' or previous.get('schema_version') != 1:
            raise BuildError('cannot modify approved or incompatible media pack')
        for asset in previous.get('assets', []):
            cid, relative = asset.get('concept_id'), asset.get('token_path')
            if not isinstance(cid, str) or cid in existing or not isinstance(relative, str) or not re.fullmatch(r'fixtures/[a-f0-9]{64}\.cvt', relative):
                raise BuildError('malformed existing manifest')
            token_path = parent / relative
            if token_path.is_symlink() or not token_path.is_file() or not SHA.fullmatch(str(asset.get('token_sha256',''))):
                raise BuildError('approved token missing')
            token = token_path.read_bytes()
            if digest(token) != asset['token_sha256'] or len(token) != asset.get('token_bytes'):
                raise BuildError('existing token integrity failure')
            decode_token(token)
            existing[cid] = asset
    seen, terms, new = set(), set(), []
    occupied_geometry = {asset['token_sha256']: asset['sense_id'] for asset in existing.values()}
    for item in sorted(spec['concepts'], key=lambda x: str(x.get('concept_id', ''))):
        _validate_concept(item, seen, terms)
        license_id = item.get('license_id')
        if license_id not in contracts:
            raise BuildError('unknown license evidence')
        source = _safe_inside(sources_dir, item.get('source'))
        content = source.read_bytes()
        try:
            token = compile_svg(content)
            render_svg(token, item['labels']['en'])
        except VectorError as exc:
            raise BuildError(f'unsafe/oversized vector: {item["concept_id"]}') from exc
        token_sha = digest(token)
        sense = item['sense_id']
        if token_sha in occupied_geometry and occupied_geometry[token_sha] != sense:
            raise BuildError('same artwork assigned to different lexical senses without review')
        occupied_geometry[token_sha] = sense
        record = {
            'concept_id': item['concept_id'], 'sense_id': sense, 'domain': item['domain'],
            'source_path': f'sources/{source.name}', 'source_version': item['source_version'],
            'source_sha256': digest(content), 'license_id': license_id,
            'rights_evidence_sha256': contracts[license_id]['evidence_sha256'],
            'token_path': f'fixtures/{token_sha}.cvt', 'token_bytes': len(token),
            'token_sha256': token_sha, 'labels': item['labels'], 'lexemes': item['lexemes'],
            'added_on': day,
        }
        if item['concept_id'] in existing:
            old = existing[item['concept_id']]
            candidate = dict(record, added_on=old['added_on'])
            if candidate != old:
                raise BuildError('approved concept changed: increment version via new ID/review')
        else:
            new.append((record, token))
    if set(existing) - seen:
        raise BuildError('cannot remove an approved concept')
    assets = sorted([*existing.values(), *(item for item, _ in new)], key=lambda x: x['concept_id'])
    manifest = {
        'schema_version': 1, 'format': 'CVT1', 'pack_id': 'semantic-vectors-sample',
        'pack_version': '0.1.0', 'release_status': 'decoder_pending',
        'decoder_compatibility': {'verified': False, 'requires': 'CVT1 offline decoder + renderer golden tests'},
        'token_max_bytes_exclusive': 2048, 'license_policy': 'CC0-1.0 with verified original rights evidence',
        'assets': assets,
    }
    payload = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
    if previous and not new:
        return previous
    # Only append content-addressed assets, then atomically publish manifest LAST.
    for record, token in new:
        dest = parent / record['token_path']
        if dest.exists():
            if dest.is_symlink() or dest.read_bytes() != token:
                raise BuildError('content-address collision or corrupted existing token')
        else:
            _atomic(dest, token)
    _atomic(manifest_path, payload)
    return manifest


def main():
    parser = argparse.ArgumentParser(description='Stage immutable CVT1 fixtures (never publish app packs)')
    parser.add_argument('--root', type=Path, default=Path('media/semantic_vectors'))
    parser.add_argument('--day', required=True)
    args = parser.parse_args()
    root = args.root
    try:
        result = build_pack(root/'concepts.json', root/'provenance.json', root/'sources', root/'fixtures', root/'manifest.json', args.day)
    except (BuildError, VectorError) as exc:
        parser.exit(1, f'REJECTED: {exc}\n')
    print(f"STAGED: {len(result['assets'])} semantic concepts; release_status=decoder_pending")


if __name__ == '__main__':
    main()
