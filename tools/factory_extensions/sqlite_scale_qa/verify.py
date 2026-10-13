"""Independent, read-only QA adapter for the canonical SQLite v2 compiler.

No release, promotion, signing or inferred linguistic equivalences live here.
The existing release/conformance tools remain authoritative for archive safety.
"""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from tools.pack_v2 import pipeline
from tools.gha_factory.pack_conformance import check as strict
from tools.gha_factory.release import candidate

ROOT = Path(__file__).resolve().parents[3]
COLLECTIONS = {
    'lexemes': ('lexicon', 'lexeme_id', 'fields_json', 'id'),
    'senses': ('senses', 'sense_id', 'payload_json', 'sense_id'),
    'translations': ('translations', 'translation_id', 'payload_json', 'translation_id'),
    'examples': ('examples', 'example_id', 'payload_json', 'example_id'),
    'relations': ('lexical_relations', 'relation_id', 'payload_json', 'relation_id'),
}
MODES = frozenset(('fts_phrase', 'exact_surface'))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def safe_input(path, root, max_bytes):
    path = Path(path)
    require(not path.is_symlink() and path.is_file(), 'missing/symlink input')
    require(path.stat().st_size <= max_bytes, 'oversized input')
    require(path.resolve().is_relative_to(Path(root).resolve()), 'source evidence outside repository')
    return path


def match_source(db, document, language):
    """Check every compiler row against independently supplied canonical JSON."""
    require(document.get('contract_version') == pipeline.CONTRACT, 'source contract mismatch')
    require(any(r['language'] == language for r in document['lexemes']), 'pack language absent from source')
    for collection, (table, key, payload_col, db_key) in COLLECTIONS.items():
        rows = document[collection]
        expected = {r[key]: r for r in rows}
        require(len(expected) == len(rows), 'duplicate source IDs in ' + collection)
        actual = {}
        for rid, raw in db.execute(f'SELECT {db_key},{payload_col} FROM {table}'):
            require(rid not in actual, 'duplicate SQLite ID')
            actual[rid] = strict.object_json(raw, pipeline.MAX_ROW)
        require(actual == expected, 'source/SQLite ' + collection + ' mismatch')
    expected_concepts = {r['concept_id'] for r in document['senses']}
    actual_concepts = {r[0] for r in db.execute('SELECT concept_id FROM concepts')}
    require(expected_concepts == actual_concepts, 'source/SQLite concept IDs mismatch')


def probe_search(db, probes, document, language):
    """Require attested query expectations: no generic Unicode tokenizer promises."""
    require(isinstance(probes, dict) and probes.get('contract_version') == '1.0.0', 'invalid search evidence contract')
    cases = probes.get('cases')
    require(isinstance(cases, list) and cases, 'missing independent search expectations')
    lexemes = {r['lexeme_id']:r for r in document['lexemes']}
    sources = {r['source']['source_id'] for r in document['lexemes']}
    covered = set()
    metrics = []
    for case in cases:
        require(isinstance(case, dict), 'invalid search probe')
        require(set(case) == {'language','script','source_id','query','mode','expected_ids'}, 'invalid search probe fields')
        lang, script, query = case['language'], case['script'], case['query']
        require(lang == language and case['source_id'] in sources, 'probe/source language mismatch')
        require(isinstance(query, str) and 0 < len(query) <= 256, 'invalid query')
        require(case['mode'] in MODES, 'unsupported search mode; no implicit fallback')
        expected = case['expected_ids']
        require(isinstance(expected, list) and expected and len(set(expected)) == len(expected), 'empty/duplicate expected ids')
        require(all(rid in lexemes and lexemes[rid]['language'] == lang and
                    lexemes[rid]['script'] == script and
                    lexemes[rid]['source']['source_id'] == case['source_id'] for rid in expected),
                'probe expected ID not attested in the source/script')
        started = time.perf_counter_ns()
        if case['mode'] == 'fts_phrase':
            phrase = '"' + query.replace('"', '""') + '"'
            sql = """SELECT l.id FROM lexicon_fts JOIN lexicon l ON l.rowid=lexicon_fts.rowid
                     WHERE lexicon_fts MATCH ? AND l.language_code=? ORDER BY l.id"""
            found = [r[0] for r in db.execute(sql, (phrase, lang))]
        else:
            found = [r[0] for r in db.execute('SELECT id FROM lexicon WHERE language_code=? AND surface=? ORDER BY id',
                                               (lang, query))]
        millis = (time.perf_counter_ns() - started) / 1e6
        require(found == sorted(expected), 'search mismatch; tokenizer/normalization not supported for ' + lang + '/' + script)
        covered.add((lang, script))
        metrics.append({'mode':case['mode'], 'language':lang, 'script':script,
                        'query_latency_ms':round(millis, 3), 'matched_rows':len(found)})
    required = {(r['language'], r['script']) for r in document['lexemes'] if r['language'] == language}
    require(required <= covered, 'missing language/script-specific search probes')
    return metrics


def verify(archive, language, digest, source, search_evidence, *, root=ROOT, fixture_only=False):
    """Returns measured QA; always refuses to grant publication permission."""
    root = Path(root).resolve()
    require(isinstance(digest, str) and pipeline.SHA_RE.fullmatch(digest), 'expected SHA-256 required')
    require(len(archive) <= candidate.MAX_ARCHIVE, 'archive too large')
    started = time.perf_counter_ns()
    inspected = strict.inspect(archive, language, root=root,
                               allow_fixture=fixture_only, expected_sha256=digest)
    require(not inspected['fixture_only'] or fixture_only, 'fixture archive not permitted')
    document = strict.object_json(Path(source).read_bytes(), pipeline.MAX_JSON)
    pipeline.validate_document(document, language, root, fixture_only)
    raw = candidate.bounded_gzip(archive)
    members = candidate._members(strict.object_json(raw, pipeline.MAX_ENVELOPE))
    with tempfile.TemporaryDirectory(prefix='sqlite-scale-readonly-') as directory:
        path = Path(directory) / 'candidate.sqlite'
        path.write_bytes(members['content/content.sqlite'])
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            match_source(db, document, language)
            timings = probe_search(db, search_evidence, document, language)
    return {'status':'FIXTURE_QA_ONLY' if fixture_only else 'CANDIDATE_QA_ONLY',
            'language':language, 'archive_sha256':digest, 'archive_bytes':len(archive),
            'sqlite_bytes':len(members['content/content.sqlite']),
            'real_rows':inspected['actual_counts'], 'queries':timings,
            'verification_ms':round((time.perf_counter_ns() - started)/1e6, 3),
            'reproducibility':'NOT_TESTED', 'signature_status':'NOT_VERIFIED',
            'publication_approved':False}


def verify_reproducible(source, language, *, root=ROOT, fixture_only=False):
    """Compile twice into fresh temp directories; never touch public packs/manifest."""
    with tempfile.TemporaryDirectory(prefix='sqlite-scale-repro-') as directory:
        hashes, times = [], []
        for index in range(2):
            dest = Path(directory) / str(index)
            dest.mkdir()
            start = time.perf_counter_ns()
            blob, _ = pipeline.compile_pack(Path(source), language, dest, Path(root), fixture_only)
            times.append(round((time.perf_counter_ns() - start)/1e6, 3))
            hashes.append(pipeline.sha(blob))
        require(hashes[0] == hashes[1], 'compiler archive bytes are not reproducible')
        return {'reproducibility':'PASS', 'sha256':hashes[0], 'compile_ms':times}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--language')
    parser.add_argument('--sha256')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--probes', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.archive is None:
            result = strict.audit(args.root)
            result['sqlite_scale_qa'] = 'source-gated; no publication authorized'
        else:
            require(args.language and args.sha256 and args.source and args.probes, 'archive, SHA, source and attested search probes required')
            archive = args.archive
            require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size <= candidate.MAX_ARCHIVE,
                    'invalid archive path/size')
            src = safe_input(args.source, args.root, pipeline.MAX_JSON)
            probes = safe_input(args.probes, args.root, 1024*1024)
            evidence = strict.object_json(probes.read_bytes())
            result = verify(archive.read_bytes(), args.language, args.sha256, src, evidence, root=args.root)
            reproducibility = verify_reproducible(src, args.language, root=args.root)
            require(reproducibility['sha256'] == args.sha256, 'candidate differs from fresh canonical compilation')
            result.update(reproducibility)
        print(pipeline.compact(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, IndexError) as error:
        print(pipeline.compact({'status':'BLOCKED', 'reason':str(error), 'publication_approved':False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
