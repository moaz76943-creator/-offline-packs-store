import re

with open('standards/lexical/sqlite_v2.py', 'r') as f:
    content = f.read()

# Make it completely bulk with list comprehensions instead of generators for inner loop

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
                         (rowid,row['surface'],row['lemma'],gloss,row['language']))
        for sid in sorted(senses):
            row = senses[sid]
            conn.execute('INSERT INTO senses VALUES (?,?,?,?,?)',
                         (sid,row['lexeme_id'],row['concept_id'],row['definition'],compact(row)))
        for row in sorted(document['translations'], key=lambda r:r['translation_id']):
            conn.execute('INSERT INTO translations VALUES (?,?,?,?,?,?)',
                         (row['translation_id'],row['from_sense_id'],row['to_sense_id'],
                          row['language'],row['text'],compact(row)))
        for row in sorted(document['examples'],key=lambda r:r['example_id']):
            conn.execute('INSERT INTO examples VALUES (?,?,?,?,?,?)',
                         (row['example_id'],row['sense_id'],senses[row['sense_id']]['lexeme_id'],
                          row['language'],row['text'],compact(row)))
        for row in sorted(document['relations'],key=lambda r:r['relation_id']):
            conn.execute('INSERT INTO lexical_relations VALUES (?,?,?,?,?)',
                         (row['relation_id'],row['from_lexeme_id'],row['to_lexeme_id'],
                          row['kind'],compact(row)))"""

lexicon_new = """        lexicon_params = []
        fts_params = []
        rowid = 1

        # Pre-compute levels and glosses to avoid redundant work in the loop
        lexeme_levels = {}
        for sense in senses.values():
            lid = sense['lexeme_id']
            for level in sense.get('levels', []):
                if level['framework_id'] == 'cefr':
                    lexeme_levels.setdefault(lid, []).append(level['level_id'])

        for rid in sorted(lexemes, key=lambda key: (lexemes[key]['language'], sort_key(lexemes[key]['surface']), key)):
            row = lexemes[rid]
            levels = lexeme_levels.get(rid, [])
            cefr = levels[0] if len(set(levels)) == 1 and levels else None
            rank = None  # Ordinal rank is NOT inferred from frequency scores.
            direction = row['direction']  # Explicitly attested; never guess script layout.
            lexicon_params.append((rid,row['surface'],row['pos'],row['pos'],direction,row['language'],row['script'],
                 row.get('dialect'),sort_key(row['surface']),cefr,rank,compact(row),compact(row['source'])))

            gloss = ' '.join(sorted(set(definitions.get(rid, []) + outbound.get(rid, []))))
            fts_params.append((rowid,row['surface'],row['lemma'],gloss,row['language']))
            rowid += 1

        conn.executemany('''INSERT INTO lexicon
            (id,surface,part_of_speech,pos,direction,language_code,script,dialect,
             sort_key,cefr_level,frequency_rank,fields_json,source_json)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', lexicon_params)

        conn.executemany('INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) VALUES (?,?,?,?,?)',
                         fts_params)

        conn.executemany('INSERT INTO senses VALUES (?,?,?,?,?)',
                         [(sid,senses[sid]['lexeme_id'],senses[sid]['concept_id'],
                           senses[sid]['definition'],compact(senses[sid]))
                          for sid in sorted(senses)])
        conn.executemany('INSERT INTO translations VALUES (?,?,?,?,?,?)',
                         [(row['translation_id'],row['from_sense_id'],row['to_sense_id'],
                           row['language'],row['text'],compact(row))
                          for row in sorted(document['translations'], key=lambda r:r['translation_id'])])
        conn.executemany('INSERT INTO examples VALUES (?,?,?,?,?,?)',
                         [(row['example_id'],row['sense_id'],senses[row['sense_id']]['lexeme_id'],
                           row['language'],row['text'],compact(row))
                          for row in sorted(document['examples'],key=lambda r:r['example_id'])])
        conn.executemany('INSERT INTO lexical_relations VALUES (?,?,?,?,?)',
                         [(row['relation_id'],row['from_lexeme_id'],row['to_lexeme_id'],
                           row['kind'],compact(row))
                          for row in sorted(document['relations'],key=lambda r:r['relation_id'])])"""

content = content.replace(lexicon_loop, lexicon_new)

with open('standards/lexical/sqlite_v2.py', 'w') as f:
    f.write(content)
