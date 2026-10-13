"""Disk-backed exact-membership sets for bounded-memory lexical validation."""
import json
import sqlite3
import tempfile
from pathlib import Path


class DiskIndex:
    def __init__(self):
        self._temp = tempfile.TemporaryDirectory(prefix="lexicon-sanitizer-")
        self.db = sqlite3.connect(str(Path(self._temp.name) / "identity.sqlite3"))
        self.db.execute("PRAGMA cache_size=-4096")
        self.db.execute("CREATE TABLE identities (category TEXT NOT NULL, identity TEXT NOT NULL, PRIMARY KEY(category, identity))")

    def set(self, category):
        return DiskSet(self.db, category)

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
            self._temp.cleanup()


class DiskSet:
    def __init__(self, db, category):
        self.db = db
        self.category = category

    def _key(self, value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    def __contains__(self, value):
        return self.db.execute("SELECT 1 FROM identities WHERE category=? AND identity=?",
                               (self.category, self._key(value))).fetchone() is not None

    def add(self, value):
        self.db.execute("INSERT OR IGNORE INTO identities(category,identity) VALUES(?,?)",
                        (self.category, self._key(value)))
