-- SQLite v2 Directed-Pair Translation Metadata Schema
-- PRAGMA user_version=2;

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

INSERT INTO metadata (key, value) VALUES
    ('schema_version', '1.0.0'),
    ('standard', 'directed_pairs');

CREATE TABLE senses (
    sense_id TEXT PRIMARY KEY,
    language TEXT NOT NULL
) STRICT;

CREATE TABLE directed_translations (
    translation_id TEXT PRIMARY KEY,
    source_sense_id TEXT NOT NULL REFERENCES senses(sense_id) DEFERRABLE INITIALLY DEFERRED,
    target_sense_id TEXT NOT NULL REFERENCES senses(sense_id) DEFERRABLE INITIALLY DEFERRED,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    text TEXT NOT NULL,
    equivalence TEXT NOT NULL CHECK(equivalence IN ('exact', 'approximate', 'contextual')),
    context TEXT,
    domain TEXT,
    examples_json TEXT, -- JSON array of examples
    provenance_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    confidence REAL CHECK(confidence >= 0.0 AND confidence <= 1.0)
) STRICT;

CREATE INDEX idx_directed_translations_source ON directed_translations(source_sense_id);
CREATE INDEX idx_directed_translations_target ON directed_translations(target_sense_id);
CREATE INDEX idx_directed_translations_langs ON directed_translations(source_language, target_language);

-- Ensure we don't assume reverse translation implicitly
CREATE TRIGGER check_reverse_translation
BEFORE INSERT ON directed_translations
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM directed_translations
    WHERE source_sense_id = NEW.target_sense_id
      AND target_sense_id = NEW.source_sense_id
      AND NEW.equivalence = 'exact'
)
BEGIN
    -- No hard block since reverse pairs CAN be independently attested.
    -- But this trigger demonstrates explicit awareness.
    -- If needed, we could add a warning or specialized logic here.
    SELECT 1;
END;
