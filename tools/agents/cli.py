#!/usr/bin/env python3
"""Commands for the scheduled agents. Network is opt-in and bounded."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from tools.agents.common import halted, load_json_tolerant, write_heartbeat, write_json
from tools.agents.ops import docs_check, performance_report, schema_guard, untested_modules
from tools.agents.root_cause import open_recorded_issue, repair_update, signature_id
from tools.agents.roster import ROSTER
from tools.agents.work import (
    attribution_text,
    build_pack,
    concept_rows,
    coverage,
    grammar_for_language,
    iter_stored_rows,
    legal_report,
    next_window,
    qa_rows,
    render_status,
    shard_pairs,
    tune,
)
from tools.language_production.catalog import ROOT, load_languages, load_sections, registry_by_id
from tools.language_production.organization import load_graph, load_profiles

OUT = Path('/tmp/agent-out')


def _out(path):
    return OUT / path


def _halt(name):
    import os
    if halted(os.environ):
        write_heartbeat(_out('state/agents'), name, 'skipped', 'kill switch')
        print('halted')
        return True
    return False


def command_plan(_args):
    if _halt('coverage'):
        return 0
    languages = sorted(registry_by_id())
    sections = [row['id'] for row in load_sections().get('sections') or []]
    pairs = shard_pairs(languages, sections)
    cursor, warning = load_json_tolerant(
        ROOT / 'state' / 'agents' / 'plan.json',
        {'schema_version': '1.0.0', 'next_index': 0},
    )
    metrics, _metric_warning = load_json_tolerant(
        ROOT / 'state' / 'agents' / 'metrics.json',
        {'schema_version': '1.0.0', 'runs': []},
    )
    tuned = tune(metrics)
    window, nxt, window_warning = next_window(pairs, cursor, tuned['shard_limit'])
    graph = load_graph()
    rows = list(iter_stored_rows(ROOT / 'data' / 'agents' / 'harvest'))
    report = coverage(graph, rows, languages)
    plan = {
        'schema_version': '1.0.0',
        'next_index': nxt,
        'tune': tuned,
        'window': window,
        'warning': ' '.join(item for item in (warning, window_warning) if item),
    }
    write_json(_out('state/agents/plan.json'), plan)
    write_json(_out('state/agents/coverage.json'), report)
    _out('STATUS.md').write_text(render_status(report, plan), encoding='utf-8')
    write_heartbeat(_out('state/agents'), 'coverage', 'degraded' if plan['warning'] else 'ok', plan['warning'])
    print(json.dumps({'shards': len(window), 'concepts': report['concepts'], 'filled': report['filled_rows']}))
    return 0


def command_qa(_args):
    if _halt('qa'):
        return 0
    rows = list(iter_stored_rows(ROOT / 'data' / 'agents'))
    profiles = (load_profiles().get('languages') or [])
    result = qa_rows(rows, profiles, refetch=None, sample=5)
    write_json(_out('state/agents/qa-report.json'), {'schema_version': '1.0.0', **result})
    status = 'failed' if result['problems'] else 'ok'
    write_heartbeat(_out('state/agents'), 'qa', status, '; '.join(result['warnings']))
    print(json.dumps(result))
    return 1 if result['problems'] else 0


def command_legal(_args):
    if _halt('legal'):
        return 0
    rows = list(iter_stored_rows(ROOT / 'data' / 'agents' / 'harvest'))
    notices = {}
    evidence = ROOT / 'legal' / 'source_evidence'
    mapping = {
        'wikidata.lexemes': None,
        'kaikki.wiktextract': evidence / 'wiktionary-copyrights.txt',
        'tatoeba.sentences': evidence / 'tatoeba-terms.txt',
        'universal-dependencies': evidence / 'ud-english-ewt-license.txt',
    }
    for key, path in mapping.items():
        if path and path.is_file():
            notices[key] = path.read_text(encoding='utf-8')
    report = legal_report(rows, notices)
    write_json(_out('state/agents/legal-report.json'), report)
    counts = {}
    for row in rows:
        counts[row.get('source_id') or 'unknown'] = counts.get(row.get('source_id') or 'unknown', 0) + 1
    attr = _out('data/agents/attribution')
    for source_id, count in sorted(counts.items()):
        license_id = next((row.get('license_id') for row in rows if row.get('source_id') == source_id), 'unverified')
        text = attribution_text(source_id, license_id, 'see catalog/organization/sources.v1.json', count)
        path = attr / f'{source_id}.txt'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    status = 'failed' if report['problems'] else ('degraded' if report['warnings'] else 'ok')
    # Degraded legal evidence must surface its reason in the heartbeat, not
    # appear as a blank warning while packs remain unapproved.
    reasons = report['problems'] if report['problems'] else report['warnings']
    write_heartbeat(_out('state/agents'), 'legal', status, '; '.join(reasons[:3]))
    print(json.dumps({'problems': len(report['problems']), 'warnings': len(report['warnings'])}))
    return 1 if report['problems'] else 0


def command_packs(_args):
    if _halt('packs'):
        return 0
    rows = [row for row in iter_stored_rows(ROOT / 'data' / 'agents' / 'harvest')]
    by_language = {}
    for row in rows:
        by_language.setdefault(row.get('language') or 'und', []).append(row)
    wrote = 0
    for language, group in sorted(by_language.items()):
        result = build_pack(group, _out(f'data/agents/packs/{language}.sqlite'))
        wrote += int(bool(result.get('wrote')))
    warning = '' if wrote or not rows else 'rows were not traceable'
    if not rows:
        warning = 'no harvested rows; root manifest was not modified'
    write_heartbeat(_out('state/agents'), 'packs', 'ok', warning)
    print(json.dumps({'packs': wrote, 'warning': warning}))
    return 0


def command_classify(_args):
    if _halt('classifier'):
        return 0
    from tools.agents.work import classify_row
    from tools.language_production.organization import index_concepts
    index = index_concepts(load_graph())
    kept = []
    for row in iter_stored_rows(ROOT / 'data' / 'agents' / 'harvest'):
        placed = classify_row(row, index)
        if placed.get('status') == 'keep':
            kept.append(placed)
    write_json(_out('data/agents/classified/rows.json'), {'schema_version': '1.0.0', 'rows': kept})
    write_heartbeat(_out('state/agents'), 'classifier', 'ok', '' if kept else 'no anchored rows in this snapshot')
    print(json.dumps({'kept': len(kept)}))
    return 0


def command_grammar(_args):
    if _halt('grammar'):
        return 0
    profiles = load_profiles().get('languages') or []
    rows = list(iter_stored_rows(ROOT / 'data' / 'agents'))
    count = 0
    for profile in profiles:
        payload = grammar_for_language(profile, rows)
        if payload['slots']:
            write_json(_out(f"data/agents/grammar/{profile.get('id')}.json"), payload)
            count += 1
    write_heartbeat(_out('state/agents'), 'grammar', 'ok', '' if count else 'profiles only; no attested forms yet')
    print(json.dumps({'languages_with_slots': count}))
    return 0


def command_docs(_args):
    if _halt('docs'):
        return 0
    report = docs_check(ROOT)
    languages = sorted(registry_by_id())
    rows = list(iter_stored_rows(ROOT / 'data' / 'agents' / 'harvest'))
    coverage_report = coverage(load_graph(), rows, languages)
    plan, _warning = load_json_tolerant(ROOT / 'state' / 'agents' / 'plan.json', {'schema_version': '1.0.0'})
    _out('STATUS.md').write_text(render_status(coverage_report, plan), encoding='utf-8')
    write_json(_out('state/agents/docs-report.json'), report)
    status = 'failed' if report['missing'] else 'ok'
    write_heartbeat(_out('state/agents'), 'docs', status, ', '.join(report['missing'][:5]))
    print(json.dumps(report))
    return 1 if report['missing'] else 0


def command_test_gap(_args):
    if _halt('test-gap'):
        return 0
    names = untested_modules(ROOT / 'tools', [ROOT / 'tools', ROOT / 'tests'])
    write_json(_out('state/agents/test-gap.json'), {
        'schema_version': '1.0.0',
        'untested': names,
        'note': 'Report only. Tests are not generated, so a gap cannot invent a false pass.',
    })
    write_heartbeat(_out('state/agents'), 'test-gap', 'ok', f'{len(names)} modules have no name mention in tests')
    print(json.dumps({'untested': len(names)}))
    return 0


def command_schema_guard(_args):
    if _halt('schema-guard'):
        return 0
    from tools.pack_v2.pipeline import CONTRACT, DDL
    packs = list((ROOT / 'packs').glob('*.sqlite')) if (ROOT / 'packs').is_dir() else []
    report = schema_guard({'contract': CONTRACT, 'ddl': DDL, 'packs_present': bool(packs), 'user_version': 2})
    write_json(_out('state/agents/schema-guard.json'), report)
    status = 'failed' if report['problems'] else 'ok'
    write_heartbeat(_out('state/agents'), 'schema-guard', status, '; '.join(report['warnings']))
    print(json.dumps(report))
    return 1 if report['problems'] else 0


def command_performance(_args):
    if _halt('performance'):
        return 0
    sizes = {}
    for folder in (ROOT / 'data' / 'agents', ROOT / 'packs'):
        if not folder.is_dir():
            continue
        total = 0
        for path in folder.rglob('*'):
            if path.is_file():
                total += path.stat().st_size
        sizes[str(folder.relative_to(ROOT))] = total
    previous, _warning = load_json_tolerant(
        ROOT / 'state' / 'agents' / 'performance.json',
        {'schema_version': '1.0.0', 'bytes': {}},
    )
    report = performance_report({'bytes': sizes}, previous)
    write_json(_out('state/agents/performance.json'), report)
    write_heartbeat(_out('state/agents'), 'performance', 'degraded' if report['flags'] else 'ok', '; '.join(report['flags']))
    print(json.dumps(report))
    return 0


def command_repair(_args):
    if _halt('health'):
        return 0
    signature = _args.signature or 'no-signature'
    # A green CI run is not proof that independent agent schedules are healthy.
    from datetime import datetime, timezone
    from tools.agents.ops import stale_heartbeats
    snapshots = []
    folder = ROOT / 'state' / 'agents'
    known_names = {row['name'] for row in ROSTER}
    if folder.is_dir():
        for path in folder.glob('*.json'):
            payload, warning = load_json_tolerant(path, {'schema_version': '1.0.0'})
            if not warning and payload.get('name') in known_names:
                snapshots.append(payload)
    now = datetime.now(timezone.utc).timestamp()
    stale = stale_heartbeats(snapshots, now, 8 * 3600)
    degraded = sorted({
        row['name'] for row in snapshots
        if row.get('status') != 'ok' and row.get('name') not in stale
        and row.get('name') != 'health'  # do not perpetuate yesterday's own alert
    })
    health = {
        'schema_version': '1.0.0',
        'roster_count': len(ROSTER),
        'observed_count': len({row['name'] for row in snapshots}),
        'stale': stale,
        'degraded': degraded,
        'failed_github_run': signature != 'no-signature',
    }
    write_json(_out('state/agents/health-report.json'), health)
    health_status = 'degraded' if stale or degraded or health['failed_github_run'] else 'ok'
    health_warning = f"stale={len(stale)} degraded={len(degraded)} failed_run={int(health['failed_github_run'])}"
    if signature == 'no-signature':
        plan = {
            'schema_version': '1.0.0',
            'action': 'recorded',
            'retries': 0,
            'signature': 'no-signature',
            'seen_count': 0,
        }
        write_json(_out('state/agents/repair.json'), plan)
        write_heartbeat(_out('state/agents'), 'health', health_status, health_warning)
        print(json.dumps(plan, sort_keys=True))
        return 0
    sid = signature_id(signature)
    record_path = ROOT / 'state' / 'repair' / f'{sid}.json'
    record, warning = load_json_tolerant(record_path, {'schema_version': '1.0.0'})
    if not record_path.is_file():
        warning = ''
    causes = ROOT / 'ROOT_CAUSES.md'
    root_causes_text = causes.read_text(encoding='utf-8') if causes.is_file() else ''
    _record, plan = repair_update(
        record,
        signature,
        run_id=getattr(_args, 'run_id', '') or '',
        root_causes_text=root_causes_text,
    )
    if plan['action'] == 'open-root-cause-issue' and getattr(_args, 'file_issue', False):
        try:
            plan = open_recorded_issue(plan)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            plan['warning'] = f'issue not opened: {exc}'
    plan['warning'] = warning or plan.get('warning') or ''
    write_json(_out(f'state/repair/{sid}.json'), plan)
    write_json(_out('state/agents/repair.json'), {
        'schema_version': '1.0.0',
        'last_signature': sid,
        'action': plan['action'],
        'retries': 0,
    })
    write_heartbeat(_out('state/agents'), 'health', health_status, health_warning + ('; ' + plan['warning'] if plan['warning'] else ''))
    print(json.dumps(plan, sort_keys=True))
    return 0


def command_harvest(args):
    name = args.name
    if _halt(name):
        return 0
    from datetime import date
    from tools.agents.harvest import SourceSkip, accept_notice, load_lexemes, rows_from_lexeme, search_lexemes
    languages = load_languages()['languages']
    by_qid = {row['wikidata']: row['id'] for row in languages if row.get('wikidata') and row.get('id')}
    profiles = {row['id']: row for row in load_profiles().get('languages') or []}
    plan, warning = load_json_tolerant(
        ROOT / 'state' / 'agents' / 'plan.json',
        {'schema_version': '1.0.0', 'window': []},
    )
    window = plan.get('window') or []
    sections = {item.get('section') for item in window if isinstance(item, dict)}
    graph = load_graph()
    concepts = [
        row for row in concept_rows(graph)
        if not sections or row.get('section') in sections
    ][:4]
    retrieved = date.today().isoformat()
    grouped = {}
    skipped = []
    if name == 'harvest-wikidata':
        for concept in concepts:
            try:
                ids = search_lexemes(concept['wikidata'])
                entities = load_lexemes(ids)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                skipped.append({'wikidata': concept.get('wikidata'), 'reason': exc.__class__.__name__})
                continue
            for entity in entities.values():
                rows, reason = rows_from_lexeme(entity, concept, by_qid, profiles, retrieved)
                if reason != 'keep':
                    if reason in ('exclude', 'quarantine', 'placeholder'):
                        skipped.append({'wikidata': concept.get('wikidata'), 'reason': reason})
                    continue
                for row in rows:
                    grouped.setdefault((row['language'], row['section']), []).append(row)
    elif name == 'harvest-kaikki':
        notice = (ROOT / 'legal' / 'source_evidence' / 'wiktionary-copyrights.txt').read_text(encoding='utf-8')
        try:
            accept_notice(notice, 'CC-BY-SA-4.0', ('GFDL-1.3-only',))
            from tools.agents.harvest import fetch_bytes
            raw = fetch_bytes(
                'https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl',
                max_bytes=120000,
            )
        except (OSError, SourceSkip, UnicodeError) as exc:
            skipped.append({'reason': exc.__class__.__name__})
            raw = b''
        wanted = {row['wikidata'] for row in concepts}
        for line in raw.splitlines():
            if not line.startswith(b'{') or not line.endswith(b'}'):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            qids = []
            for sense in obj.get('senses') or []:
                for qid in sense.get('wikidata') or []:
                    if isinstance(qid, str):
                        qids.append(qid)
            if not set(qids) & wanted:
                continue
            # Kaikki lines in the sampled window have not carried a Wiktionary revision.
            # Without a page revision the row is not traceable, so it is not stored.
            skipped.append({'reason': 'missing_wiktionary_revision', 'word': obj.get('word')})
    elif name == 'harvest-tatoeba':
        from tools.agents.harvest import TATOEBA_CODES, tatoeba_sample
        notice = (ROOT / 'legal' / 'source_evidence' / 'tatoeba-terms.txt').read_text(encoding='utf-8')
        try:
            accept_notice(notice, 'CC-BY-2.0-FR')
            code = TATOEBA_CODES.get('sv', '')
            for sample in tatoeba_sample(code):
                grouped.setdefault(('sv', 'sentences'), []).append({
                    'language': 'sv',
                    'section': 'sentences',
                    'text': sample['text'],
                    'author': sample['author'],
                    'sentence_slot': sample['sentence_slot'],
                    'source_id': 'tatoeba.sentences',
                    'record_id': sample['record_id'],
                    'license_id': 'CC-BY-2.0-FR',
                    'retrieval_date': retrieved,
                    'origin_url': 'https://tatoeba.org/en/terms_of_use',
                    'status': 'keep',
                })
        except (OSError, SourceSkip, UnicodeError, ValueError) as exc:
            skipped.append({'reason': exc.__class__.__name__})
    else:
        notice_path = ROOT / 'legal' / 'source_evidence' / 'ud-english-ewt-license.txt'
        notice = notice_path.read_text(encoding='utf-8') if notice_path.is_file() else ''
        try:
            accept_notice(notice, 'CC-BY-SA-4.0')
            from tools.agents.harvest import ud_sample
            for sample in ud_sample():
                grouped.setdefault(('en', 'grammar'), []).append({
                    'language': 'en',
                    'section': 'grammar',
                    'text': sample['text'],
                    'sentence_slot': sample['sentence_slot'],
                    'source_id': 'universal-dependencies',
                    'record_id': sample['record_id'],
                    'license_id': 'CC-BY-SA-4.0',
                    'retrieval_date': retrieved,
                    'origin_url': 'https://github.com/UniversalDependencies/UD_English-EWT',
                    'status': 'keep',
                })
        except (OSError, SourceSkip, UnicodeError, ValueError) as exc:
            skipped.append({'reason': exc.__class__.__name__})
    wrote = 0
    for (language, section), rows in sorted(grouped.items()):
        payload = {
            'schema_version': '1.0.0',
            'source': name,
            'language': language,
            'section': section,
            'retrieval_date': retrieved,
            'rows': rows,
            'skipped': skipped,
        }
        write_json(_out(f'data/agents/harvest/{name.replace("harvest-", "")}/{language}/{section}.json'), payload)
        wrote += 1
    if not grouped:
        write_json(_out(f'data/agents/harvest/{name.replace("harvest-", "")}/checkpoint.json'), {
            'schema_version': '1.0.0',
            'source': name,
            'retrieval_date': retrieved,
            'rows': [],
            'skipped': skipped,
            'concepts_attempted': [row.get('wikidata') for row in concepts],
        })
    warning_text = f'skipped {len(skipped)}' if skipped else ''
    write_heartbeat(_out('state/agents'), name, 'degraded' if skipped and not wrote else 'ok', warning_text)
    print(json.dumps({'files': wrote, 'skipped': len(skipped), 'warning': warning}))
    return 0


def command_watchdog(_args):
    if _halt('watchdog'):
        return 0
    from datetime import datetime, timezone
    from tools.agents.ops import codeql_run_heartbeat, dispatch_batch, stale_heartbeats
    heartbeats = []
    folder = ROOT / 'state' / 'agents'
    if folder.is_dir():
        for path in folder.glob('*.json'):
            payload, _warning = load_json_tolerant(path, {'schema_version': '1.0.0'})
            if payload.get('name'):
                heartbeats.append(payload)
    now = datetime.now(timezone.utc).timestamp()
    # CodeQL has read-only permissions, so it cannot publish a file heartbeat.
    # Read actual Actions evidence rather than redispatching it every hour.
    run_file = getattr(_args, 'codeql_runs', '')
    if run_file:
        try:
            path = Path(run_file)
            if path.stat().st_size > 16384:
                raise ValueError('oversized CodeQL run evidence')
            result = codeql_run_heartbeat(json.loads(path.read_text(encoding='utf-8')), now)
        except (OSError, ValueError, json.JSONDecodeError):
            result = None
        if result is not None:
            from datetime import datetime as _dt
            prior = next((x for x in heartbeats if x.get('name') == 'codeql'), None)
            prior_stamp = (prior or {}).get('last_run') or ''
            try:
                prior_epoch = _dt.fromisoformat(prior_stamp.replace('Z', '+00:00')).timestamp()
            except (ValueError, TypeError, OverflowError):
                prior_epoch = -1
            observed_epoch = _dt.fromisoformat(result['last_run']).timestamp()
            if observed_epoch >= prior_epoch:
                heartbeats = [x for x in heartbeats if x.get('name') != 'codeql']
                heartbeats.append(result)
                write_json(_out('state/agents/codeql.json'), result)
    stale = stale_heartbeats(heartbeats, now, 8 * 3600)
    # Rotate by UTC hour; no new ledger or scheduler is needed. A continuously
    # failing early roster entry cannot monopolize all three recovery slots.
    batch = dispatch_batch(stale, cap=3, rotation=int(now // 3600))
    write_json(_out('state/agents/watchdog.json'), {
        'schema_version': '1.0.0',
        'stale': stale,
        'dispatch': batch,
    })
    # A requested workflow dispatch is not verified worker completion.
    write_heartbeat(_out('state/agents'), 'watchdog',
                    'degraded' if stale else 'ok',
                    f'requested {len(batch)} of {len(stale)} stale agents')
    print('\n'.join(batch))
    return 0


def command_links(_args):
    if _halt('links'):
        return 0
    import urllib.request
    from tools.agents.ops import urls_well_formed
    catalog = json.loads((ROOT / 'catalog' / 'organization' / 'sources.v1.json').read_text(encoding='utf-8'))
    urls = []
    for source in catalog.get('sources') or []:
        for key in ('origin_url', 'license_page_url'):
            if source.get(key):
                urls.append(source[key])
    bad = urls_well_formed(urls)
    results = []
    for url in urls:
        if url in bad:
            results.append({'url': url, 'status': 'malformed'})
            continue
        request = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'offline-packs-store/1.0 (language-production)'})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                results.append({'url': url, 'status': response.status})
        except Exception as exc:
            results.append({'url': url, 'status': exc.__class__.__name__})
    write_json(_out('state/agents/links.json'), {'schema_version': '1.0.0', 'results': results})
    write_heartbeat(_out('state/agents'), 'links', 'degraded' if bad else 'ok', f'{len(bad)} malformed')
    print(json.dumps({'checked': len(results)}))
    return 0


def command_janitor(args):
    if _halt('janitor'):
        return 0
    from tools.agents.ops import janitor_action
    payload, warning = load_json_tolerant(args.pr_json, {'schema_version': '1.0.0', 'pulls': []})
    actions = []
    for pr in payload.get('pulls') or []:
        action, reason = janitor_action(pr)
        actions.append({'number': pr.get('number'), 'action': action, 'reason': reason})
    write_json(_out('state/agents/janitor.json'), {'schema_version': '1.0.0', 'actions': actions, 'warning': warning})
    write_heartbeat(_out('state/agents'), 'janitor', 'degraded' if warning else 'ok', warning)
    print(json.dumps(actions))
    return 0


def command_cleanup(args):
    if _halt('cleanup'):
        return 0
    from tools.agents.ops import branch_deletable
    names = []
    if args.list and Path(args.list).is_file():
        names = [line.strip() for line in Path(args.list).read_text(encoding='utf-8').splitlines() if line.strip()]
    delete = [name for name in names if branch_deletable(name, True)]
    write_json(_out('state/agents/cleanup.json'), {'schema_version': '1.0.0', 'delete': delete})
    write_heartbeat(_out('state/agents'), 'cleanup', 'ok', f'{len(delete)} branches')
    print('\n'.join(delete))
    return 0


def command_triage(args):
    if _halt('triage'):
        return 0
    from tools.agents.ops import agent_for_issue, duplicate_issues
    payload, warning = load_json_tolerant(args.issues, {'schema_version': '1.0.0', 'issues': []})
    dupes = duplicate_issues(payload.get('issues') or [])
    links = [
        {'number': issue.get('number'), 'agent': agent_for_issue(issue.get('title'))}
        for issue in payload.get('issues') or [] if isinstance(issue, dict)
    ]
    write_json(_out('state/agents/triage.json'), {
        'schema_version': '1.0.0',
        'close': [issue.get('number') for issue in dupes],
        'links': links,
        'warning': warning,
    })
    write_heartbeat(_out('state/agents'), 'triage', 'degraded' if warning else 'ok', warning)
    print(json.dumps({'close': len(dupes)}))
    return 0


def command_heartbeat(args):
    write_heartbeat(Path(args.dir), args.name, args.status, args.warning or '')
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    mapping = {
        'plan': command_plan,
        'qa': command_qa,
        'legal': command_legal,
        'packs': command_packs,
        'classify': command_classify,
        'grammar': command_grammar,
        'docs': command_docs,
        'test-gap': command_test_gap,
        'schema-guard': command_schema_guard,
        'performance': command_performance,
        'repair': command_repair,
    }
    for name, func in mapping.items():
        item = commands.add_parser(name)
        if name == 'repair':
            item.add_argument('--signature', default='')
            item.add_argument('--run-id', default='')
            item.add_argument('--file-issue', action='store_true')
        item.set_defaults(func=func)
    watchdog = commands.add_parser('watchdog')
    watchdog.add_argument('--codeql-runs', default='')
    watchdog.set_defaults(func=command_watchdog)
    commands.add_parser('links').set_defaults(func=command_links)
    janitor = commands.add_parser('janitor')
    janitor.add_argument('--pr-json', required=True)
    janitor.set_defaults(func=command_janitor)
    cleanup = commands.add_parser('cleanup')
    cleanup.add_argument('--list', default='')
    cleanup.set_defaults(func=command_cleanup)
    triage = commands.add_parser('triage')
    triage.add_argument('--issues', required=True)
    triage.set_defaults(func=command_triage)
    beat = commands.add_parser('heartbeat')
    beat.add_argument('--name', required=True)
    beat.add_argument('--status', required=True)
    beat.add_argument('--dir', required=True)
    beat.add_argument('--warning', default='')
    beat.set_defaults(func=command_heartbeat)
    for harvest_name in ('harvest-wikidata', 'harvest-kaikki', 'harvest-tatoeba', 'harvest-ud'):
        item = commands.add_parser(harvest_name)
        item.set_defaults(func=command_harvest, name=harvest_name)
    roster = commands.add_parser('roster')
    roster.set_defaults(func=lambda _args: print(json.dumps([row['name'] for row in ROSTER])) or 0)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'{exc.__class__.__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
