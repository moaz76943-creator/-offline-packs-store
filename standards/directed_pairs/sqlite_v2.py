"""SQLite v2 projection for directed pairs."""

def schema():
    return """
CREATE TABLE directed_translations (
    source_sense_id TEXT NOT NULL,
    target_sense_id TEXT NOT NULL,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    translation_text TEXT NOT NULL,
    equivalence TEXT NOT NULL,
    context TEXT,
    domain TEXT,
    examples TEXT,
    provenance_id TEXT NOT NULL,
    source_version TEXT,
    confidence REAL,
    PRIMARY KEY (source_sense_id, target_sense_id, provenance_id)
);
"""
