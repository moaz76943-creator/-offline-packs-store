import json
import zlib
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from legal.ledger.admission import SCHEMA, evaluate

class TokenValidationError(Exception): pass
class DiskSpaceError(Exception): pass
class CompilationError(Exception): pass

class MediaCompiler:
    def __init__(self, output_dir, staging_dir=None, repo_root=None):
        self.output_dir = output_dir
        self.staging_dir = staging_dir or tempfile.mkdtemp()
        self.repo_root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[2]
        self.max_bytes = 2048
        self.max_decoded_bytes = 64 * 1024
        self.max_paths = 50
        self.supported_encodings = ['v1', 'v2']

    def _ensure_space(self, path, required_bytes):
        os.makedirs(path, exist_ok=True)
        _total, _used, free = shutil.disk_usage(path)
        if free < required_bytes:
            raise DiskSpaceError("Insufficient disk space")

    def check_disk_space(self, required_bytes=1024*1024):
        self._ensure_space(self.staging_dir, required_bytes)
        self._ensure_space(self.output_dir, required_bytes)

    def _decompress_token(self, raw):
        if not isinstance(raw, (bytes, bytearray)):
            raise TokenValidationError("Invalid format or not zlib compressed JSON")
        decoder = zlib.decompressobj()
        try:
            decompressed = decoder.decompress(bytes(raw), self.max_decoded_bytes + 1)
        except zlib.error as exc:
            raise TokenValidationError("Invalid format or not zlib compressed JSON") from exc
        # Stop before a compressed bomb expands without a bound. Do not flush
        # leftover output: flush would resume an unbounded inflate.
        if len(decompressed) > self.max_decoded_bytes or decoder.unconsumed_tail:
            raise TokenValidationError("Decompressed token exceeds limit")
        if not decoder.eof or decoder.unused_data:
            raise TokenValidationError("Invalid format or not zlib compressed JSON")
        return decompressed

    def _load_canonical_ledger(self):
        path = self.repo_root / 'legal' / 'ledger' / 'sources.json'
        try:
            if path.is_symlink() or not path.is_file():
                raise TokenValidationError("Provenance ledger unavailable")
            ledger = json.loads(path.read_text(encoding='utf-8'))
        except TokenValidationError:
            raise
        except (OSError, ValueError) as exc:
            raise TokenValidationError("Provenance ledger unavailable") from exc
        if (not isinstance(ledger, dict) or ledger.get('schema_version') != SCHEMA
                or not isinstance(ledger.get('sources'), list)):
            raise TokenValidationError("Provenance ledger unavailable")
        return ledger

    def _require_admitted_provenance(self, evidence):
        """A caller license label is not redistribution rights.

        The token may only reference a source record already stored in the
        canonical ledger. This method does not create licenses, approvals,
        or evidence files. Missing proof fails closed.
        """
        source_id = evidence.get('source_id')
        dataset_version = evidence.get('dataset_version')
        artifact_sha = evidence.get('artifact_sha256')
        if (not isinstance(source_id, str) or not source_id.strip()
                or not isinstance(dataset_version, str) or not dataset_version.strip()
                or not isinstance(artifact_sha, str) or not artifact_sha.strip()):
            raise TokenValidationError("Admitted provenance reference required")
        ledger = self._load_canonical_ledger()
        matches = [source for source in ledger['sources']
                   if isinstance(source, dict) and source.get('source_id') == source_id]
        if len(matches) != 1:
            raise TokenValidationError("Admitted provenance record absent")
        source = matches[0]
        retrieval = source.get('retrieval') if isinstance(source.get('retrieval'), dict) else {}
        if (dataset_version != source.get('dataset_version')
                or artifact_sha != retrieval.get('sha256')):
            raise TokenValidationError("Provenance reference does not match the ledger snapshot")
        license_info = source.get('license') if isinstance(source.get('license'), dict) else {}
        if 'license' in evidence and evidence.get('license') != license_info.get('id'):
            raise TokenValidationError("Caller license label is not admitted provenance")
        if source.get('kind') != 'vector_art':
            raise TokenValidationError("Separate vector-art rights proof required")
        blockers = evaluate(
            {'schema_version': SCHEMA, 'sources': [source]},
            {'languages': [], 'packs': []},
            [],
            self.repo_root,
        )
        if blockers:
            raise TokenValidationError("Provenance not admitted: " + "; ".join(blockers))
        return source

    def validate_token(self, raw):
        if len(raw) >= self.max_bytes:
            raise TokenValidationError("Token size exceeds max limit")

        try:
            decompressed = self._decompress_token(raw)
            token = json.loads(decompressed)
        except TokenValidationError:
            raise
        except Exception as exc:
            raise TokenValidationError("Invalid format or not zlib compressed JSON") from exc

        if not isinstance(token, dict):
            raise TokenValidationError("Decoded token must be a JSON object")

        if token.get('version') not in self.supported_encodings:
            raise TokenValidationError("Unsupported encoding version")

        if not isinstance(token.get('paths'), list) or len(token['paths']) > self.max_paths:
            raise TokenValidationError("Malformed geometry or too many paths")

        evidence = token.get('source_evidence', None)
        if not isinstance(evidence, dict):
            raise TokenValidationError("source_evidence must be an object")

        concept_id = token.get('concept_id')
        source_hash = token.get('source_hash')
        if (not isinstance(concept_id, str) or not concept_id.strip()
                or not isinstance(source_hash, str) or not source_hash.strip()):
            raise TokenValidationError("Missing concept_id or source_hash")

        self._require_admitted_provenance(evidence)
        return token

    def _reject_duplicate_concepts(self, tokens):
        counts = {}
        for token in tokens:
            concept_id = token['concept_id']
            counts[concept_id] = counts.get(concept_id, 0) + 1
        duplicates = sorted(concept_id for concept_id, count in counts.items() if count > 1)
        if duplicates:
            raise CompilationError("duplicate concept_id: " + ", ".join(duplicates))

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

    def _publish_atomic(self, pack_bytes):
        """Replace pack.vct on the output filesystem only.

        A temporary file in output_dir is flushed and renamed with os.replace.
        shutil.move is not used: across filesystems it copies onto the live pack.
        """
        self._ensure_space(self.output_dir, len(pack_bytes))
        final_path = os.path.join(self.output_dir, 'pack.vct')
        fd, tmp_name = tempfile.mkstemp(prefix='.pack-', suffix='.tmp', dir=self.output_dir)
        replaced = False
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(pack_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, final_path)
            replaced = True
        except OSError as exc:
            raise DiskSpaceError("Failed to write to disk, possibly insufficient space") from exc
        finally:
            if not replaced and tmp_name and os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
        try:
            dir_fd = os.open(self.output_dir, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
        return final_path

    def compile(self, raw_tokens, prior_pack_meta=None, runtime_evidence=None):
        if runtime_evidence is None or not runtime_evidence.get('compatible'):
            raise CompilationError("Cannot mark pack production-ready without downstream runtime decoder compatibility evidence")

        self.check_disk_space()

        valid_tokens = []
        for raw in raw_tokens:
            try:
                valid_tokens.append(self.validate_token(raw))
            except TokenValidationError as exc:
                raise CompilationError(
                    "invalid input token; refusing to publish a partial snapshot"
                ) from exc

        self._reject_duplicate_concepts(valid_tokens)
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

        pack_hash = hashlib.sha256(pack_bytes).hexdigest()
        meta = {
            'sha256': pack_hash,
            'size': len(pack_bytes),
            'concept_count': len(pack_data['concepts'])
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

        self._publish_atomic(pack_bytes)

        decoder_manifest = {
            'supported_encodings': self.supported_encodings,
            'max_paths': self.max_paths,
            'max_bytes': self.max_bytes,
            'max_decoded_bytes': self.max_decoded_bytes
        }

        return {
            'metadata': meta,
            'delta_plan': delta_plan,
            'change_events': change_events,
            'decoder_manifest': decoder_manifest,
            'pack_data_for_future': pack_data # just for tests
        }
