"""Planning, classification, grammar, QA, legal checks and pack candidates.

Every function tolerates missing input. None of them invent words.
"""

import hashlib
import os
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path

from tools.agents.common import (
    BLOCKED_CONCEPTS,
    SCHEMA_VERSION,
    is_placeholder,
    policy_qids,
    row_traceable,
    script_matches,
    write_json,
)
from tools.language_production.levels import estimate_level
from tools.open_sources.assess import positive_match

MAX_PARALLEL_CAP = 20
MAX_SHARDS = 200
MIN_PARALLEL = 4
MIN_SHARDS = 20


def concept_rows(graph):
    rows = []
    for section in (graph or {}).get('sections') or []:
        if not isinstance(section, dict):
            continue
        for subsection in section.get('subsections') or []:
            if not isinstance(subsection, dict):
                continue
            for concept in subsection.get('concepts') or []:
                if not isinstance(concept, dict):
                    continue
                qid = concept.get('wikidata')
                if qid in BLOCKED_CONCEPTS:
                    continue
                rows.append({
                    'section': section.get('id'),
                    'subsection': subsection.get('id'),
                    'concept_id': concept.get('id'),
                    'wikidata': qid,
                })
    return rows


def shard_pairs(language_ids, section_ids):
    pairs = []
    for section in section_ids:
        for language in language_ids:
            pairs.append({'language': language, 'section': section})
    return pairs


def next_window(pairs, cursor, limit):
    """Continue from next_index. A bad cursor restarts at 0 and warns."""
    warning = ''
    if not pairs:
        return [], 0, 'no shards'
    try:
        index = int((cursor or {}).get('next_index') or 0)
    except (TypeError, ValueError):
        index = 0
        warning = 'malformed cursor'
    index = index % len(pairs)
    try:
        size = int(limit)
    except (TypeError, ValueError):
        size = MIN_SHARDS
        warning = warning or 'malformed limit'
    size = max(1, min(size, len(pairs), MAX_SHARDS))
    window = [pairs[(index + offset) % len(pairs)] for offset in range(size)]
    return window, (index + size) % len(pairs), warning


def tune(metrics):
    """Rule-based shard sizing from recorded durations and failures. No model calls."""
    parallel = 12
    shards = 80
    reason = 'default until a metrics snapshot exists'
    if not isinstance(metrics, dict) or metrics.get('schema_version') != SCHEMA_VERSION:
        return {'max_parallel': parallel, 'shard_limit': shards, 'reason': reason}
    runs = [row for row in metrics.get('runs') or [] if isinstance(row, dict)]
    if not runs:
        return {'max_parallel': parallel, 'shard_limit': shards, 'reason': reason}
    recent = runs[-5:]
    failures = sum(1 for row in recent if row.get('status') == 'failed')
    rate = failures / len(recent)
    durations = [row.get('duration_seconds') for row in recent if isinstance(row.get('duration_seconds'), (int, float))]
    mean = sum(durations) / len(durations) if durations else None
    if rate > 0.3:
        parallel = max(MIN_PARALLEL, parallel - 4)
        shards = max(MIN_SHARDS, int(shards * 0.8))
        reason = 'failure rate above 0.3; smaller window'
    elif rate < 0.05 and mean is not None and mean < 600:
        parallel = MAX_PARALLEL_CAP
        shards = MAX_SHARDS
        reason = 'recent runs stayed under 10 minutes with few failures'
    return {'max_parallel': parallel, 'shard_limit': shards, 'reason': reason}


def iter_stored_rows(root):
    root = Path(root)
    if not root.is_dir():
        return
    for path in sorted(root.rglob('*.json')):
        if path.name.endswith('.heartbeat.json'):
            continue
        try:
            import json
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload.get('rows') if isinstance(payload, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield row


def coverage(graph, stored_rows, language_ids):
    inventory = concept_rows(graph)
    by_section = defaultdict(list)
    for row in inventory:
        by_section[row['section']].append(row['concept_id'])
    filled = defaultdict(set)
    for row in stored_rows or []:
        if not row_traceable(row):
            continue
        concept = row.get('concept_id')
        language = row.get('language')
        if isinstance(concept, str) and isinstance(language, str):
            filled[language].add(concept)
    languages = []
    known = set()
    for concept in inventory:
        known.add(concept['concept_id'])
    for language in language_ids:
        have = {concept for concept in filled.get(language, set()) if concept in known}
        total = len(known)
        languages.append({
            'id': language,
            'filled': len(have),
            'gaps': total - len(have),
            'fill_ratio': round(len(have) / total, 6) if total else 0.0,
        })
    languages.sort(key=lambda row: (-row['gaps'], row['id']))
    return {
        'schema_version': SCHEMA_VERSION,
        'concepts': len(known),
        'languages': languages,
        'filled_rows': sum(row['filled'] for row in languages),
        'gap_rows': sum(row['gaps'] for row in languages),
    }


def render_status(report, plan):
    report = report or {}
    lines = [
        '# Language production status',
        '',
        'Counts below are computed from stored rows and the concept graph.',
        'A missing harvest file stays a gap. No word is invented.',
        '',
        f"Concepts in the graph: {report.get('concepts') or 0}",
        f"Filled language-concept cells: {report.get('filled_rows') or 0}",
        f"Open language-concept cells: {report.get('gap_rows') or 0}",
        '',
        '| Language | Filled | Open gaps | Fill ratio |',
        '| --- | ---: | ---: | ---: |',
    ]
    shown = 0
    for row in report.get('languages') or []:
        if shown >= 20 and not row.get('filled'):
            continue
        lines.append(
            f"| {row.get('id')} | {row.get('filled')} | {row.get('gaps')} | {row.get('fill_ratio')} |"
        )
        shown += 1
        if shown >= 30:
            break
    if shown == 0:
        lines.append('| — | 0 | 0 | 0 |')
    total_languages = len(report.get('languages') or [])
    if total_languages > shown:
        lines.append(f'| … |  |  | {total_languages} languages, largest gaps first |')
    tune_row = (plan or {}).get('tune') or {}
    lines.extend([
        '',
        f"Next shard limit: {tune_row.get('shard_limit', MIN_SHARDS)}",
        f"Next max parallel: {tune_row.get('max_parallel', MIN_PARALLEL)}",
        f"Tune reason: {tune_row.get('reason', 'no plan yet')}",
        '',
        'Level labels are `estimated:heuristic-v1`, not corpus bands.',
        'Kill switch: set repository variable `AGENTS_HALT` or `LANGUAGE_PRODUCTION_HALT` to `true`.',
        'The 2026-10-18 chat decision approved Wikidata (CC0), Kaikki/Wiktionary (CC-BY-SA-4.0 and GFDL) and Tatoeba (CC-BY-2.0-FR). A GitHub line `decision: approve` is not required for those sources.',
        'GPL, CC-BY-SA-3.0, NC, ND, UniMorph, Apertium and unverified OmegaWiki stay excluded.',
        'Root `manifest.json` stays fail-closed. Candidate packs live under `data/agents/packs/` on `agents/data`.',
        '',
    ])
    return '\n'.join(lines)


def classify_row(row, index):
    """Place a row only when its QID is already in the concept graph."""
    if not isinstance(row, dict):
        return {'status': 'reject', 'reason': 'malformed'}
    if not row_traceable(row):
        return {'status': 'reject', 'reason': 'untraceable'}
    decision, reason = policy_qids(row.get('qids') or [])
    if decision != 'keep':
        return {'status': decision, 'reason': reason}
    qid = row.get('wikidata')
    slot = index.get(qid) if isinstance(qid, str) else None
    if not slot:
        return {'status': 'unplaced', 'reason': 'no_concept_anchor'}
    text = row.get('lemma') or row.get('text') or ''
    level = estimate_level(text, 1, 1)
    placed = dict(row)
    placed.update({
        'status': 'keep',
        'section': slot.get('section'),
        'subsection': slot.get('subsection'),
        'concept_id': slot.get('concept_id'),
        'level': level,
    })
    return placed


def grammar_for_language(profile, rows):
    """Profile facts fill script and direction. Other slots wait for attested rows."""
    profile = profile or {}
    language = profile.get('id')
    slots = []
    if profile.get('script'):
        slots.append({
            'id': 'grammar.script',
            'language': language,
            'value': profile.get('script'),
            'source_id': 'catalog.language_profiles',
            'record_id': f"profile:{language}:script",
            'license_id': 'CC0-1.0',
            'retrieval_date': 'registry',
            'evidence': 'language_profiles.v1.json',
        })
    if profile.get('direction'):
        slots.append({
            'id': 'grammar.direction',
            'language': language,
            'value': profile.get('direction'),
            'source_id': 'catalog.language_profiles',
            'record_id': f"profile:{language}:direction",
            'license_id': 'CC0-1.0',
            'retrieval_date': 'registry',
            'evidence': 'language_profiles.v1.json',
        })
    for row in rows or []:
        if row.get('language') != language or row.get('status') not in (None, 'keep'):
            continue
        if row.get('forms') and row.get('pos') == 'verb':
            slots.append({
                'id': 'verb.forms',
                'language': language,
                'value': row.get('forms'),
                'source_id': row.get('source_id'),
                'record_id': row.get('record_id'),
                'license_id': row.get('license_id'),
                'retrieval_date': row.get('retrieval_date'),
                'level': (row.get('level') or {}).get('level_id'),
            })
        if row.get('sentence_slot') in ('sentence.statement', 'sentence.question'):
            slots.append({
                'id': row['sentence_slot'],
                'language': language,
                'value': row.get('text'),
                'source_id': row.get('source_id'),
                'record_id': row.get('record_id'),
                'license_id': row.get('license_id'),
                'retrieval_date': row.get('retrieval_date'),
                'level': (row.get('level') or {}).get('level_id'),
            })
    return {'schema_version': SCHEMA_VERSION, 'language': language, 'slots': slots}


def qa_rows(rows, profiles, refetch=None, sample=3):
    """Return problems. A refetch mismatch is a hard problem. Network absence is a warning."""
    problems = []
    warnings = []
    seen = set()
    by_id = {row.get('id'): row for row in profiles or [] if isinstance(row, dict)}
    chosen = [row for row in rows or [] if isinstance(row, dict)][:sample]
    for row in chosen:
        label = row.get('record_id') or '?'
        if not row_traceable(row):
            problems.append(f'{label}: untraceable or placeholder')
            continue
        # Match the harvester's provenance identity: a single attested sense
        # may legitimately anchor more than one concept, or a different
        # approved source may reuse a record ID.
        key = (row.get('language'), row.get('source_id'), row.get('record_id'),
               row.get('sense_id') or '', row.get('concept_id') or '')
        if key in seen:
            problems.append(f'{label}: duplicate')
            continue
        seen.add(key)
        profile = by_id.get(row.get('language')) or {}
        text = row.get('lemma') or row.get('text') or ''
        if not script_matches(text, profile.get('script')):
            problems.append(f'{label}: wrong script for {profile.get("script")}')
        decision, reason = policy_qids(row.get('qids') or ([row.get('wikidata')] if row.get('wikidata') else []))
        if decision != 'keep':
            problems.append(f'{label}: {reason}')
        if refetch is None:
            continue
        try:
            remote = refetch(row)
        except OSError as exc:
            warnings.append(f'{label}: recheck skipped ({exc.__class__.__name__})')
            continue
        if not isinstance(remote, dict) or remote.get('record_id') != row.get('record_id'):
            problems.append(f'{label}: source id mismatch')
        elif (remote.get('lemma') or remote.get('text')) != text:
            problems.append(f'{label}: source text mismatch')
    return {'problems': problems, 'warnings': warnings, 'sampled': len(chosen)}


def legal_report(rows, notices):
    """Block only when a stored row's license conflicts with its notice. Missing notices warn."""
    problems = []
    warnings = []
    seen_warnings = set()
    notices = notices or {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        license_id = row.get('license_id')
        source_id = row.get('source_id') or ''
        notice = notices.get(source_id, notices.get(license_id))
        if notice is None:
            # One warning per missing evidence source; never interpret this as
            # license approval or silently promote the candidate to production.
            warning = f'{source_id or license_id}: notice not loaded'
            if warning not in seen_warnings:
                seen_warnings.add(warning)
                warnings.append(warning)
            continue
        ok, reasons = positive_match(notice, license_id, row.get('co_offered') or ())
        if not ok:
            problems.append(f"{row.get('record_id')}: {','.join(reasons)}")
    return {'schema_version': SCHEMA_VERSION, 'problems': problems, 'warnings': warnings}


def attribution_text(source_id, license_id, origin, count):
    share = ''
    if license_id in ('CC-BY-SA-4.0', 'GFDL-1.3-only'):
        share = (
            'Share-alike: adaptations of this material must stay under the same license '
            '(CC-BY-SA-4.0 and GFDL-1.3-only when the Wiktionary grant offers both).\n'
        )
    elif license_id == 'CC-BY-2.0-FR':
        share = 'Attribution: cite the sentence author. This license is not share-alike.\n'
    return (
        f'Title: {source_id}\n'
        f'License: {license_id}\n'
        f'Source: {origin}\n'
        f'Records: {count}\n'
        f'{share}'
        'Changes: bounded extract; no words invented; content-policy exclusions removed.\n'
        'This file is not the ledger. Root manifest release stays fail-closed.\n'
    )


def build_pack(rows, output):
    """Stage a non-production legacy candidate before replacing earlier bytes.

    These entries-only databases are NOT canonical SQLite v2, source approved or
    publishable. Failures must leave the prior database and receipt intact.
    """
    kept = [row for row in rows or [] if row_traceable(row)]
    output = Path(output)
    if not kept:
        return {'wrote': False, 'reason': 'no traceable rows', 'sha256': None,
                'production_ready': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = output.with_suffix('.sha256.json')

    with tempfile.TemporaryDirectory(prefix=f'.{output.name}.', dir=output.parent) as tmp:
        staging = Path(tmp)
        candidate = staging / 'candidate.sqlite'
        with sqlite3.connect(candidate) as connection:
            connection.execute(
                'CREATE TABLE entries (language TEXT, concept_id TEXT, lemma TEXT, '
                'source_id TEXT, record_id TEXT, license_id TEXT, retrieval_date TEXT)'
            )
            connection.executemany(
                'INSERT INTO entries VALUES (?,?,?,?,?,?,?)',
                [(
                    row.get('language'), row.get('concept_id'),
                    row.get('lemma') or row.get('text'), row.get('source_id'),
                    row.get('record_id'), row.get('license_id'),
                    row.get('retrieval_date'),
                ) for row in kept],
            )
            connection.commit()

        with sqlite3.connect(candidate) as connection:
            if connection.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise ValueError('Legacy candidate failed SQLite integrity_check')
            if connection.execute('SELECT count(*) FROM entries').fetchone()[0] != len(kept):
                raise ValueError('Legacy candidate count mismatch')
        digest_state = hashlib.sha256()
        with candidate.open('rb') as source:
            for chunk in iter(lambda: source.read(65536), b''):
                digest_state.update(chunk)
        digest = digest_state.hexdigest()
        receipt = staging / 'candidate.sha256.json'
        write_json(receipt, {
            'schema_version': SCHEMA_VERSION,
            'path': str(output),
            'sha256': digest,
            'rows': len(kept),
            'format': 'legacy-entry-candidate',
            'production_ready': False,
        })
        # Idempotent reruns must not churn the shared agents/data checkpoint.
        # Compare on-disk bytes and metadata, not old, potentially stale flags.
        if output.is_file() and receipt_path.is_file():
            with output.open('rb') as old, candidate.open('rb') as new:
                if all(a == b for a, b in zip(iter(lambda: old.read(65536), b''),
                                               iter(lambda: new.read(65536), b''))):
                    if receipt_path.read_bytes() == receipt.read_bytes():
                        return {'wrote': False, 'reason': 'unchanged candidate',
                                'sha256': digest, 'rows': len(kept),
                                'production_ready': False}

        previous = staging / 'previous.sqlite'
        existed = output.exists()
        if existed:
            # Disk-to-disk backup, never loading the previous pack into memory.
            shutil.copy2(output, previous)
        try:
            os.replace(candidate, output)
            os.replace(receipt, receipt_path)
        except OSError:
            if existed:
                os.replace(previous, output)
            else:
                output.unlink(missing_ok=True)
            raise

    return {'wrote': True, 'reason': '', 'sha256': digest,
            'rows': len(kept), 'production_ready': False}
