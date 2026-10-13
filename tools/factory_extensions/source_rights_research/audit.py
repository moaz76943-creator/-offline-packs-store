#!/usr/bin/env python3
"""Read-only legal research triage. NEVER writes to legal/ledger or approves a source."""
import argparse
import hashlib
import ipaddress
import json
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[3]
REGISTRY = Path(__file__).with_name('candidates.json')
CATALOG = REPO / 'catalog/language_registry.v1.json'
LEDGER = REPO / 'legal/ledger/sources.json'
KIND = frozenset({'dictionary', 'morphology', 'grammar', 'sentences', 'pronunciation', 'metadata'})
ID = re.compile(r'^[a-z][a-z0-9-]{1,79}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
MAX_JSON = 300_000
MAX_EVIDENCE = 256_000
MAX_CAPTURE = 1_024_000
ALLOW_HOSTS = frozenset({
    'kaikki.org', 'en.wiktionary.org', 'www.wikidata.org', 'unimorph.github.io',
    'github.com', 'tatoeba.org', 'panlex.org', 'dev.panlex.org',
    'commonvoice.mozilla.org', 'cldr.unicode.org', 'www.unicode.org'
})
REQUIRED = frozenset({
    'candidate_id', 'kind', 'publisher', 'source_url', 'dataset_version',
    'acquisition_date', 'dataset_sha256', 'dataset_artifact_path', 'source_license_claim',
    'extraction_tool_license_claim', 'individual_record_rights',
    'audio_rights', 'commercial_redistribution', 'rights_risks', 'obligations',
    'evidence', 'confirmed_language_ids', 'coverage_note', 'copyright_notices',
    'authors', 'modification_history', 'human_review'
})


def unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key: ' + key)
        out[key] = value
    return out


def load(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON:
        raise ValueError('JSON size limit')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def valid_url(value):
    if not isinstance(value, str) or len(value) > 400:
        return False
    try:
        u = urlsplit(value)
        if (u.scheme != 'https' or u.hostname not in ALLOW_HOSTS or
                u.username or u.password or u.port not in (None, 443) or u.fragment):
            return False
        if not u.path.startswith('/') or '\\' in value or any(ord(c) < 32 for c in value):
            return False
        if u.hostname.replace('.', '').isdigit():
            return False
        if u.query and any(key in u.query.lower() for key in ('token=', 'key=', 'secret=', 'auth=')):
            return False
        return True
    except (ValueError, TypeError):
        return False


def is_sha(s):
    return isinstance(s, str) and SHA.fullmatch(s) is not None


def is_date(s):
    if not isinstance(s, str):
        return False
    try:
        return date.fromisoformat(s).isoformat() == s
    except ValueError:
        return False


def pinned_local_sha(relative, expected, max_bytes=64_000_000):
    """Verify real immutable local bytes only; no symlinks, path escapes or huge reads."""
    if not isinstance(relative, str) or not relative or not is_sha(expected):
        return False
    candidate = Path(relative)
    if candidate.is_absolute() or '..' in candidate.parts or '.git' in candidate.parts:
        return False
    root = REPO.resolve()
    path = (root / candidate).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        return False
    if path.stat().st_size > max_bytes:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest() == expected


def warnings(candidate):
    notes = ' '.join(str(candidate.get(x, '')) for x in (
        'source_license_claim', 'individual_record_rights', 'audio_rights',
        'extraction_tool_license_claim'))
    flags = set()
    if re.search(r'(^|[^A-Z])(?:NC|NONCOMMERCIAL|NON-COMMERCIAL)(?:[^A-Z]|$)', notes.upper()):
        flags.add('NONCOMMERCIAL_REQUIRES_REJECTION_OR_WRITTEN_EXCEPTION')
    if re.search(r'BY-SA|SHAREALIKE|GFDL', notes, re.I):
        flags.add('SHAREALIKE_AND_ATTRIBUTION_REVIEW')
    if re.search(r'\bOR\b|DUAL|MIXED|PER_RECORD|PER_CONTRIBUTOR', notes, re.I):
        flags.add('MULTI_LICENSE_OR_RECORD_RIGHTS_REVIEW')
    if re.search(r'UNCONFIRMED|UNVERIFIED|NOT_VERIFIED|MISSING|UNKNOWN|NOT_APPLICABLE', notes, re.I):
        flags.add('RIGHTS_SCOPE_INCOMPLETE')
    if candidate.get('kind') == 'pronunciation':
        flags.add('AUDIO_AND_SPEAKER_RIGHTS_REVIEW')
    if candidate.get('candidate_id') == 'panlex':
        flags.add('PANLEX_CONFLICTING_ORIGINAL_SOURCE_RIGHTS')
    return sorted(flags)


def audit(catalog, registry, ledger):
    """Deterministic inventory, coverage and human queue. Approval is not expressible here."""
    if not isinstance(catalog, dict) or catalog.get('schema_version') != '1.0.0':
        raise ValueError('unrecognized canonical catalog')
    langs = catalog.get('languages')
    if not isinstance(langs, list) or len(langs) != 100:
        raise ValueError('expected exactly 100 canonical languages')
    ids = [x.get('id') for x in langs if isinstance(x, dict)]
    if len(ids) != 100 or len(set(ids)) != 100 or any(not isinstance(x, str) for x in ids):
        raise ValueError('duplicate/noncanonical language identities')
    if (not isinstance(ledger, dict) or ledger.get('schema_version') != '1.0.0'
            or not isinstance(ledger.get('sources'), list)):
        raise ValueError('Route05 ledger invalid')
    if (not isinstance(registry, dict) or registry.get('schema_version') != 'research.v1'
            or registry.get('policy') != 'RESEARCH_ONLY_NEVER_ADMIT'
            or registry.get('approved_sources') != []
            or not is_date(registry.get('as_of'))
            or not isinstance(registry.get('candidates'), list)
            or not 1 <= len(registry['candidates']) <= 100):
        raise ValueError('candidate registry cannot approve sources')

    known, queue, coverage = set(), [], {k: [] for k in ids}
    approved_ledger = {s.get('source_id') for s in ledger['sources'] if isinstance(s, dict)
                       and s.get('status') == 'APPROVED_FOR_REDISTRIBUTION'}
    for c in registry['candidates']:
        if not isinstance(c, dict) or set(c) != REQUIRED:
            raise ValueError('invalid candidate fields')
        cid = c['candidate_id']
        if not isinstance(cid, str) or not ID.fullmatch(cid) or cid in known:
            raise ValueError('duplicate/invalid candidate ID')
        known.add(cid)
        if c['kind'] not in KIND or not isinstance(c['publisher'], str) or not c['publisher'].strip():
            raise ValueError('missing publisher/kind')
        if not valid_url(c['source_url']):
            raise ValueError('untrusted source URL')
        if c['human_review'] != {'status': 'REVIEW_REQUIRED', 'reviewer': None,
                                'decision_url': None, 'decision_date': None}:
            raise ValueError('candidate review cannot auto-approve')
        if c['commercial_redistribution'] != 'NOT_AUTHORIZED':
            raise ValueError('candidate cannot grant redistribution')
        if c['dataset_version'] is not None and (not isinstance(c['dataset_version'], str) or not c['dataset_version']):
            raise ValueError('invalid version')
        if c['dataset_sha256'] is not None and not is_sha(c['dataset_sha256']):
            raise ValueError('invalid dataset digest')
        if c['acquisition_date'] is not None and not is_date(c['acquisition_date']):
            raise ValueError('invalid acquisition date')
        if (c['dataset_sha256'] is None) != (c['dataset_artifact_path'] is None):
            raise ValueError('source artifact path/hash pair required')
        if any(not isinstance(c[x], str) or not c[x].strip() for x in (
                'source_license_claim', 'extraction_tool_license_claim',
                'individual_record_rights', 'audio_rights', 'coverage_note')):
            raise ValueError('missing distinct rights scope')
        if not isinstance(c['evidence'], list) or not c['evidence'] or len(c['evidence']) > 8:
            raise ValueError('missing official evidence')
        for e in c['evidence']:
            if not isinstance(e, dict) or set(e) != {
                    'url', 'kind', 'snapshot_sha256', 'snapshot_path', 'reviewed_at'}:
                raise ValueError('invalid evidence metadata')
            if not valid_url(e['url']) or e['kind'] != 'PUBLISHER_OR_PROJECT_STATEMENT':
                raise ValueError('untrusted licensing evidence URL')
            if e['snapshot_sha256'] is not None and not is_sha(e['snapshot_sha256']):
                raise ValueError('invalid evidence SHA')
            if (e['snapshot_sha256'] is None) != (e['snapshot_path'] is None):
                raise ValueError('evidence path/hash pair required')
            if e['reviewed_at'] is not None and not is_date(e['reviewed_at']):
                raise ValueError('invalid review date')
        for key in ('authors', 'copyright_notices', 'modification_history', 'rights_risks', 'obligations'):
            if not isinstance(c[key], list) or len(c[key]) > 100 or any(not isinstance(v, str) for v in c[key]):
                raise ValueError('invalid authors/notices/history')
        matched = c['confirmed_language_ids']
        if not isinstance(matched, list) or len(matched) != len(set(matched)) or any(x not in coverage for x in matched):
            raise ValueError('unverified language mapping')
        for lang in matched:
            coverage[lang].append(cid)
        blocks = []
        if cid in approved_ledger:
            blocks.append('EXISTING_LEDGER_ID_COLLISION_CHECK_REQUIRED')
        if c['dataset_version'] is None:
            blocks.append('MISSING_EXACT_DATASET_VERSION')
        if (c['acquisition_date'] is None or c['dataset_sha256'] is None or
                not pinned_local_sha(c['dataset_artifact_path'], c['dataset_sha256'])):
            blocks.append('MISSING_OR_UNVERIFIED_DOWNLOADED_BYTES_AND_SHA256')
        if any(e['snapshot_sha256'] is None or not
               pinned_local_sha(e['snapshot_path'], e['snapshot_sha256'], MAX_EVIDENCE)
               for e in c['evidence']):
            blocks.append('MISSING_OR_UNVERIFIED_IMMUTABLE_LICENSE_PROOF_SNAPSHOT')
        if not c['copyright_notices']:
            blocks.append('ORIGINAL_COPYRIGHT_NOTICES_NOT_CAPTURED')
        blocks.extend(warnings(c))
        blocks.append('MISSING_AUTHORIZED_HUMAN_REDISTRIBUTION_DECISION')
        queue.append({'candidate_id': cid, 'kind': c['kind'], 'state': 'REVIEW_REQUIRED',
                      'commercial_redistribution_allowed': False,
                      'blockers': sorted(set(blocks)), 'official_evidence_urls':
                      [e['url'] for e in c['evidence']]})
    per_language = []
    for l in langs:
        cid = l['id']
        per_language.append({
            'language_id': cid, 'language_name': l.get('display_names', {}).get('en', cid),
            'mapped_research_candidates': sorted(coverage[cid]),
            'source_bytes_verified': 0, 'redistribution_approved_sources': 0,
            'resource_scarcity': 'NOT_MEASURED',
            'research_gap': 'NO_PER_LANGUAGE_CANDIDATE_EVIDENCE' if not coverage[cid]
                            else 'CANDIDATE_MAPPED_BUT_NO_ADMITTED_BYTES'
        })
    return {'schema_version': 'research.report.v1', 'canonical_language_count': len(per_language),
            'approved_by_this_tool': 0, 'route05_approved_existing_count': len(approved_ledger),
            'research_candidate_count': len(known), 'human_approval_queue': queue,
            'language_coverage': per_language,
            'note': 'Research gaps are NOT objective under-resourced-language rankings.'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect blocked for licensing evidence')


def capture_public_evidence(registry, output, opener=None):
    """Optional bounded official-page snapshot hashes. Never approves or imports data."""
    opener = opener or urllib.request.build_opener(NoRedirect())
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    findings = []
    total = 0
    for c in registry['candidates']:
        for idx, evidence in enumerate(c['evidence']):
            url = evidence['url']
            if not valid_url(url):
                raise ValueError('untrusted external evidence')
            req = urllib.request.Request(url, headers={'User-Agent': 'DEUTSCH-source-rights-audit/1.0',
                                                      'Accept': 'text/html,text/plain'})
            try:
                with opener.open(req, timeout=8) as response:
                    if response.geturl() != url:
                        raise ValueError('changed evidence URL')
                    media = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                    if media not in ('text/html', 'text/plain'):
                        raise ValueError('unexpected evidence content type')
                    raw = response.read(MAX_EVIDENCE + 1)
                    if len(raw) > MAX_EVIDENCE or total + len(raw) > MAX_CAPTURE:
                        raise ValueError('evidence byte budget exceeded')
                    total += len(raw)
                    sha = hashlib.sha256(raw).hexdigest()
                    dest = output / (c['candidate_id'] + '-' + str(idx) + '.html')
                    dest.write_bytes(raw)
                    findings.append({'candidate_id': c['candidate_id'], 'url': url,
                                     'sha256': sha, 'bytes': len(raw), 'status': 'SNAPSHOT_ONLY'})
            except (OSError, ValueError, urllib.error.URLError) as err:
                findings.append({'candidate_id': c['candidate_id'], 'url': url,
                                 'status': 'UNAVAILABLE', 'error_type': type(err).__name__})
    (output / 'evidence_snapshot_report.json').write_text(
        json.dumps(findings, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    return findings


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--capture-public-evidence', action='store_true')
    opts = p.parse_args(argv)
    report = audit(load(CATALOG), load(REGISTRY), load(LEDGER))
    report['canonical_registry_sha256'] = hashlib.sha256(CATALOG.read_bytes()).hexdigest()
    opts.out.mkdir(parents=True, exist_ok=True)
    (opts.out / 'rights_audit.json').write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8')
    if opts.capture_public_evidence:
        capture_public_evidence(load(REGISTRY), opts.out / 'evidence_snapshots')
    print(json.dumps({'research_candidates': report['research_candidate_count'],
                      'languages': report['canonical_language_count'],
                      'approved_by_research': 0, 'human_review_items':
                      len(report['human_approval_queue'])}, sort_keys=True))


if __name__ == '__main__':
    main()
