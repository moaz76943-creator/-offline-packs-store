import re
import json
import gzip
import hashlib
import os
import glob
import shutil
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class EvidenceCompiler:
    def __init__(self, registry_path='catalog/language_registry.v1.json', manifest_path='manifest.json', packs_dir='packs'):
        self.registry_path = registry_path
        self.manifest_path = manifest_path
        self.packs_dir = packs_dir

    def load_registry(self):
        with open(self.registry_path, 'r') as f:
            data = json.load(f)
        return {lang['id']: lang for lang in data.get('languages', [])}

    def load_manifest(self):
        with open(self.manifest_path, 'r') as f:
            data = json.load(f)
        return {lang['code']: lang for lang in data.get('languages', [])}

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
            m = re.search(r'(v\d+|a\d+)\.pack\.gz$', os.path.basename(p))
            pack_info['version'] = m.group(1) if m else 'unknown'

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
            pack_info['cefr_evidence'] = []
            pack_info['media_identities'] = [d.get('icon_vector') for d in data.get('domains', []) if 'icon_vector' in d]
            level_data = data.get('level', '')
            if level_data:
                pack_info['cefr_evidence'].extend([l.strip() for l in level_data.split(',') if l.strip()])
            if 'header' in data:
                pack_info['cefr_evidence'].extend(data['header'].get('levels', []))
            pack_info['level'] = ', '.join(pack_info['cefr_evidence'])

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
                is_release_ready = True
                has_cefr = False
                has_media = False
                for p_info in evidence['packs']:
                    if p_info.get('level'):
                        has_cefr = True
                    if p_info.get('media_identities'):
                        has_media = True

                if has_cefr and has_media and any(p.get('terms_count', 0) > 0 for p in evidence['packs']):
                    evidence['status'] = 'releaseReady'
                else:
                    evidence['status'] = 'verified'
                    evidence['reasons'].append('Missing CEFR, media, or lexical counts.')
                evidence['reasons'] = [r for r in evidence['reasons'] if r != 'No package files found.']
            elif all_packs_license_blocked and pack_files:
                evidence['status'] = 'licenseBlocked'


        return evidence

    def compile(self, output_path='tools/final_release_evidence/release_evidence.json'):
        registry_data = self.load_registry()
        manifest_data = self.load_manifest()

        results = {
            'schema_version': '1.0.0',
            'total_languages': len(registry_data),
            'languages': {}
        }

        for lang_code in sorted(registry_data.keys()):
            manifest_info = manifest_data.get(lang_code)
            evidence = self.verify_pack(lang_code, manifest_info)
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
