import re

with open('standards/lexical/sqlite_v2.py', 'r') as f:
    content = f.read()

# Replace the senses loop
senses_loop = """        for sid in sorted(senses):
            row = senses[sid]
            conn.execute('INSERT INTO senses VALUES (?,?,?,?,?)',
                         (sid,row['lexeme_id'],row['concept_id'],row['definition'],compact(row)))"""

senses_new = """        conn.executemany('INSERT INTO senses VALUES (?,?,?,?,?)',
                         ((sid,senses[sid]['lexeme_id'],senses[sid]['concept_id'],
                           senses[sid]['definition'],compact(senses[sid]))
                          for sid in sorted(senses)))"""

content = content.replace(senses_loop, senses_new)

# Replace the translations loop
trans_loop = """        for row in sorted(document['translations'], key=lambda r:r['translation_id']):
            conn.execute('INSERT INTO translations VALUES (?,?,?,?,?,?)',
                         (row['translation_id'],row['from_sense_id'],row['to_sense_id'],
                          row['language'],row['text'],compact(row)))"""

trans_new = """        conn.executemany('INSERT INTO translations VALUES (?,?,?,?,?,?)',
                         ((row['translation_id'],row['from_sense_id'],row['to_sense_id'],
                           row['language'],row['text'],compact(row))
                          for row in sorted(document['translations'], key=lambda r:r['translation_id'])))"""

content = content.replace(trans_loop, trans_new)

# Replace the examples loop
ex_loop = """        for row in sorted(document['examples'],key=lambda r:r['example_id']):
            conn.execute('INSERT INTO examples VALUES (?,?,?,?,?,?)',
                         (row['example_id'],row['sense_id'],senses[row['sense_id']]['lexeme_id'],
                          row['language'],row['text'],compact(row)))"""

ex_new = """        conn.executemany('INSERT INTO examples VALUES (?,?,?,?,?,?)',
                         ((row['example_id'],row['sense_id'],senses[row['sense_id']]['lexeme_id'],
                           row['language'],row['text'],compact(row))
                          for row in sorted(document['examples'],key=lambda r:r['example_id'])))"""

content = content.replace(ex_loop, ex_new)

# Replace the relations loop
rel_loop = """        for row in sorted(document['relations'],key=lambda r:r['relation_id']):
            conn.execute('INSERT INTO lexical_relations VALUES (?,?,?,?,?)',
                         (row['relation_id'],row['from_lexeme_id'],row['to_lexeme_id'],
                          row['kind'],compact(row)))"""

rel_new = """        conn.executemany('INSERT INTO lexical_relations VALUES (?,?,?,?,?)',
                         ((row['relation_id'],row['from_lexeme_id'],row['to_lexeme_id'],
                           row['kind'],compact(row))
                          for row in sorted(document['relations'],key=lambda r:r['relation_id'])))"""

content = content.replace(rel_loop, rel_new)


with open('standards/lexical/sqlite_v2.py', 'w') as f:
    f.write(content)
