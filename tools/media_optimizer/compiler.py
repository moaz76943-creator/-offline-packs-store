import json
import zlib
import hashlib
import os
import shutil
import tempfile

class TokenValidationError(Exception): pass
class DiskSpaceError(Exception): pass
class CompilationError(Exception): pass

class MediaCompiler:
    def __init__(self, output_dir, staging_dir=None):
        self.output_dir = output_dir
        self.staging_dir = staging_dir or tempfile.mkdtemp()
        self.max_bytes = 2048
        self.max_paths = 50
        self.supported_encodings = ['v1', 'v2']
        self.valid_licenses = ['CC0', 'CC-BY', 'CC0-1.0', 'PUBLIC-DOMAIN', 'GFDL-1.3-only', 'CC-BY-SA-4.0']

    def check_disk_space(self, required_bytes=1024*1024):
        total, used, free = shutil.disk_usage(self.staging_dir)
        if free < required_bytes:
            raise DiskSpaceError("Insufficient disk space")

    def validate_token(self, raw):
        if len(raw) >= self.max_bytes:
            raise TokenValidationError("Token size exceeds max limit")

        try:
            decompressed = zlib.decompress(raw)
            token = json.loads(decompressed)
        except Exception:
            raise TokenValidationError("Invalid format or not zlib compressed JSON")

        if token.get('version') not in self.supported_encodings:
            raise TokenValidationError("Unsupported encoding version")

        if not isinstance(token.get('paths'), list) or len(token['paths']) > self.max_paths:
            raise TokenValidationError("Malformed geometry or too many paths")

        evidence = token.get('source_evidence', {})
        if evidence.get('license') not in self.valid_licenses:
            raise TokenValidationError("Invalid or missing license")

        if not token.get('concept_id') or not token.get('source_hash'):
            raise TokenValidationError("Missing concept_id or source_hash")

        return token

    def deduplicate_geometry(self, tokens):
        geometry_pool = {}
        geometry_list = []

        for token in tokens:
            geom_str = json.dumps(token['paths'], sort_keys=True)
            geom_hash = hashlib.sha256(geom_str.encode()).hexdigest()
            if geom_hash not in geometry_pool:
                geometry_pool[geom_hash] = len(geometry_list)
                geometry_list.append(token['paths'])
            token['geometry_ref'] = geometry_pool[geom_hash]

        return geometry_list, tokens

    def compile(self, raw_tokens, prior_pack_meta=None, runtime_evidence=None):
        if runtime_evidence is None or not runtime_evidence.get('compatible'):
            raise CompilationError("Cannot mark pack production-ready without downstream runtime decoder compatibility evidence")

        self.check_disk_space()

        valid_tokens = []
        for raw in raw_tokens:
            try:
                valid_tokens.append(self.validate_token(raw))
            except TokenValidationError:
                continue # ignore invalid tokens in this simple pass

        valid_tokens.sort(key=lambda x: x['concept_id'])

        geometry_list, processed_tokens = self.deduplicate_geometry(valid_tokens)

        # Build pack
        pack_data = {
            'geometry_pool': geometry_list,
            'concepts': {}
        }
        for t in processed_tokens:
            pack_data['concepts'][t['concept_id']] = {
                'geometry_ref': t['geometry_ref'],
                'version': t['version'],
                'source_hash': t['source_hash'],
                'palette': t.get('palette'),
                'semantic_label': t.get('semantic_label'),
                'viewBox': t.get('viewBox')
            }

        pack_json = json.dumps(pack_data, sort_keys=True)
        pack_bytes = zlib.compress(pack_json.encode())

        # Atomically write pack
        pack_filename = os.path.join(self.staging_dir, 'pack.vct')
        try:
            with open(pack_filename, 'wb') as f:
                f.write(pack_bytes)
        except OSError:
            raise DiskSpaceError("Failed to write to disk, possibly insufficient space")

        pack_hash = hashlib.sha256(pack_bytes).hexdigest()
        meta = {
            'sha256': pack_hash,
            'size': len(pack_bytes),
            'concept_count': len(processed_tokens)
        }

        delta_plan = {}
        change_events = []
        if prior_pack_meta:
            prior_concepts = prior_pack_meta.get('concepts', {})
            for cid, current_data in pack_data['concepts'].items():
                if cid not in prior_concepts:
                    change_events.append({"type": "added", "concept_id": cid})
                elif prior_concepts[cid]['source_hash'] != current_data['source_hash']:
                    change_events.append({"type": "updated", "concept_id": cid})
                else:
                    change_events.append({"type": "unchanged", "concept_id": cid})

            for cid in prior_concepts:
                if cid not in pack_data['concepts']:
                    change_events.append({"type": "deleted", "concept_id": cid})

            delta_plan = {"changes": change_events}

        os.makedirs(self.output_dir, exist_ok=True)
        final_pack_path = os.path.join(self.output_dir, 'pack.vct')
        shutil.move(pack_filename, final_pack_path)

        decoder_manifest = {
            'supported_encodings': self.supported_encodings,
            'max_paths': self.max_paths,
            'max_bytes': self.max_bytes
        }

        return {
            'metadata': meta,
            'delta_plan': delta_plan,
            'change_events': change_events,
            'decoder_manifest': decoder_manifest,
            'pack_data_for_future': pack_data # just for tests
        }
