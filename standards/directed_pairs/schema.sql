CREATE TABLE IF NOT EXISTS senses (
    id TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    definition TEXT NOT NULL,
    usage_context TEXT,
    domains_json TEXT
);

CREATE TABLE IF NOT EXISTS translations (
    id TEXT PRIMARY KEY,
    source_sense_id TEXT NOT NULL,
    target_sense_id TEXT NOT NULL,
    target_language TEXT NOT NULL,
    translation_text TEXT NOT NULL,
    equivalence TEXT NOT NULL,
    context TEXT,
    confidence REAL,
    examples_json TEXT,
    source_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    publisher TEXT NOT NULL,
    FOREIGN KEY(source_sense_id) REFERENCES senses(id),
    FOREIGN KEY(target_sense_id) REFERENCES senses(id)
);
