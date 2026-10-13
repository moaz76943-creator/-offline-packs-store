#!/usr/bin/env python3
"""Read-only, bounded report explaining why the public factory cannot produce packs.

No corpora are downloaded, no issue is created and no manifest is modified.
The report deliberately distinguishes source declarations from verified bytes.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_TASKS = frozenset({
    'lexical_ingest', 'morphology_ingest', 'examples_ingest',
    'sqlite_compile', 'pack_release',
})


def read_json(root, relative, maximum=2_000_000):
    path = root / relative
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('missing, symlinked or oversized repository input: ' + relative)
    return json.loads(path.read_text(encoding='utf-8'))


def inspect(root, supported_task_types=None):
    """Pure inventory. Accepted manifests are NOT assumed to be verified packs."""
    root = Path(root).resolve()
    registry = read_json(root, 'catalog/language_registry.v1.json')
    ledger = read_json(root, 'legal/ledger/sources.json')
    release = read_json(root, 'manifest.json')
    langs = registry.get('languages')
    if (registry.get('schema_version') != '1.0.0' or not isinstance(langs, list)
            or len(langs) != 100 or any(not isinstance(x, dict) for x in langs)):
        raise ValueError('canonical 100-language registry invalid')
    identities = [x.get('id') for x in langs]
    if any(not isinstance(x, str) or not x for x in identities) or len(set(identities)) != 100:
        raise ValueError('duplicate or invalid language identity')
    sources = ledger.get('sources')
    if ledger.get('schema_version') != '1.0.0' or not isinstance(sources, list):
        raise ValueError('source ledger invalid')
    if any(not isinstance(x, dict) for x in sources):
        raise ValueError('malformed source ledger entry')
    packs = release.get('packs')
    if not isinstance(packs, list) or release.get('total_languages') != 100:
        raise ValueError('public release manifest invalid')

    if supported_task_types is None:
        # Import the actual installed queue contract, not a guessed task list.
        from tools.gha_factory.dispatcher import queue
        supported_task_types = queue.TASK_TYPES
    declared_approved = [s for s in sources if s.get('status') == 'APPROVED_FOR_REDISTRIBUTION']
    eligible_dictionary = [s for s in declared_approved if s.get('kind') == 'dictionary']
    accepted_root = root / 'tools/gha_factory/admission/accepted'
    admissions = 0
    if accepted_root.is_dir():
        folders = list(accepted_root.iterdir())
        if len(folders) > 300:
            raise ValueError('admission report inventory exceeds bounded scan')
        for folder in folders:
            if folder.is_symlink() or not folder.is_dir():
                continue
            report_file = folder / 'queue.json'
            if not report_file.is_file() or report_file.is_symlink():
                continue
            report = read_json(folder, 'queue.json')
            if (report.get('schema_version') == '1.0.0'
                    and report.get('status') == 'ACCEPTED_FOR_QUEUE'
                    and report.get('publication_approved') is False
                    and isinstance(report.get('jobs'), list)):
                admissions += len(report['jobs'])
    supported = frozenset(supported_task_types)
    blockers = []
    if not eligible_dictionary:
        blockers.append('NO_APPROVED_DICTIONARY_SOURCE')
    if not admissions:
        blockers.append('NO_ADMITTED_SOURCE_PARTITIONS')
    missing = sorted(PRODUCTION_TASKS - supported)
    if missing:
        blockers.append('QUEUE_SUPPORTS_VERIFICATION_NOT_PRODUCTION')
    if not packs:
        blockers.append('NO_PUBLISHED_PACKS')

    return {
        'status': 'BLOCKED_SOURCE' if not eligible_dictionary else (
            'BLOCKED_PIPELINE' if admissions == 0 or missing else 'REQUIRES_PRODUCTION_QA'),
        'canonical_language_count': len(identities),
        'source_ledger_entries': len(sources),
        'declared_approved_source_count': len(declared_approved),
        'declared_approved_dictionary_count': len(eligible_dictionary),
        'admission_manifest_partition_count_unverified': admissions,
        'published_pack_manifest_entries_unverified': len(packs),
        'actual_production_records_verified': None,
        'queue_task_types': sorted(supported),
        'missing_production_task_types': missing,
        'blockers': blockers,
        'disclaimer': 'Inventory only: no source license, corpus bytes or packs verified by this report.',
    }


def main():
    try:
        report = inspect(ROOT)
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({'status': 'AUDIT_ERROR', 'error': str(error)}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as file:
            file.write('## Public factory production readiness\n\n')
            file.write(f"**Status:** `{report['status']}`. **Registered:** 100. ")
            file.write(f"**Approved dictionary declarations:** {report['declared_approved_dictionary_count']}. ")
            file.write(f"**Unverified manifest packs:** {report['published_pack_manifest_entries_unverified']}.\n\n")
            for blocker in report['blockers']:
                file.write(f'- `{blocker}`\n')
            file.write('\nNo corpus or pack has been produced by this diagnostic.\n')
    return 0  # Expected absence of approved sources is an explicit status, not a CI crash.


if __name__ == '__main__':
    sys.exit(main())
