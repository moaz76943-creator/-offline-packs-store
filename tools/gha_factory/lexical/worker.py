#!/usr/bin/env python3
"""Approved immutable Wiktextract -> bounded, resumable Route 06 / SQLite v2 QA.

Never downloads corpora, invents translations or publishes production packs.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

MAX_LINE_BYTES = 1024 * 1024
MAX_JOB_LINES = 100000
BATCH_SIZE = 256
_ID = re.compile(r'^[a-z][a-z0-9._:-]{2,127}$')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(65536), b''):
            h.update(part)
    return h.hexdigest()


def json_no_duplicates(raw):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError('repeated JSON property')
            obj[key] = value
        return obj
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite number')))


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f'missing approved module: {path.name}')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def registry(root, language):
    path = root / 'catalog/language_registry.v1.json'
    document = json_no_duplicates(path.read_bytes())
    languages = document['languages']
    if len(languages) != 100 or len({row['id'] for row in languages}) != 100:
        raise ValueError('canonical 100-language registry invalid')
    found = next((row for row in languages if row['id'] == language), None)
    if not found:
        raise ValueError('unregistered language identity')
    script = found['default_script']
    if script not in found['scripts'] or script not in document['scripts']:
        raise ValueError('unregistered script')
    return found, document['scripts'], digest_file(path)


def approved_source(root, source_id):
    """Use GHA-01, Route 05 and Route 08 approval and original SHA-256 checks."""
    if not _ID.fullmatch(source_id):
        raise ValueError('invalid source ID')
    ledger = json_no_duplicates((root / 'legal/ledger/sources.json').read_bytes())
    if ledger.get('schema_version') != '1.0.0':
        raise ValueError('unsupported legal ledger')
    sources = [s for s in ledger.get('sources', []) if s.get('source_id') == source_id]
    if len(sources) != 1:
        raise ValueError('BLOCKED_SOURCE: no uniquely approved source')
    source = sources[0]
    if not isinstance(source.get('alterations'), list) or not source['alterations']:
        raise ValueError('BLOCKED_SOURCE: alteration history required')
    retrieval = source.get('retrieval') or {}
    relative = retrieval.get('artifact_path')
    if not isinstance(relative, str):
        raise ValueError('BLOCKED_SOURCE: missing reviewed artifact')
    original = Path(relative)
    input_path = (root / original).resolve()
    if original.is_absolute() or '..' in original.parts or not input_path.is_relative_to(root.resolve()):
        raise ValueError('BLOCKED_SOURCE: forbidden source path')
    importer = module(root / 'tools/sources/pilot5/pipeline.py', 'approved_pilot5_importer')
    importer.verify_source(ledger, source_id, input_path, root)
    admission = module(root / 'tools/gha_factory/admission/pipeline.py', 'route01_source_admission')
    admission.route05_source(root, source_id, source['dataset_version'],
                             input_path, 'wiktextract-jsonl')
    return source, input_path, importer


def partition_of(lexeme_id, count):
    return int(hashlib.sha256(lexeme_id.encode('utf-8')).hexdigest()[:16], 16) % count


@contextmanager
def exclusive_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('partition is already owned by another worker') from exc
        yield


def init_db(path, fingerprint):
    db = sqlite3.connect(path)
    db.execute('PRAGMA cache_size=-2048')
    db.execute('PRAGMA temp_store=FILE')
    db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS lexemes(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS senses(id TEXT PRIMARY KEY,lexeme_id TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS senses_by_lexeme ON senses(lexeme_id,id);
        CREATE TABLE IF NOT EXISTS evidence(locator TEXT PRIMARY KEY,line_sha256 TEXT NOT NULL,
            lexeme_id TEXT NOT NULL,source_id TEXT NOT NULL);
    """)
    saved = db.execute("SELECT v FROM meta WHERE k='fingerprint'").fetchone()
    if saved and saved[0] != fingerprint:
        db.close()
        raise ValueError('checkpoint identity mismatch; refusing cross-source resume')
    if not saved:
        state = {'offset': 0, 'next_line': 1, 'input_rows': 0, 'owned_rows': 0,
                 'accepted_lexemes': 0, 'accepted_senses': 0,
                 'rejected': 0, 'duplicates': 0, 'unrouted_malformed': 0}
        db.executemany('INSERT INTO meta VALUES (?,?)',
                       [('fingerprint', fingerprint), ('state', canonical(state))])
        db.commit()
    return db


def _row_identity(row, lang, importer):
    if not isinstance(row, dict) or row.get('lang_code') != lang:
        return None
    word, etym = row.get('word'), row.get('etymology_number')
    pos = importer.POS.get(row.get('pos')) if isinstance(row.get('pos'), str) else None
    if not isinstance(word, str) or not word.strip() or not pos or (etym is not None and
         (not isinstance(etym, int) or isinstance(etym, bool))):
        return None
    word = importer.normalize(word)
    if lang == 'en' and pos == 'verb' and ' ' in word.strip():
        pos = 'multiword'
    return importer.stable('lex', lang, word, pos, etym)


def _extract(row, lang, entry, scripts, importer, source, locator):
    selected_script = row.get('script', entry['default_script'])
    if selected_script not in entry['scripts'] or selected_script not in scripts:
        return None
    importer.LANGS[lang] = selected_script
    parsed = importer.extract(row, lang, source, locator)
    if parsed is None:
        return None
    lexeme, senses = parsed
    lexeme['script'] = selected_script
    direction = scripts[selected_script]['direction']
    lexeme['direction'] = 'ttb' if direction.startswith('ttb') else direction
    if lexeme['direction'] not in ('ltr', 'rtl', 'ttb'):
        return None
    if not senses or len(senses) > 128:
        return None
    for group in ('articles', 'classifiers', 'inflections', 'conjugations', 'irregular_forms'):
        for form in lexeme.get('morphology', {}).get(group, []):
            form['source'] = lexeme['source']
    return lexeme, senses


def merge_attested(previous, incoming):
    """Union source-attested morphology and IPA only, preserving their row evidence."""
    changed = False
    for field in ('gender', 'noun_class', 'number'):
        old = previous.get('morphology', {}).get(field)
        new = incoming.get('morphology', {}).get(field)
        if old is not None and new is not None and old != new:
            raise ValueError('conflicting attested morphological feature')
    if incoming.get('morphology'):
        old = previous.setdefault('morphology', {})
        for key, value in incoming['morphology'].items():
            if key not in old:
                old[key] = value
                changed = True
            elif isinstance(value, list):
                for form in value:
                    signature = {k:v for k,v in form.items() if k != 'source'} if isinstance(form,dict) else form
                    if not any(({k:v for k,v in p.items() if k != 'source'} if isinstance(p,dict) else p) == signature for p in old[key]):
                        old[key].append(form)
                        changed = True
    old_audio = previous.setdefault('pronunciations', [])
    for sample in incoming.get('pronunciations', []):
        if not any((p['notation'],p['value'],p.get('dialect')) ==
                   (sample['notation'],sample['value'],sample.get('dialect')) for p in old_audio):
            old_audio.append(sample)
            changed = True
    return changed


def _validate_records(lexeme, senses, validators):
    lex_validator, sense_validator = validators
    if not lex_validator.is_valid(lexeme):
        return False
    if any(not sense_validator.is_valid(s) or s['lexeme_id'] != lexeme['lexeme_id'] for s in senses):
        return False
    return (len(canonical(lexeme).encode('utf-8')) <= 65536 and
            all(len(canonical(s).encode('utf-8')) <= 65536 for s in senses))


def validators_from(root):
    from jsonschema import Draft202012Validator
    schema = json_no_duplicates((root / 'standards/lexical/lexical.schema.json').read_bytes())
    Draft202012Validator.check_schema(schema)
    return tuple(Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/' + name})
                 for name in ('lexeme', 'sense'))


def _ingest(db, inp, lang, index, partitions, max_lines, importer, source, entry, scripts, validators):
    state = json.loads(db.execute("SELECT v FROM meta WHERE k='state'").fetchone()[0])
    with inp.open('rb') as stream:
        stream.seek(state['offset'])
        for _ in range(max_lines):
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if not raw:
                return state, True
            oversized = len(raw) > MAX_LINE_BYTES
            if oversized and not raw.endswith(b'\n'):
                while True:
                    tail = stream.readline(65536)
                    if not tail or tail.endswith(b'\n'):
                        break
            locator = f"line:{state['next_line']}"
            state['input_rows'] += 1
            state['next_line'] += 1
            state['offset'] = stream.tell()
            try:
                row = None if oversized else json_no_duplicates(raw)
                lex_id = _row_identity(row, lang, importer)
            except (ValueError, TypeError, UnicodeError):
                lex_id = None
            if lex_id is None:
                state['unrouted_malformed'] += 1
            elif partition_of(lex_id, partitions) == index:
                state['owned_rows'] += 1
                try:
                    parsed = _extract(row, lang, entry, scripts, importer, source, locator)
                    valid = parsed is not None and _validate_records(*parsed, validators)
                except (ValueError, TypeError, UnicodeError, KeyError):
                    valid = False
                if not valid:
                    state['rejected'] += 1
                else:
                    lexeme, senses = parsed
                    before = (state['accepted_lexemes'], state['accepted_senses'],
                              state['duplicates'])
                    db.execute('SAVEPOINT lexical_record')
                    try:
                        found = db.execute('SELECT payload FROM lexemes WHERE id=?', (lex_id,)).fetchone()
                        if found:
                            earlier = json.loads(found[0])
                            if any(earlier[k] != lexeme[k] for k in ('lemma', 'pos', 'script', 'direction')):
                                raise ValueError('stable lexeme identity collision')
                            modified = merge_attested(earlier, lexeme)
                            if modified:
                                if not validators[0].is_valid(earlier):
                                    raise ValueError('merged attestation failed lexical schema')
                                db.execute('UPDATE lexemes SET payload=? WHERE id=?',
                                           (canonical(earlier),lex_id))
                        else:
                            db.execute('INSERT INTO lexemes VALUES (?,?)', (lex_id, canonical(lexeme)))
                            state['accepted_lexemes'] += 1
                            modified = True
                        added = 0
                        for sense in senses:
                            existing = db.execute('SELECT payload FROM senses WHERE id=?', (sense['sense_id'],)).fetchone()
                            if existing:
                                if json.loads(existing[0])['definition'] != sense['definition']:
                                    raise ValueError('stable sense identity collision')
                            else:
                                db.execute('INSERT INTO senses VALUES (?,?,?)',
                                           (sense['sense_id'], lex_id, canonical(sense)))
                                added += 1
                        if not added and not modified:
                            state['duplicates'] += 1
                        else:
                            state['accepted_senses'] += added
                            db.execute('INSERT INTO evidence VALUES (?,?,?,?)',
                                       (locator, hashlib.sha256(raw).hexdigest(),lex_id,source['source_id']))
                    except (ValueError, TypeError, KeyError, sqlite3.IntegrityError):
                        db.execute('ROLLBACK TO SAVEPOINT lexical_record')
                        db.execute('RELEASE SAVEPOINT lexical_record')
                        state['accepted_lexemes'], state['accepted_senses'], state['duplicates'] = before
                        state['rejected'] += 1
                    else:
                        db.execute('RELEASE SAVEPOINT lexical_record')
            db.execute("UPDATE meta SET v=? WHERE k='state'", (canonical(state),))
            if state['input_rows'] % 200 == 0:
                db.commit()
    db.commit()
    return state, False


def _export(db, out, lang, source, source_sha, index, partitions, state, root):
    """Bounded independently validated lexical documents and SQLite v2 QA slices."""
    import shutil
    tmp = out / 'export-staging'
    done = out / 'verified-batches'
    if tmp.exists() or done.exists():
        raise ValueError('immutable export path already exists')
    tmp.mkdir()
    mapping_dir = root / 'standards/lexical'
    sys.path.insert(0, str(mapping_dir))
    lex_contract = module(mapping_dir / 'validate.py', 'lex_contract_for_factory')
    sqlite_v2 = module(mapping_dir / 'sqlite_v2.py', 'sqlite_v2_for_factory')
    batches = []
    try:
        cursor = db.execute('SELECT id,payload FROM lexemes ORDER BY id')
        n = 0
        while True:
            group = cursor.fetchmany(BATCH_SIZE)
            if not group:
                break
            lexemes = [json.loads(row[1]) for row in group]
            senses = []
            for lid, _ in group:
                senses.extend(json.loads(x[0]) for x in db.execute(
                    'SELECT payload FROM senses WHERE lexeme_id=? ORDER BY id',(lid,)))
            doc = {'contract_version':'1.0.0',
                   'document_id': f'factory.{lang}.{source_sha[:16]}.p{index:04d}of{partitions:04d}.b{n:06d}',
                   'lexemes':lexemes,'senses':senses,'translations':[], 'examples':[], 'relations':[]}
            lex_contract.validate(doc, publication=True)
            lexical = tmp / f'batch-{n:06d}.json'
            lexical.write_text(canonical(doc)+'\n', encoding='utf-8')
            sqlite_file = tmp / f'batch-{n:06d}.sqlite'
            sqlite_v2.build(doc, sqlite_file, publication=True)
            batches.append({'file': lexical.name, 'sha256':digest_file(lexical),
                            'sqlite':sqlite_file.name,'sqlite_sha256':digest_file(sqlite_file),
                            'lexemes':len(lexemes),'senses':len(senses)})
            n += 1
        evidence = tmp / 'evidence.jsonl'
        with evidence.open('w', encoding='utf-8', newline='\n') as target:
            for locator,sha,lexid,sid in db.execute(
                'SELECT locator,line_sha256,lexeme_id,source_id FROM evidence ORDER BY CAST(SUBSTR(locator,6) AS INTEGER)'):
                target.write(canonical({'record_locator':locator,'raw_line_sha256':sha,
                                        'lexeme_id':lexid,'source_id':sid})+'\n')
        receipt = {'status':'VERIFIED_BATCHES_NOT_PRODUCTION_PACKS','source_id':source['source_id'],
                   'source_sha256':source_sha,'license_id':source['license']['id'],
                   'dataset_version':source['dataset_version'],'language':lang,
                   'partition_index':index,'partition_count':partitions,
                   'partition_id':hashlib.sha256(f'{source_sha}:{lang}:{index}/{partitions}'.encode()).hexdigest(),
                   'counts':state,'batches':batches,'evidence_sha256':digest_file(evidence),
                   'sqlite_mapping':'2.0.0','production_ready':False,
                   'translation_edges':0,'cefr_assignments':0}
        (tmp/'qa_receipt.json').write_text(canonical(receipt)+'\n',encoding='utf-8')
        tmp.rename(done)
        return receipt
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def execute(root, source_id, language, output, partition_index=0, partition_count=1,
            max_lines=20000):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not (1 <= partition_count <= 1024 and 0 <= partition_index < partition_count):
        raise ValueError('invalid partition claim')
    if not 1 <= max_lines <= MAX_JOB_LINES:
        raise ValueError('job input-row cap invalid')
    entry, scripts, registry_sha = registry(root, language)
    source, inp, importer = approved_source(root, source_id)
    source_sha = source['retrieval']['sha256']
    if digest_file(inp) != source_sha:
        raise ValueError('BLOCKED_SOURCE: snapshot changed during admission')
    validators = validators_from(root)
    if output.is_relative_to(root):
        raise ValueError('output must be outside immutable public repository')
    output.mkdir(parents=True, exist_ok=True)
    identity = canonical({'source_id':source_id,'sha256':source_sha,'language':language,
                          'registry_sha256':registry_sha,'partition_index':partition_index,
                          'partition_count':partition_count,'schema':'1.0.0'})
    with exclusive_lock(output/'.worker.lock'):
        db = init_db(output/'checkpoint.sqlite',identity)
        try:
            if (output/'verified-batches').exists():
                return json.loads((output/'verified-batches/qa_receipt.json').read_text(encoding='utf-8'))
            state, eof = _ingest(db, inp, language, partition_index, partition_count,
                                  max_lines, importer, source, entry, scripts, validators)
            db.commit()
            if digest_file(inp) != source_sha:
                raise ValueError('BLOCKED_SOURCE: immutable source changed during processing')
            if not eof:
                return {'status':'PARTIAL_CHECKPOINT','source_id':source_id,
                        'language':language,'counts':state,'production_ready':False}
            if state['accepted_lexemes'] == 0:
                return {'status':'NO_ACCEPTED_RECORDS','language':language,
                        'counts':state,'production_ready':False}
            return _export(db,output,language,source,source_sha,partition_index,
                           partition_count,state,root)
        finally:
            db.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root', type=Path, default=Path.cwd())
    p.add_argument('--source-id', required=True)
    p.add_argument('--language', required=True)
    p.add_argument('--partition-index', type=int, required=True)
    p.add_argument('--partition-count', type=int, required=True)
    p.add_argument('--max-lines', type=int, default=20000)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    try:
        receipt = execute(args.repo_root,args.source_id,args.language,args.out,
                          args.partition_index,args.partition_count,args.max_lines)
        print(canonical(receipt))
        return 0 if receipt['status'] != 'NO_ACCEPTED_RECORDS' else 3
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error, ImportError) as error:
        print(canonical({'status':'BLOCKED_SOURCE_OR_DEPENDENCY','accepted':0,
                         'error':str(error)}),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
