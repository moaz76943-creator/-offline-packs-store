import json
import zlib
import base64
import hashlib
import os
import shutil
import tempfile

MAX_TOKEN_SIZE = 2048
MAX_PATHS = 50

def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def compact_json(data: dict) -> str:
    return json.dumps(data, separators=(',', ':'), sort_keys=True)

def validate_token(file_path: str, expected_metadata: dict = None) -> tuple[str, str, str, dict]:
    """
    Validates a J053 semantic vector token.
    Returns (canonical_token_hash, canonical_geometry_hash, base64_compact_string, parsed_json)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Token file not found: {file_path}")

    file_size = os.path.getsize(file_path)
    if file_size >= MAX_TOKEN_SIZE:
        raise ValueError(f"Token size {file_size} exceeds {MAX_TOKEN_SIZE} bytes")

    with open(file_path, 'rb') as f:
        raw_data = f.read()

    try:
        decompressed = zlib.decompress(raw_data)
    except zlib.error:
        raise ValueError("Token is not valid zlib compressed data")

    try:
        data = json.loads(decompressed.decode('utf-8'))
    except json.JSONDecodeError:
        raise ValueError("Token does not contain valid JSON")

    # Validation
    license_id = data.get('license_id')
    if license_id not in ('CC0-1.0', 'PUBLIC-DOMAIN'):
        raise ValueError(f"Invalid license: {license_id}. Must be CC0-1.0 or PUBLIC-DOMAIN.")

    if 'concept_id' not in data or 'version' not in data or 'source_hash' not in data:
        raise ValueError("Missing required provenance fields (concept_id, version, source_hash)")

    # Check geometry
    if 'geometry' not in data:
        raise ValueError("Missing geometry")

    geom = data['geometry']
    if geom.get('encoding_version') not in ('1', 1):
        raise ValueError(f"Unsupported encoding version: {geom.get('encoding_version')}")

    paths = geom.get('paths', [])
    if not isinstance(paths, list):
        raise ValueError("Geometry paths must be a list")

    if len(paths) > MAX_PATHS:
        raise ValueError(f"Geometry path count {len(paths)} exceeds bounded memory limit of {MAX_PATHS}")

    if len(paths) == 0:
        raise ValueError("Malformed geometry: no paths")

    for path in paths:
        if 'd' not in path:
            raise ValueError("Malformed geometry: missing path data")

    # Canonical token hash
    canonical_json_str = compact_json(data)
    canonical_bytes = canonical_json_str.encode('utf-8')
    canonical_token_hash = compute_sha256(canonical_bytes)

    # Canonical geometry hash
    canonical_geometry_str = compact_json(geom)
    canonical_geometry_hash = compute_sha256(canonical_geometry_str.encode('utf-8'))

    recompressed = zlib.compress(canonical_bytes)
    base64_compact = base64.b64encode(recompressed).decode('ascii')

    return canonical_token_hash, canonical_geometry_hash, base64_compact, data

class MediaPackCompiler:
    def __init__(self, prior_pack_index=None):
        self.prior_pack_index = prior_pack_index or {}

        self.geometries = {} # geometry_hash -> base64_data
        self.concepts = {} # concept_id -> dict
        self.stats = {
            'added': 0,
            'reused': 0,
            'deleted': 0
        }
        self.delta_plan = {
            'added': [],
            'reused': [],
            'deleted': []
        }

    def add_token(self, file_path: str, metadata: dict):
        concept_id = metadata.get('concept_id')
        version = metadata.get('version')
        source_hash = metadata.get('source_hash')
        label = metadata.get('semantic_label', '')

        if not concept_id or not version or not source_hash:
            raise ValueError("Metadata must include concept_id, version, and source_hash")

        if concept_id in self.prior_pack_index:
            prior_meta = self.prior_pack_index[concept_id]
            if prior_meta.get('version') == version and prior_meta.get('source_hash') == source_hash:
                geom_hash = prior_meta.get('geometry_hash')
                base64_data = prior_meta.get('base64_data')
                if geom_hash and base64_data:
                    self.geometries[geom_hash] = base64_data
                    self.concepts[concept_id] = {
                        'version': version,
                        'source_hash': source_hash,
                        'token_hash': prior_meta.get('token_hash'),
                        'geometry_hash': geom_hash,
                        'label': prior_meta.get('label', label),
                        'base64_data': base64_data
                    }
                    self.stats['reused'] += 1
                    self.delta_plan['reused'].append(concept_id)
                    return

        token_hash, geometry_hash, base64_compact, data = validate_token(file_path)

        if data.get('concept_id') != concept_id:
            raise ValueError("Concept ID mismatch between metadata and token content")

        self.geometries[geometry_hash] = base64_compact
        self.concepts[concept_id] = {
            'version': version,
            'source_hash': source_hash,
            'token_hash': token_hash,
            'geometry_hash': geometry_hash,
            'label': label,
            'base64_data': base64_compact
        }

        self.stats['added'] += 1
        self.delta_plan['added'].append(concept_id)

    def build_pack(self, out_dir: str, decoder_evidence_provided: bool = False):
        for prior_cid in self.prior_pack_index:
            if prior_cid not in self.concepts:
                self.stats['deleted'] += 1
                self.delta_plan['deleted'].append(prior_cid)

        pack_data = {
            'format_version': '1.0',
            'geometries': dict(sorted(self.geometries.items())),
            'concepts': {
                cid: {
                    'token_hash': data['token_hash'],
                    'geometry_hash': data['geometry_hash'],
                    'label': data['label']
                }
                for cid, data in sorted(self.concepts.items())
            }
        }

        pack_json = compact_json(pack_data)
        pack_bytes = pack_json.encode('utf-8')
        pack_sha256 = compute_sha256(pack_bytes)
        pack_size = len(pack_bytes)

        temp_dir = tempfile.mkdtemp(dir=os.path.dirname(out_dir) or '.')
        try:
            with open(os.path.join(temp_dir, 'pack.json'), 'wb') as f:
                f.write(pack_bytes)

            metadata = {
                'sha256': pack_sha256,
                'size_bytes': pack_size,
                'concept_count': len(self.concepts),
                'geometry_count': len(self.geometries),
                'production_ready': decoder_evidence_provided
            }
            with open(os.path.join(temp_dir, 'metadata.json'), 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

            with open(os.path.join(temp_dir, 'delta_plan.json'), 'w', encoding='utf-8') as f:
                json.dump(self.delta_plan, f, indent=2)

            wordbit_manifest = {
                'decoder_compatible': decoder_evidence_provided,
                'max_token_size': MAX_TOKEN_SIZE,
                'max_paths': MAX_PATHS
            }
            with open(os.path.join(temp_dir, 'wordbit_compatibility.json'), 'w', encoding='utf-8') as f:
                json.dump(wordbit_manifest, f, indent=2)

            j087_events = {
                'unchanged': self.delta_plan['reused'],
                'updated': self.delta_plan['added'],
                'deleted': self.delta_plan['deleted'],
                'invalid': []
            }
            with open(os.path.join(temp_dir, 'j087_events.json'), 'w', encoding='utf-8') as f:
                json.dump(j087_events, f, indent=2)

            # Atomic swap
            backup_dir = None
            if os.path.exists(out_dir):
                backup_dir = out_dir + ".bak"
                os.rename(out_dir, backup_dir)

            try:
                os.replace(temp_dir, out_dir)
                if backup_dir:
                    shutil.rmtree(backup_dir)
            except Exception as swap_err:
                if backup_dir:
                    os.rename(backup_dir, out_dir)
                raise swap_err

        except Exception as e:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise e
