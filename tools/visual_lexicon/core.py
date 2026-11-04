import json
import zlib
import hashlib

MAX_TOKEN_SIZE = 2048
MAX_PATHS = 50
MAX_COORDS_PER_PATH = 500

def validate_token_data(token_data: dict):
    if not isinstance(token_data, dict):
        raise ValueError("Token data must be a dictionary.")

    required_keys = {"version", "viewBox", "paths", "palette", "semantic_label"}
    missing_keys = required_keys - set(token_data.keys())
    if missing_keys:
        raise ValueError(f"Missing required fields. Missing: {missing_keys}")

    if not isinstance(token_data["version"], int) or token_data["version"] < 1:
        raise ValueError("Invalid version.")

    if not isinstance(token_data["viewBox"], (list, tuple)) or len(token_data["viewBox"]) != 4:
        raise ValueError("viewBox must be an array of 4 numbers.")

    if not isinstance(token_data["paths"], list):
        raise ValueError("paths must be a list.")

    if len(token_data["paths"]) > MAX_PATHS:
        raise ValueError(f"Exceeded maximum path count of {MAX_PATHS}.")

    for path in token_data["paths"]:
        if not isinstance(path, str):
            raise ValueError("each path must be a string.")
        # Simple complexity bound check by length or splitting
        if len(path.split()) > MAX_COORDS_PER_PATH:
            raise ValueError("Exceeded maximum coordinates per path.")

    if not isinstance(token_data["palette"], list):
        raise ValueError("palette must be a list of colors.")

    if not isinstance(token_data["semantic_label"], str) or not token_data["semantic_label"]:
        raise ValueError("semantic_label must be a non-empty string.")

def encode_token(token_data: dict) -> bytes:
    validate_token_data(token_data)
    json_bytes = json.dumps(token_data, separators=(',', ':')).encode('utf-8')
    compressed = zlib.compress(json_bytes)

    if len(compressed) >= MAX_TOKEN_SIZE:
        raise ValueError(f"Oversized token. Size: {len(compressed)} bytes (limit: {MAX_TOKEN_SIZE}).")

    return compressed

def decode_token(data: bytes) -> dict:
    if len(data) >= MAX_TOKEN_SIZE:
        raise ValueError(f"Oversized token. Size: {len(data)} bytes (limit: {MAX_TOKEN_SIZE}).")
    try:
        json_bytes = zlib.decompress(data)
    except zlib.error as e:
        raise ValueError(f"Invalid compressed data: {e}")

    try:
        token_data = json.loads(json_bytes.decode('utf-8'))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON payload: {e}")

    validate_token_data(token_data)
    return token_data

def get_content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
