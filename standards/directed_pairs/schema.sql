-- SQLite v2 Schema snippet for Directed Pairs

CREATE TABLE directed_pair_senses(
    sense_id TEXT PRIMARY KEY,
    language_code TEXT NOT NULL,
    definition TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE directed_pairs(
    pair_id TEXT PRIMARY KEY,
    from_sense_id TEXT NOT NULL REFERENCES directed_pair_senses(sense_id),
    to_sense_id TEXT NOT NULL REFERENCES directed_pair_senses(sense_id),
    from_language_code TEXT NOT NULL,
    to_language_code TEXT NOT NULL,
    translation_text TEXT NOT NULL,
    equivalence TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX idx_directed_pairs_from ON directed_pairs(from_sense_id);
CREATE INDEX idx_directed_pairs_to ON directed_pairs(to_sense_id);
CREATE INDEX idx_directed_pairs_langs ON directed_pairs(from_language_code, to_language_code);
