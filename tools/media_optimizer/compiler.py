import os
import json
import zlib
import hashlib
import tempfile
import shutil
from pathlib import Path

class TokenValidationError(Exception):
    pass

class MediaPackCompiler:
    def __init__(self):
        self.max_bytes = 2048
        self.max_paths = 50
        self.valid_licenses = {'CC0', 'authorized'}
        self.supported_encoding_versions = {1, 2}

    def canonical_json(self, data):
        return json.dumps(data, separators=(',', ':'), sort_keys=True).encode('utf-8')

    def canonical_hash(self, data):
        return hashlib.sha256(self.canonical_json(data)).hexdigest()

    def decode_token(self, vct_bytes):
        if len(vct_bytes) >= self.max_bytes:
            raise TokenValidationError(f"Token exceeds {self.max_bytes} bytes")

        try:
            json_bytes = zlib.decompress(vct_bytes)
        except zlib.error:
            raise TokenValidationError("Invalid zlib compression")

        try:
            token_data = json.loads(json_bytes.decode('utf-8'))
        except json.JSONDecodeError:
            raise TokenValidationError("Invalid JSON metadata")

        return token_data

    def validate_token_data(self, token_data):
        if 'paths' not in token_data or not isinstance(token_data['paths'], list):
            raise TokenValidationError("Missing or invalid geometry (paths)")
        if len(token_data['paths']) > self.max_paths:
            raise TokenValidationError(f"Geometry exceeds {self.max_paths} paths")

        if token_data.get('license') not in self.valid_licenses:
            raise TokenValidationError(f"Unsupported license: {token_data.get('license')}")

        if token_data.get('version') not in self.supported_encoding_versions:
            raise TokenValidationError(f"Unsupported encoding version: {token_data.get('version')}")

        if not token_data.get('concept_id'):
            raise TokenValidationError("Missing concept_id")

        if 'source_hash' not in token_data:
            raise TokenValidationError("Missing source_hash")

    def compile_pack(self, vct_tokens, prior_pack_index, output_dir, downstream_evidence):
        if not downstream_evidence:
            raise ValueError("Downstream WordBit decoder compatibility evidence is required.")

        tokens_by_concept = {}
        geometry_pool = {}
        geometry_mapping = {}

        # 1. Parse and Validate
        for vct_bytes in vct_tokens:
            token_data = self.decode_token(vct_bytes)
            self.validate_token_data(token_data)

            concept_id = token_data['concept_id']
            # Generate deterministic SHA-256 for the canonical uncompressed JSON string
            canonical_bytes = self.canonical_json(token_data)
            token_hash = hashlib.sha256(canonical_bytes).hexdigest()

            # Deduplicate geometry
            geometry = token_data['paths']
            geometry_json = json.dumps(geometry, separators=(',', ':'), sort_keys=True)
            geometry_hash = hashlib.sha256(geometry_json.encode('utf-8')).hexdigest()

            if geometry_hash not in geometry_pool:
                geometry_pool[geometry_hash] = geometry

            geometry_mapping[concept_id] = geometry_hash
            tokens_by_concept[concept_id] = {
                'concept_id': concept_id,
                'token_hash': token_hash,
                'geometry_hash': geometry_hash,
                'version': token_data['version'],
                'license': token_data['license'],
                'size_bytes': len(vct_bytes)
            }

        # 2. Prepare Output Index
        pack_index = {
            'concepts': dict(sorted(tokens_by_concept.items())),
            'geometries': dict(sorted(geometry_pool.items()))
        }

        # Generate package metadata (SHA-256 and actual size)
        pack_json_bytes = json.dumps(pack_index, separators=(',', ':'), sort_keys=True).encode('utf-8')
        package_metadata = {
            'sha256': hashlib.sha256(pack_json_bytes).hexdigest(),
            'size_bytes': len(pack_json_bytes)
        }
        pack_index['package_metadata'] = package_metadata

        # 3. Compare with prior pack to generate delta and events
        events = {'unchanged': [], 'updated': [], 'deleted': [], 'invalid': []}
        delta = {'updated_concepts': {}, 'deleted_concepts': []}

        if prior_pack_index and 'concepts' in prior_pack_index:
            old_concepts = prior_pack_index['concepts']
            new_concepts = pack_index['concepts']

            for cid, new_meta in new_concepts.items():
                if cid not in old_concepts:
                    events['updated'].append(cid)
                    delta['updated_concepts'][cid] = new_meta
                else:
                    if old_concepts[cid]['token_hash'] != new_meta['token_hash']:
                        events['updated'].append(cid)
                        delta['updated_concepts'][cid] = new_meta
                    else:
                        events['unchanged'].append(cid)

            for cid in old_concepts:
                if cid not in new_concepts:
                    events['deleted'].append(cid)
                    delta['deleted_concepts'].append(cid)
        else:
            # All are updated/new if no prior pack
            for cid in pack_index['concepts']:
                events['updated'].append(cid)
                delta['updated_concepts'][cid] = pack_index['concepts'][cid]

        # 4. Atomic Staging
        temp_dir = tempfile.mkdtemp(dir=os.path.dirname(output_dir) or '.')
        try:
            # Write pack.json
            pack_path = os.path.join(temp_dir, 'pack.json')
            with open(pack_path, 'wb') as f:
                f.write(pack_json_bytes)

            # Write delta.json
            delta_path = os.path.join(temp_dir, 'delta.json')
            with open(delta_path, 'w', encoding='utf-8') as f:
                json.dump(delta, f, indent=2, sort_keys=True)

            # Write events.json
            events_path = os.path.join(temp_dir, 'events.json')
            with open(events_path, 'w', encoding='utf-8') as f:
                json.dump(events, f, indent=2, sort_keys=True)

            # Write decoder manifest
            manifest_path = os.path.join(temp_dir, 'wordbit_decoder_compatibility.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump({'compatible': True, 'max_paths': self.max_paths, 'max_bytes': self.max_bytes}, f, indent=2)

            # Atomic replace
            # By standardizing on rename, it will overwrite empty dirs or files, but rmtree first
            # is non-atomic and might be where it failed in the test.
            # We'll use os.replace to perform an atomic overwrite instead of os.rename.
            if os.path.exists(output_dir) and os.path.isdir(output_dir):
                # If output_dir already exists and is a directory, replacing it directly with rename
                # might fail if it's not empty on some OS.
                # In unix, rename a dir over a non-empty dir fails.
                # A common pattern is to rename the old dir to a backup dir, then rename new to old.
                backup_dir = temp_dir + "_backup"
                os.rename(output_dir, backup_dir)
                try:
                    os.rename(temp_dir, output_dir)
                except Exception as ex:
                    os.rename(backup_dir, output_dir)
                    raise ex
                shutil.rmtree(backup_dir)
            else:
                os.replace(temp_dir, output_dir)

        except Exception as e:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise e

        return pack_index
