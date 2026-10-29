import re

with open('standards/lexical/sqlite_v2.py', 'r') as f:
    content = f.read()

# Replace the lexicon loop
lexicon_loop = """        for rid in sorted(lexemes, key=lambda key: (lexemes[key]['language'], sort_key(lexemes[key]['surface']), key)):
            row = lexemes[rid]
            levels = [level['level_id'] for sense in senses.values() if sense['lexeme_id'] == rid
                      for level in sense.get('levels', []) if level['framework_id'] == 'cefr']
            cefr = levels[0] if len(set(levels)) == 1 and levels else None
            rank = None  # Ordinal rank is NOT inferred from frequency scores.
            direction = row['direction']  # Explicitly attested; never guess script layout.
            conn.execute('''INSERT INTO lexicon
                (id,surface,part_of_speech,pos,direction,language_code,script,dialect,
                 sort_key,cefr_level,frequency_rank,fields_json,source_json)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (rid,row['surface'],row['pos'],row['pos'],direction,row['language'],row['script'],
                 row.get('dialect'),sort_key(row['surface']),cefr,rank,compact(row),compact(row['source'])))
            rowid = conn.execute('SELECT rowid FROM lexicon WHERE id=?',(rid,)).fetchone()[0]
            gloss = ' '.join(sorted(set(definitions.get(rid, []) + outbound.get(rid, []))))
            conn.execute('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES (?,?,?,?,?)',
                         (rowid,row['surface'],row['lemma'],gloss,row['language']))"""

lexicon_new = """        lexicon_params = []
        for rid in sorted(lexemes, key=lambda key: (lexemes[key]['language'], sort_key(lexemes[key]['surface']), key)):
            row = lexemes[rid]
            levels = [level['level_id'] for sense in senses.values() if sense['lexeme_id'] == rid
                      for level in sense.get('levels', []) if level['framework_id'] == 'cefr']
            cefr = levels[0] if len(set(levels)) == 1 and levels else None
            rank = None  # Ordinal rank is NOT inferred from frequency scores.
            direction = row['direction']  # Explicitly attested; never guess script layout.
            lexicon_params.append((rid,row['surface'],row['pos'],row['pos'],direction,row['language'],row['script'],
                 row.get('dialect'),sort_key(row['surface']),cefr,rank,compact(row),compact(row['source'])))

        conn.executemany('''INSERT INTO lexicon
            (id,surface,part_of_speech,pos,direction,language_code,script,dialect,
             sort_key,cefr_level,frequency_rank,fields_json,source_json)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', lexicon_params)

        rowids = dict(conn.execute('SELECT id, rowid FROM lexicon').fetchall())

        fts_params = []
        for rid in sorted(lexemes, key=lambda key: (lexemes[key]['language'], sort_key(lexemes[key]['surface']), key)):
            row = lexemes[rid]
            rowid = rowids[rid]
            gloss = ' '.join(sorted(set(definitions.get(rid, []) + outbound.get(rid, []))))
            fts_params.append((rowid,row['surface'],row['lemma'],gloss,row['language']))

        conn.executemany('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES (?,?,?,?,?)',
                         fts_params)"""

content = content.replace(lexicon_loop, lexicon_new)

with open('standards/lexical/sqlite_v2.py', 'w') as f:
    f.write(content)
