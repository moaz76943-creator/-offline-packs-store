import sqlite3

db = sqlite3.connect(':memory:')
db.execute("CREATE VIRTUAL TABLE fts USING fts5(x, tokenize='unicode61 remove_diacritics 2')")
db.execute("INSERT INTO fts(x) VALUES ('كِتاب')")
res = db.execute("SELECT * FROM fts WHERE fts MATCH 'كتاب'").fetchall()
print("Matches for كتاب with remove_diacritics 2:", res)
