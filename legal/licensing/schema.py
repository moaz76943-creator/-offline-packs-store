import json

LEDGER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/moaz76943-creator/-offline-packs-store/blob/main/legal/licensing/schema.py",
    "title": "Open Lexical Source Licensing Ledger",
    "description": "Schema for source-specific licensing records.",
    "type": "object",
    "required": ["source_id", "url", "author", "version", "license"],
    "properties": {
        "source_id": {"type": "string", "minLength": 1},
        "url": {"type": "string", "format": "uri"},
        "author": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "license": {
            "type": "object",
            "required": ["declared_id", "evidence_url"],
            "properties": {
                "declared_id": {
                    "enum": ["CC-BY-SA-4.0", "GFDL-1.3-only", "CC0-1.0", "PUBLIC-DOMAIN"]
                },
                "evidence_url": {"type": "string", "format": "uri"}
            }
        },
        "modification_status": {
            "type": "string",
            "enum": ["unmodified", "modified"]
        },
        "hash": {"type": "string", "minLength": 1}
    }
}
