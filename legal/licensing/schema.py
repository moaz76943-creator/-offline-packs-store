import json

# JSON schema for a single source record in the licensing ledger.
# Required fields per source: source_id, url, author, version, license, modification_status
# Distinguishes license declarations from verified evidence.
LEDGER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Open Lexical Source Licensing Ledger",
    "type": "object",
    "required": ["source_id", "url", "author", "version", "license", "modification_status"],
    "properties": {
        "source_id": {
            "type": "string",
            "minLength": 1
        },
        "url": {
            "type": "string",
            "format": "uri"
        },
        "author": {
            "type": "string",
            "minLength": 1
        },
        "version": {
            "type": "string",
            "minLength": 1
        },
        "license": {
            "type": "object",
            "required": ["declared_id", "evidence_url", "evidence_hash"],
            "properties": {
                "declared_id": {
                    "type": "string",
                    "enum": ["CC-BY-SA-4.0", "GFDL-1.3-only", "CC0-1.0", "PUBLIC-DOMAIN", "CC-BY-2.0-FR"]
                },
                "evidence_url": {
                    "type": "string",
                    "format": "uri"
                },
                "evidence_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$"
                },
                "cc_by_sa_obligations": {
                    "type": "object",
                    "properties": {
                        "attribution": {"type": "boolean"},
                        "license_link": {"type": "boolean"},
                        "changes_disclosed": {"type": "boolean"},
                        "sharealike": {"type": "boolean"},
                        "no_additional_restrictions": {"type": "boolean"}
                    }
                },
                "gfdl_obligations": {
                    "type": "object",
                    "properties": {
                        "license_copy": {"type": "boolean"},
                        "copyright_notices": {"type": "boolean"},
                        "history": {"type": "boolean"}
                    }
                }
            },
            "additionalProperties": False
        },
        "modification_status": {
            "type": "string",
            "enum": ["UNMODIFIED", "MODIFIED"]
        }
    },
    "additionalProperties": False
}

def get_schema() -> dict:
    return LEDGER_SCHEMA
