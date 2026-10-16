CREATE TABLE IF NOT EXISTS directed_pair_translations (
    pair_id TEXT PRIMARY KEY,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    source_sense_id TEXT NOT NULL,
    target_sense_id TEXT NOT NULL,
    translation_text TEXT NOT NULL,
    context TEXT,
    domain TEXT,
    equivalence TEXT NOT NULL,
    provenance_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    confidence_evidence TEXT NOT NULL,
    CHECK (source_language != target_language),
    CHECK (source_sense_id != target_sense_id)
);

CREATE TABLE IF NOT EXISTS directed_pair_examples (
    pair_id TEXT NOT NULL,
    example_text TEXT NOT NULL,
    FOREIGN KEY(pair_id) REFERENCES directed_pair_translations(pair_id) ON DELETE CASCADE
);
