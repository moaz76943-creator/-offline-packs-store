import json
import gzip
import hashlib
import os
import glob
import shutil
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

APPROVED_STATUS = 'APPROVED_FOR_REDISTRIBUTION'
BLOCKED_STATUS = 'BLOCKED_DEPENDENCY'
# A source admits a language only through an explicit code. An unscoped
# approval does not cover the registry.
_SOURCE_LANGUAGE_KEYS = ('languages', 'language', 'language_codes')
_PACK_LANGUAGE_KEYS = ('id', 'language', 'lang', 'code', 'lang_code', 'languages')


def _explicit_codes(value):
    if isinstance(value, str):
        code = value.strip()
        if code and code not in {'*', 'all', 'any'}:
            return {code}
        return set()
    if isinstance(value, list):
        codes = set()
        for item in value:
            codes |= _explicit_codes(item)
        return codes
    return set()


def admitted_languages(ledger):
    """Languages named by an APPROVED_FOR_REDISTRIBUTION source.

    Fail closed: missing ledger, non-approved status, or a source with no
    language field admits nothing. One approved source does not admit every
    registered language.
    """
    if not isinstance(ledger, dict):
        return set()
    sources = ledger.get('sources')
    if not isinstance(sources, list):
        return set()
    admitted = set()
    for source in sources:
        if not isinstance(source, dict) or source.get('status') != APPROVED_STATUS:
            continue
        for key in _SOURCE_LANGUAGE_KEYS:
            admitted |= _explicit_codes(source.get(key))
    return admitted


def manifest_pack_languages(manifest):
    """Languages present in manifest['packs']. Legacy languages[] entries do not count."""
    if not isinstance(manifest, dict):
        return set()
    packs = manifest.get('packs')
    if not isinstance(packs, list):
        return set()
    published = set()
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        for key in _PACK_LANGUAGE_KEYS:
            published |= _explicit_codes(pack.get(key))
    return published


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
        if lang_code not in admitted:
            reasons.append('No APPROVED_FOR_REDISTRIBUTION source names this language.')
        if lang_code not in published:
            reasons.append('No pack for this language in manifest.packs.')
        return {
            'lang_code': lang_code,
            'status': BLOCKED_STATUS,
            'packs': [],
            'reasons': reasons,
        }

    def compute_sha256(self, filepath):
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()

    def is_valid_license(self, license_name):
        if not license_name:
            return False
        license_name_lower = license_name.lower()
        valid = ['public domain', 'cc0', 'cc-by', 'gfdl', 'zero copyright', 'creative commons attribution']
        return any(v in license_name_lower for v in valid)

    def verify_pack(self, lang_code, expected_manifest_data):
        evidence = {
            'lang_code': lang_code,
            'status': 'metadataOnly',
            'packs': [],
            'reasons': []
        }

        # Look for packages belonging to this language (e.g. ru_core_a1.pack.gz, ru_universal_v1.pack.gz)
        # Some packs might not have standard naming but match the registry, we filter exactly those.
        # But wait, looking at `manifest.json`, the pack file is explicitly specified in expected_manifest_data.
        expected_pack_file = expected_manifest_data.get('pack_file') if expected_manifest_data else None

        # In this ecosystem, a language can have multiple packs (e.g. core_a1, universal_v1)
        # So we look for any pack starting with `lang_code_`
        pack_files = glob.glob(os.path.join(self.packs_dir, f"{lang_code}_*.pack.gz"))

        # Some legacy files like deutsch_a1.pack.gz might exist, but we only process ones that match lang_code.

        if not pack_files:
            evidence['status'] = 'sourceMissing' if expected_manifest_data else 'metadataOnly'
            evidence['reasons'].append("No package files found.")
            return evidence

        has_valid_pack = False
        all_packs_license_blocked = True

        for p in pack_files:
            pack_info = {
                'file': os.path.basename(p),
                'actual_sha256': None,
                'valid': False
            }

            actual_hash = self.compute_sha256(p)
            pack_info['actual_sha256'] = actual_hash

            expected_hash = None
            if expected_manifest_data and expected_manifest_data.get('pack_file') == os.path.basename(p):
                expected_hash = expected_manifest_data.get('sha256')

            if expected_hash and actual_hash != expected_hash:
                pack_info['error'] = 'Hash mismatch (stale evidence or invalid signature)'
                evidence['reasons'].append(f"{os.path.basename(p)}: Hash mismatch.")
                evidence['status'] = 'invalidPack'
                evidence['packs'].append(pack_info)
                continue

            try:
                with gzip.open(p, 'rt', encoding='utf-8') as f:
                    first_line = f.readline()
                    data = json.loads(first_line)
            except Exception as e:
                pack_info['error'] = 'Invalid gzip or JSON'
                evidence['reasons'].append(f"{os.path.basename(p)}: Invalid gzip or JSON.")
                evidence['status'] = 'invalidPack'
                evidence['packs'].append(pack_info)
                continue

            pack_lang_code = data.get('lang_code')
            if not pack_lang_code and 'header' in data:
                 pack_lang_code = data['header'].get('code')

            if not pack_lang_code and 'language' in data:
                 # Legacy files might not have lang_code, but if they start with lang_code_ we can be lenient or strict.
                 # Let's enforce strict identity checking. If it doesn't declare the code, it's invalid.
                 pack_info['error'] = f"Missing internal lang_code"
                 evidence['reasons'].append(f"{os.path.basename(p)}: Missing internal lang_code.")
                 evidence['status'] = 'invalidPack'
                 evidence['packs'].append(pack_info)
                 continue

            # Additional check for legacy files missing lang_code altogether
            if pack_lang_code is None:
                pack_info['error'] = f"Mismatched internal lang_code 'None' != '{lang_code}'"
                evidence['reasons'].append(f"{os.path.basename(p)}: Mismatched internal lang_code.")
                evidence['status'] = 'invalidPack'
                evidence['packs'].append(pack_info)
                continue

            if pack_lang_code != lang_code:
                pack_info['error'] = f"Mismatched internal lang_code '{pack_lang_code}' != '{lang_code}'"
                evidence['reasons'].append(f"{os.path.basename(p)}: Mismatched internal lang_code.")
                evidence['status'] = 'invalidPack'
                evidence['packs'].append(pack_info)
                continue

            license_str = data.get('license')
            if not license_str and 'header' in data:
                license_str = data['header'].get('license')
            license_str = license_str or ''

            pack_info['license'] = license_str
            pack_info['terms_count'] = data.get('terms_count', 0)
            pack_info['level'] = data.get('level', '')
            if 'header' in data:
                pack_info['level'] = ', '.join(data['header'].get('levels', []))

            if not self.is_valid_license(license_str):
                pack_info['error'] = f"Invalid or restricted license: {license_str}"
                evidence['reasons'].append(f"{os.path.basename(p)}: Invalid license.")
                evidence['status'] = 'licenseBlocked'
                evidence['packs'].append(pack_info)
                continue

            all_packs_license_blocked = False
            pack_info['valid'] = True
            has_valid_pack = True
            evidence['packs'].append(pack_info)

        if evidence['status'] not in ['invalidPack']:
            if has_valid_pack:
                evidence['status'] = 'releaseReady'
                evidence['reasons'] = []
            elif all_packs_license_blocked and pack_files:
                evidence['status'] = 'licenseBlocked'

        return evidence

    def compile(self, output_path='tools/final_release_evidence/release_evidence.json'):
        registry_data = self.load_registry()
        manifest_document = self.load_manifest_document()
        manifest_data = {
            lang['code']: lang for lang in manifest_document.get('languages', [])
            if isinstance(lang, dict) and 'code' in lang
        }
        admitted = admitted_languages(self.load_ledger())
        published = manifest_pack_languages(manifest_document)

        results = {
            'schema_version': '1.0.0',
            'readiness_rule': 'releaseReady requires an APPROVED_FOR_REDISTRIBUTION source that names the language and a pack in manifest.packs',
            'total_languages': len(registry_data),
            'languages': {}
        }

        for lang_code in sorted(registry_data.keys()):
            if lang_code not in admitted or lang_code not in published:
                evidence = self.blocked_dependency(lang_code, admitted, published)
            else:
                evidence = self.verify_pack(lang_code, manifest_data.get(lang_code))
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
