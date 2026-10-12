BEGIN TRANSACTION;

-- Create missing FTS tables if they do not exist
CREATE VIRTUAL TABLE IF NOT EXISTS verbs_fts USING fts5(verb_id UNINDEXED, infinitive, translation_ar, tokenize='trigram');
CREATE VIRTUAL TABLE IF NOT EXISTS idioms_fts USING fts5(idiom_id UNINDEXED, expression, translation_ar, explanation, tokenize='trigram');

-- Drop old triggers if they exist to recreate them
DROP TRIGGER IF EXISTS verbs_ai;
DROP TRIGGER IF EXISTS idioms_ai;

-- Create triggers for automatic synchronization
CREATE TRIGGER verbs_ai AFTER INSERT ON verbs BEGIN
  INSERT INTO verbs_fts(verb_id, infinitive, translation_ar) VALUES (new.verb_id, new.infinitive, new.translation_ar);
END;

CREATE TRIGGER idioms_ai AFTER INSERT ON idioms BEGIN
  INSERT INTO idioms_fts(idiom_id, expression, translation_ar, explanation) VALUES (new.idiom_id, new.expression, new.translation_ar, new.explanation);
END;

-- Populate existing records safely (INSERT OR IGNORE to prevent duplicates if already migrated)
INSERT OR IGNORE INTO verbs_fts(verb_id, infinitive, translation_ar)
SELECT verb_id, infinitive, translation_ar FROM verbs;

INSERT OR IGNORE INTO idioms_fts(idiom_id, expression, translation_ar, explanation)
SELECT idiom_id, expression, translation_ar, explanation FROM idioms;

-- Update user_version
PRAGMA user_version=3;

COMMIT;
