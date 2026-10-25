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
# The live queue currently exposes verification-only task types. Avoid
# inventing names for future producer tasks owned by other agents.
VERIFICATION_TASKS = frozenset({'registry_validate', 'admission_partition_verify'})
# An unrecognized name is not a producer. This is the only task the readiness
# report already treats as source-backed production work.
PRODUCTION_TASKS = frozenset({'source_backed_real_worker'})


def read_json(root, relative, maximum=2_000_000):
    path = root / relative
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('missing, symlinked or oversized repository input: ' + relative)
    return json.loads(path.read_text(encoding='utf-8'))


def source_evidence_ok(root, source):
    """Route 05 evidence gate (pipeline.py license/source checks). Declaration alone fails closed."""
    try:
        from tools.gha_factory.admission import pipeline as admission
        retrieval = source.get('retrieval') if isinstance(source.get('retrieval'), dict) else {}
        artifact = admission.checked_file(
            root, retrieval.get('artifact_path'), retrieval.get('sha256'), 'source')
        admission.route05_source(
            root, source.get('source_id'), source.get('dataset_version'),
            artifact, 'wiktextract-jsonl')
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return True


def eligible_jobs(report, queue):
    """Count jobs the dispatcher controller would keep. Malformed jobs are discarded."""
    seen = set()
    count = 0
    for job in report['jobs']:
        if not isinstance(job, dict):
            continue
        index = job.get('partition_index')
        if type(index) is not int or index < 0 or index >= 100000:
            continue
        if (job.get('source_id') != report.get('source_id')
                or job.get('language') != report.get('language')
                or job.get('dataset_version') != report.get('dataset_version')
                or job.get('category') != 'dictionary'
                or job.get('path') != f'partition-{index:08d}.jsonl'
                or type(job.get('record_count')) is not int
                or not (1 <= job['record_count'] <= queue.MAX_PARTITION_RECORDS)
                or not queue.HEX.fullmatch(str(job.get('sha256', '')))):
            continue
        key = (job['source_id'], job['language'], report.get('source_artifact_sha256'), index)
        if key in seen:
            continue
        seen.add(key)
        count += 1
    return count


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
    declared_dictionary = [s for s in declared_approved if s.get('kind') == 'dictionary']
    # A status string is not admission. License and source bytes must match Route 05.
    verified_dictionary = [s for s in declared_dictionary if source_evidence_ok(root, s)]
    accepted_root = root / 'tools/gha_factory/admission/accepted'
    admissions = 0
    if accepted_root.is_dir():
        from tools.gha_factory.dispatcher import queue
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
                    and isinstance(report.get('jobs'), list)
                    and len(report['jobs']) <= 200):
                admissions += eligible_jobs(report, queue)
    supported = frozenset(supported_task_types)
    blockers = []
    if not verified_dictionary:
        blockers.append('NO_APPROVED_DICTIONARY_SOURCE')
    if not admissions:
        blockers.append('NO_ADMITTED_SOURCE_PARTITIONS')
    # Unknown tasks do not prove a producer. Stay verification-blocked until a
    # task is positively identified as source-backed production work.
    identified_production = bool((supported - VERIFICATION_TASKS) & PRODUCTION_TASKS)
    validation_only = not identified_production
    if not identified_production:
        blockers.append('QUEUE_SUPPORTS_VERIFICATION_NOT_PRODUCTION')
    else:
        blockers.append('PRODUCTION_WORKER_RESULT_NOT_VERIFIED')
    if not packs:
        blockers.append('NO_PUBLISHED_PACKS')

    return {
        'status': 'BLOCKED_SOURCE' if not verified_dictionary else (
            'BLOCKED_PIPELINE' if admissions == 0 or not identified_production else 'REQUIRES_PRODUCTION_QA'),
        'canonical_language_count': len(identities),
        'source_ledger_entries': len(sources),
        'declared_approved_source_count': len(declared_approved),
        'declared_approved_dictionary_count': len(declared_dictionary),
        'admission_manifest_partition_count_unverified': admissions,
        'published_pack_manifest_entries_unverified': len(packs),
        'actual_production_records_verified': None,
        'queue_task_types': sorted(supported),
        'queue_verification_only': validation_only,
        'actual_production_worker_result_verified': False,
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
