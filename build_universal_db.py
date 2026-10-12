import sqlite3
import os
import hashlib
import gzip
import json

db_path = 'universal.db'
if os.path.exists(db_path):
    os.remove(db_path)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# Create table according to what might be expected, let's look at compile_store_packs.py DDL
# or maybe we should just create a simple table and dump the contents of the packs into it.
c.execute('''
CREATE TABLE IF NOT EXISTS packs (
    language_code TEXT PRIMARY KEY,
    pack_data TEXT
)
''')

packs_dir = 'packs'
if os.path.exists(packs_dir):
    for filename in sorted(os.listdir(packs_dir)):
        if filename.endswith('.pack.gz'):
            lang_code = filename.split('_')[0]
            with gzip.open(os.path.join(packs_dir, filename), 'rt', encoding='utf-8') as f:
                data = f.read()
                c.execute('INSERT OR REPLACE INTO packs (language_code, pack_data) VALUES (?, ?)', (lang_code, data))

conn.commit()
conn.close()

with open(db_path, 'rb') as f:
    h = hashlib.sha256(f.read()).hexdigest()

with open('latest_universal_db_hash.txt', 'w') as f:
    f.write(h)

print("Created universal.db and latest_universal_db_hash.txt")
