import json
import hashlib
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

APPROVED_STATUS = 'APPROVED_FOR_REDISTRIBUTION'
BLOCKED_STATUS = 'BLOCKED_DEPENDENCY'
# Ledger sources cannot name a language: schema.json sets additionalProperties
# false and has no languages/language/language_codes field. The language comes
# from the published pack, and the pack's source refs must match an approved source.
_PACK_LANGUAGE_KEYS = ('languageCode', 'language', 'lang', 'code', 'lang_code', 'id')
_SOURCE_ID_KEYS = ('source_ids', 'sourceIds', 'source_id')
_SOURCE_REF_KEYS = ('source_refs', 'sourceRefs')
_UNSCOPED = {'*', 'all', 'any'}


def _explicit_code(value):
    if not isinstance(value, str):
        return None
    code = value.strip()
    if not code or code in _UNSCOPED:
        return None
    return code


def _pack_entries(manifest):
    if not isinstance(manifest, dict):
        return []
    packs = manifest.get('packs')
    if not isinstance(packs, list):
        return []
    return [pack for pack in packs if isinstance(pack, dict)]


def pack_language(pack):
    """Single language named by the pack entry itself. Ambiguous entries match nothing."""
    if not isinstance(pack, dict):
        return None
    codes = set()
    for key in _PACK_LANGUAGE_KEYS:
        code = _explicit_code(pack.get(key))
        if code:
            codes.add(code)
    if len(codes) != 1:
        return None
    return next(iter(codes))


def pack_source_refs(pack):
    """Source provenance carried on a manifest.packs entry."""
    if not isinstance(pack, dict):
        return []
    refs = []
    for key in _SOURCE_REF_KEYS:
        value = pack.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str) and item.strip():
                refs.append({'source_id': item.strip()})
            elif isinstance(item, dict) and isinstance(item.get('source_id'), str) and item['source_id'].strip():
                refs.append(item)
    for key in _SOURCE_ID_KEYS:
        value = pack.get(key)
        if isinstance(value, str) and value.strip():
            refs.append({'source_id': value.strip()})
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    refs.append({'source_id': item.strip()})
    return refs


def _approved_index(ledger):
    if not isinstance(ledger, dict):
        return {}
    sources = ledger.get('sources')
    if not isinstance(sources, list):
        return {}
    approved = {}
    for source in sources:
        if not isinstance(source, dict) or source.get('status') != APPROVED_STATUS:
            continue
        source_id = source.get('source_id')
        if isinstance(source_id, str) and source_id:
            approved[source_id] = source
    return approved


def _ref_matches(ref, source):
    if not source or source.get('status') != APPROVED_STATUS:
        return False
    if ref.get('source_id') != source.get('source_id'):
        return False
    if 'dataset_version' in ref and ref.get('dataset_version') != source.get('dataset_version'):
        return False
    if 'artifact_sha256' in ref:
        retrieval = source.get('retrieval') if isinstance(source.get('retrieval'), dict) else {}
        if ref.get('artifact_sha256') != retrieval.get('sha256'):
            return False
    return True


def pack_bound_to_approved_source(pack, ledger):
    """True when every source ref on the pack matches an approved ledger source."""
    refs = pack_source_refs(pack)
    if not refs:
        return False
    approved = _approved_index(ledger)
    return all(_ref_matches(ref, approved.get(ref.get('source_id'))) for ref in refs)


def admitted_languages(ledger, manifest=None):
    """Languages whose published pack cites an APPROVED_FOR_REDISTRIBUTION source.

    Schema-valid ledger entries do not carry a language, so a ledger alone admits
    nothing. Passing manifest.packs supplies the language and the source binding.
    """
    if manifest is None:
        return set()
    return {
        language
        for pack in _pack_entries(manifest)
        if (language := pack_language(pack)) and pack_bound_to_approved_source(pack, ledger)
    }


def manifest_pack_languages(manifest):
    """Languages present in manifest['packs']. Legacy languages[] entries do not count."""
    return {language for pack in _pack_entries(manifest) if (language := pack_language(pack))}


class EvidenceCompiler:
    def __init__(self, registry_path='catalog/language_registry.v1.json', manifest_path='manifest.json', packs_dir='packs', ledger_path='legal/ledger/sources.json'):
        self.registry_path = registry_path
        self.manifest_path = manifest_path
        self.packs_dir = packs_dir
        self.ledger_path = ledger_path

    def load_registry(self):
        with open(self.registry_path, 'r') as f:
            data = json.load(f)
        return {lang['id']: lang for lang in data.get('languages', [])}

    def load_manifest_document(self):
        with open(self.manifest_path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('manifest must be an object')
        return data

    def load_manifest(self):
        data = self.load_manifest_document()
        return {lang['code']: lang for lang in data.get('languages', []) if isinstance(lang, dict) and 'code' in lang}

    def load_ledger(self):
        if not os.path.exists(self.ledger_path):
            return {'schema_version': '1.0.0', 'sources': []}
        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {'schema_version': '1.0.0', 'sources': []}
        return data

    def blocked_dependency(self, lang_code, admitted, published):
        """No legacy pack file is treated as valid while admission is missing."""
        reasons = []
        if lang_code not in published:
            reasons.append('No pack for this language in manifest.packs.')
        if lang_code not in admitted:
            reasons.append('No APPROVED_FOR_REDISTRIBUTION source is bound by manifest.packs.')

        status = BLOCKED_STATUS
        if lang_code not in published and lang_code not in admitted:
            status = 'metadataOnly'
        elif lang_code not in admitted:
            status = 'licenseBlocked'

        return {
            'lang_code': lang_code,
            'status': status,
            'packs': [],
            'reasons': reasons,
        }

    def compute_sha256(self, filepath):
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()

    def published_pack_path(self, pack):
        """Resolve manifest.packs path inside packs_dir. Absolute paths and '..' are refused."""
        raw = pack.get('path') if isinstance(pack, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            return None
        raw = raw.strip()
        if os.path.isabs(raw):
            return None
        parts = Path(raw).parts
        if not parts or any(part in ('..', '') for part in parts):
            return None
        packs_root = Path(self.packs_dir).resolve()
        if len(parts) == 1:
            candidate = Path(self.packs_dir) / parts[0]
        else:
            candidate = packs_root.parent / raw
        if candidate.is_symlink():
            return None
        try:
            resolved = candidate.resolve()
            resolved.relative_to(packs_root)
        except (OSError, ValueError):
            return None
        return candidate

    def verify_published_pack(self, lang_code, pack):
        """releaseReady only when this manifest.packs entry's file exists and its sha256 matches."""
        declared = pack.get('path') if isinstance(pack.get('path'), str) else ''
        info = {
            'file': declared,
            'actual_sha256': None,
            'valid': False,
        }
        evidence = {
            'lang_code': lang_code,
            'status': 'sourceMissing',
            'packs': [info],
            'reasons': [],
        }
        path = self.published_pack_path(pack)
        if path is None or not path.is_file():
            info['error'] = 'Published pack file is missing or outside packs/'
            evidence['reasons'].append(f'{declared or lang_code}: published pack file is missing.')
            evidence['status'] = 'sourceMissing'
            return evidence
        expected = pack.get('sha256')
        actual = self.compute_sha256(path)
        info['actual_sha256'] = actual
        if not isinstance(expected, str) or len(expected) != 64 or expected != actual:
            info['error'] = 'Published pack sha256 does not match'
            evidence['reasons'].append(f'{declared}: published pack sha256 does not match.')
            evidence['status'] = 'invalidPack'
            return evidence
        info['valid'] = True
        evidence['status'] = 'releaseReady'
        evidence['reasons'] = []
        return evidence

    def compile(self, output_path='tools/final_release_evidence/release_evidence.json'):
        registry_data = self.load_registry()
        manifest_document = self.load_manifest_document()
        ledger = self.load_ledger()
        admitted = admitted_languages(ledger, manifest_document)
        published = manifest_pack_languages(manifest_document)
        packs_for = {}
        for pack in _pack_entries(manifest_document):
            language = pack_language(pack)
            if language:
                packs_for.setdefault(language, []).append(pack)

        results = {
            'schema_version': '1.0.0',
            'readiness_rule': (
                'releaseReady requires a manifest.packs entry whose source provenance matches '
                'an APPROVED_FOR_REDISTRIBUTION ledger source and whose path exists with a matching sha256'
            ),
            'total_languages': len(registry_data),
            'languages': {}
        }

        for lang_code in sorted(registry_data.keys()):
            bound = [pack for pack in packs_for.get(lang_code, []) if pack_bound_to_approved_source(pack, ledger)]
            if lang_code not in admitted or lang_code not in published or not bound:
                evidence = self.blocked_dependency(lang_code, admitted, published)
            else:
                rows = [self.verify_published_pack(lang_code, pack) for pack in bound]
                evidence = {
                    'lang_code': lang_code,
                    'status': 'releaseReady',
                    'packs': [],
                    'reasons': [],
                }
                for row in rows:
                    evidence['packs'].extend(row['packs'])
                    if row['status'] == 'invalidPack':
                        evidence['status'] = 'invalidPack'
                        evidence['reasons'].extend(row['reasons'])
                    elif row['status'] != 'releaseReady' and evidence['status'] != 'invalidPack':
                        evidence['status'] = row['status']
                        evidence['reasons'].extend(row['reasons'])
                if evidence['status'] == 'releaseReady':
                    evidence['reasons'] = []
            results['languages'][lang_code] = evidence

        tmp_path = output_path + '.tmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, sort_keys=True)
            os.rename(tmp_path, output_path)
            logging.info(f"Successfully compiled evidence for {len(registry_data)} languages.")
        except Exception as e:
            logging.error(f"Failed to write evidence: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

if __name__ == '__main__':
    compiler = EvidenceCompiler()
    compiler.compile()
