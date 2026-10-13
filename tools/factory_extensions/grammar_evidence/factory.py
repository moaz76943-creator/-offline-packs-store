#!/usr/bin/env python3
"""Versioned, evidence-gated grammar sidecar. Does not publish content.

No network, no inferred inflections, no language-family fallback, no rights claims.
All input snapshots are independently governed; a passing structural audit is not
human approval or an authentic grammar parser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

VERSION = '1.0.0'
RULE_ID = re.compile(r'^gr1:([a-z]{2,3}):([a-z][a-z0-9_]{2,63}):v([1-9][0-9]*)$')
SHA = re.compile(r'^[a-f0-9]{64}$')
KINDS = frozenset(('descriptive', 'pedagogical'))
REGISTERS = frozenset(('formal', 'neutral', 'informal', 'colloquial', 'literary', 'unknown'))
ALLOWED_LEDGERS = frozenset(('morphology', 'dictionary', 'examples'))
MAX_ROW = 16 * 1024


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(obj):
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def snapshot(root):
    root = Path(root)
    registry = load(root / 'catalog/language_registry.v1.json')
    overrides = load(root / 'standards/morphology/feature_overrides.json')
    ledger = load(root / 'legal/ledger/sources.json')
    assert registry['schema_version'] == overrides['schema_version'] == ledger['schema_version'] == VERSION
    langs = {x['id']: x for x in registry['languages']}
    if len(langs) != 100 or len(registry['languages']) != 100:
        raise ValueError('canonical_registry_not_100_unique')
    if len(overrides['features']) != 25 or len(set(overrides['features'])) != 25:
        raise ValueError('invalid_canonical_dimensions')
    return {'langs': langs, 'features': frozenset(overrides['features']),
            'overrides': overrides['overrides'],
            'ledger': {x['source_id']: x for x in ledger['sources']}, 'root': root}


def capability(context, language, feature):
    if language not in context['langs'] or feature not in context['features']:
        return 'unknown'
    return context['overrides'].get(language, {}).get(feature, 'unknown')


def rule_hash(rule):
    return digest({k: v for k, v in rule.items() if k != 'review'})


def collect_evidence(lexical, forms):
    """Strict IDs; lexical v1 and attested morphology v1; never merge identities."""
    if lexical.get('contract_version') != VERSION:
        raise ValueError('lexical_contract_mismatch')
    lexemes = {}
    for row in lexical['lexemes']:
        key = row['lexeme_id']
        if key in lexemes:
            raise ValueError('duplicate_lexeme')
        lexemes[key] = row
    senses = {}
    for row in lexical['senses']:
        key = row['sense_id']
        if key in senses or row['lexeme_id'] not in lexemes:
            raise ValueError('duplicate_or_dangling_sense')
        senses[key] = row
    examples = {}
    for row in lexical['examples']:
        key = row['example_id']
        if key in examples or row['sense_id'] not in senses:
            raise ValueError('duplicate_or_dangling_example')
        examples[key] = row
    observed = {}
    for form in forms:
        if not isinstance(form, dict) or any(k not in form for k in
                ('language_code', 'lemma_id', 'sense_id', 'form', 'features', 'source_id', 'evidence_version')):
            raise ValueError('malformed_attested_form')
        key = digest([form['language_code'], form['lemma_id'], form['sense_id'], form['form'], form['features']])
        if key in observed:
            raise ValueError('duplicate_attested_form')
        observed[key] = form
    return {'lexemes': lexemes, 'senses': senses, 'examples': examples, 'forms': observed}


def source_approved(src, context):
    """Presence in a local file or a license label cannot supply source approval."""
    if not isinstance(src, dict) or not all(k in src for k in ('source_id', 'dataset_version', 'artifact_sha256', 'record_locator')):
        return False
    record = context['ledger'].get(src['source_id'])
    if not record or record.get('status') != 'APPROVED_FOR_REDISTRIBUTION':
        return False
    if record.get('kind') not in ALLOWED_LEDGERS or not record.get('review'):
        return False
    retrieval = record.get('retrieval') or {}
    artifact = retrieval.get('artifact_path')
    if not isinstance(artifact, str) or not artifact or Path(artifact).is_absolute():
        return False
    file_path = (context['root'] / artifact).resolve()
    if not file_path.is_relative_to(context['root'].resolve()) or not file_path.is_file():
        return False
    h = hashlib.sha256()
    with file_path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            h.update(block)
    if h.hexdigest() != retrieval.get('sha256'):
        return False
    if (src['dataset_version'] != record.get('dataset_version') or
        src['artifact_sha256'] != retrieval.get('sha256') or
        not SHA.fullmatch(str(src['artifact_sha256']))):
        return False
    return isinstance(src['record_locator'], str) and bool(src['record_locator'].strip())


def local_source(src, context):
    return source_approved(src, context)


def approved_lexical_source(src, context):
    return (isinstance(src, dict) and src.get('publication_approved') is True
            and src.get('fixture_only') is False and source_approved(src, context))


def check_rule(rule, context, corpus, reviewers, index):
    """Return deterministic blocking reasons; errors never convert to approvals."""
    problems = set()
    if not isinstance(rule, dict):
        return ['invalid_rule']
    rid, lang = rule.get('rule_id'), rule.get('language')
    m = RULE_ID.fullmatch(rid) if isinstance(rid, str) else None
    if not m or m.group(1) != lang or lang not in context['langs'] or rule.get('schema_version') != VERSION:
        problems.add('invalid_or_cross_language_identity')
    feature = rule.get('capability')
    state = capability(context, lang, feature)
    if state != 'supported':
        problems.add('unsupported_or_unknown_capability')
    if rule.get('kind') not in KINDS or rule.get('register') not in REGISTERS:
        problems.add('invalid_rule_kind_or_register')
    for field in ('explanation', 'pattern', 'domain'):
        if not isinstance(rule.get(field), str) or not rule[field].strip():
            problems.add('missing_' + field)
    for field in ('exceptions', 'prerequisites', 'lexeme_refs', 'form_refs', 'example_refs', 'sources'):
        if not isinstance(rule.get(field), list):
            problems.add('missing_' + field)
    if problems:
        return sorted(problems)
    if rule['kind'] == 'pedagogical' and not rule.get('descriptive_rule_id'):
        problems.add('pedagogical_rule_requires_descriptive_parent')
    if rule.get('descriptive_rule_id'):
        parent = index.get(rule['descriptive_rule_id'])
        if not parent or parent.get('language') != lang or parent.get('kind') != 'descriptive':
            problems.add('invalid_descriptive_parent')
    if not rule['sources'] or not all(local_source(s, context) for s in rule['sources']):
        problems.add('source_rights_not_approved')
    if not rule['lexeme_refs'] or not rule['form_refs'] or not rule['example_refs']:
        problems.add('attested_links_incomplete')
    for dep in rule['prerequisites']:
        if dep == rid or dep not in index or index[dep].get('language') != lang:
            problems.add('invalid_prerequisite')
    for ref in rule['lexeme_refs']:
        if not isinstance(ref, dict):
            problems.add('invalid_lexeme_link')
            continue
        lex = corpus['lexemes'].get(ref.get('lexeme_id'))
        sense = corpus['senses'].get(ref.get('sense_id'))
        if (not lex or not sense or sense['lexeme_id'] != ref.get('lexeme_id') or
                lex['language'] != lang or not approved_lexical_source(lex.get('source'), context) or
                not approved_lexical_source(sense.get('source'), context)):
            problems.add('invalid_or_unapproved_lexeme_link')
    for ref in rule['form_refs']:
        if not isinstance(ref, dict):
            problems.add('invalid_form_link')
            continue
        key = digest([lang, ref.get('lemma_id'), ref.get('sense_id'), ref.get('form'), ref.get('features')])
        form = corpus['forms'].get(key)
        if not form or not source_approved({'source_id': form['source_id'],
               'dataset_version': ref.get('dataset_version'), 'artifact_sha256': ref.get('artifact_sha256'),
               'record_locator': ref.get('record_locator')}, context) or ref.get('evidence_version') != form['evidence_version']:
            problems.add('invalid_or_unapproved_form_link')
        if (isinstance(ref.get('features'), dict) and feature in ref['features'] and
                rule.get('feature_value') and ref['features'][feature] != rule['feature_value']):
            problems.add('form_feature_contradiction')
    for ref in rule['example_refs']:
        if not isinstance(ref, dict):
            problems.add('invalid_example_link')
            continue
        row = corpus['examples'].get(ref.get('example_id'))
        if not row or row['language'] != lang or not approved_lexical_source(row.get('source'), context):
            problems.add('invalid_or_unapproved_example_link')
            continue
        ann = ref.get('annotation')
        if not isinstance(ann, dict) or any(not isinstance(ann.get(k), str) for k in ('span', 'feature')):
            problems.add('invalid_annotation')
            continue
        if ann['span'] not in row['text'] or ann['feature'] != f'{feature}={rule.get("feature_value", "")}' or not rule.get('feature_value'):
            problems.add('example_feature_contradiction')
        if not any(a.get('span') == ann['span'] and a.get('feature') == ann['feature'] and
                   a.get('explanation_ref') == rid for a in row.get('grammar_annotations', [])):
            problems.add('example_annotation_not_attested')
        for a in row.get('grammar_annotations', []):
            if (a.get('span') == ann['span'] and isinstance(a.get('feature'), str)
                    and a['feature'].split('=', 1)[0] == feature and a['feature'] != ann['feature']):
                problems.add('conflicting_example_annotations')
    review = rule.get('review') or {}
    editor = reviewers.get(review.get('reviewer_id'))
    if (review.get('decision') != 'approved' or review.get('rule_sha256') != rule_hash(rule)
        or not isinstance(review.get('decision_url'), str)
        or not review.get('decision_url', '').startswith('https://')
        or not editor or lang not in editor.get('languages', []) or editor.get('status') != 'approved'):
        problems.add('independent_editorial_review_missing')
    return sorted(problems)


def cycles(rules):
    marks, cyclic = {}, set()
    def visit(rid, stack):
        if marks.get(rid) == 2:
            return
        if marks.get(rid) == 1:
            cyclic.update(stack[stack.index(rid):])
            return
        marks[rid] = 1
        for dep in rules[rid].get('prerequisites', []):
            if dep in rules:
                visit(dep, stack + [dep])
        marks[rid] = 2
    for rid in sorted(rules):
        visit(rid, [rid])
    return cyclic


def read_jsonl(path, max_records=5000):
    result = []
    with Path(path).open('rb') as fh:
        for n, raw in enumerate(fh, 1):
            if n > max_records or len(raw) > MAX_ROW:
                raise ValueError('shard_budget_exceeded')
            if raw.strip():
                result.append(json.loads(raw.decode('utf-8')))
    return result


def build_report(rules, context, corpus, reviewers, shard=0, shards=1, backlog=None):
    if not (0 <= shard < shards <= 16):
        raise ValueError('invalid_shard')
    mapping = {}
    duplicates = set()
    for rule in rules:
        rid = rule.get('rule_id') if isinstance(rule, dict) else None
        if not isinstance(rid, str):
            raise ValueError('invalid_rule_record')
        if rid in mapping:
            duplicates.add(rid)
        mapping[rid] = rule
    graph_cycles = cycles(mapping)
    totals = {}
    detail = []
    for code in sorted(context['langs']):
        if int(hashlib.sha256(code.encode()).hexdigest(), 16) % shards != shard:
            continue
        records = [r for r in rules if r.get('language') == code]
        accepted, ex_ids, domains, gaps = [], set(), set(), Counter()
        for rule in sorted(records, key=lambda r: r['rule_id']):
            reasons = check_rule(rule, context, corpus, reviewers, mapping)
            if rule['rule_id'] in duplicates:
                reasons.append('duplicate_rule_identity')
            if rule['rule_id'] in graph_cycles:
                reasons.append('prerequisite_cycle')
            if reasons:
                for reason in set(reasons):
                    gaps[reason] += 1
            else:
                accepted.append(rule['rule_id'])
                domains.add(rule['domain'])
                ex_ids.update(r['example_id'] for r in rule['example_refs'])
        topics = None if backlog is None or code not in backlog else sorted(backlog[code])
        totals[code] = {'verified_rules': len(accepted), 'verified_examples': len(ex_ids),
            'verified_domains': len(domains), 'candidate_rules': len(records),
            'unknown_capabilities': sum(capability(context, code, c) == 'unknown' for c in context['features']),
            'topic_gap_status': 'NOT_ASSESSED' if topics is None else 'TRACKED',
            'missing_topics': None if topics is None else sorted(set(topics) - domains),
            'blocked_reasons': dict(sorted(gaps.items()))}
        detail.extend(accepted)
    status = ('BLOCKED' if any(x['blocked_reasons'] for x in totals.values())
              else 'APPROVED_RULES' if detail else 'EMPTY_NO_APPROVED_CONTENT')
    return {'schema_version': VERSION, 'status': status, 'shard': shard, 'shards': shards,
        'language_count': len(totals), 'languages': totals,
        'approved_rule_ids': sorted(detail), 'candidate_digest': digest(rules)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo-root', default='.')
    ap.add_argument('--rules', default='tools/factory_extensions/grammar_evidence/rules.jsonl')
    ap.add_argument('--lexical', default=None, help='Externally admitted canonical lexical 1.0 snapshot')
    ap.add_argument('--forms', default=None, help='Externally admitted morphology JSONL snapshot')
    ap.add_argument('--reviewers', default=None, help='Independently governed reviewer roster')
    ap.add_argument('--shard', type=int, default=0)
    ap.add_argument('--shards', type=int, default=1)
    args = ap.parse_args()
    context = snapshot(args.repo_root)
    rules = read_jsonl(args.repo_root + '/' + args.rules)
    if args.lexical and args.forms:
        corpus = collect_evidence(load(args.lexical), read_jsonl(args.forms))
    else:
        corpus = collect_evidence({'contract_version': VERSION, 'lexemes': [], 'senses': [], 'examples': []}, [])
    roster = load(args.reviewers) if args.reviewers else {'reviewers': []}
    reviewers = {r['id']: r for r in roster['reviewers']}
    topic_file = Path(args.repo_root) / 'tools/factory_extensions/grammar_evidence/topic_backlog.v1.json'
    topics = load(topic_file)
    if topics.get('schema_version') != VERSION or not isinstance(topics.get('languages'), dict):
        raise ValueError('invalid_topic_backlog')
    for code, items in topics['languages'].items():
        if code not in context['langs'] or not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            raise ValueError('unregistered_or_invalid_topic')
    result = build_report(rules, context, corpus, reviewers, args.shard, args.shards, topics['languages'])
    print(canonical(result))
    return 1 if result['status'] == 'BLOCKED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
