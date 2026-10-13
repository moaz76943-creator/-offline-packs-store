import sqlite3

def normalize_text(text):
    if not isinstance(text, str):
        return text
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

db = sqlite3.connect(':memory:')
db.execute("CREATE VIRTUAL TABLE fts USING fts5(x, tokenize='unicode61 remove_diacritics 2')")

db.create_function("normalize_text", 1, normalize_text)
# if we just insert the original text:
db.execute("INSERT INTO fts(x) VALUES ('كِتاب')")
# and search with the original text normalized:
print(list(db.execute("SELECT * FROM fts WHERE fts MATCH ?", (normalize_text("كتاب"),))))
