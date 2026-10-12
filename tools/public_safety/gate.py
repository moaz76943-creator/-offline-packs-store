#!/usr/bin/env python3
"""Fail-closed staged Git publication scanner. Python stdlib only, no network.

This is a local CLI, not a replacement for mandatory branch protection. It
reads *only Git's index blobs*, not untracked/private working-tree files.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

EXPECTED_REMOTE = 'github.com/moaz76943-creator/-offline-packs-store'
MAX_BLOB = 12 * 1024 * 1024
MAX_EXPANDED = 24 * 1024 * 1024
MAX_MEMBERS = 512
MAX_STAGED = 350
TEXT_SUFFIXES = {'.md', '.txt', '.json', '.jsonl', '.yml', '.yaml', '.toml',
                 '.csv', '.tsv', '.py', '.html', '.css', '.xml', '.svg'}
MEDIA_SUFFIXES = {'.webp', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ogg',
                  '.mp3', '.opus', '.wav', '.woff2'}
LICENSES = {'CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'MIT',
            'Apache-2.0', 'OFL-1.1', 'Public-Domain'}
FORBIDDEN_SUFFIXES = {'.env', '.key', '.pem', '.p12', '.pfx', '.jks',
                      '.keystore', '.crt', '.cer', '.der', '.p8', '.mobileprovision',
                      '.db', '.sqlite', '.sqlite3', '.db3', '.bak', '.log', '.dmp',
                      '.core', '.bin', '.apk', '.aab', '.ipa', '.class', '.dex',
                      '.so', '.dylib', '.exe', '.dll', '.zip.bak'}
SENSITIVE_NAMES = re.compile(r'(?i)(^|[./_-])(secret|credentials?|passwords?|'
                             r'signing|keystore|sqlcipher|private[_-]?key|'
                             r'learner[_-]?progress|user[_-]?data|debug[_-]?db)($|[./_-])')
PRIVATE_PATHS = re.compile(r'(?i)(?:^|[\\/])(?:lib/(?:services|screens|models)/|'
                           r'android/app/|ios/Runner/|\.gradle/|\.idea/|'
                           r'\.git/|private/|internal/|userdata/|secrets?/|'
                           r'home/[^/]+/|Users/[^/]+/)')
SECRET_PATTERNS = (
    ('CREDENTIAL_PATTERN', re.compile(rb'(?i)(?:gh[pousr]_[A-Za-z0-9_]{30,}|'
        rb'github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|'
        rb'xox[baprs]-[A-Za-z0-9-]{15,}|AIza[0-9A-Za-z_-]{30,}|'
        rb'sk-[A-Za-z0-9_-]{24,})')),
    ('PRIVATE_KEY_BLOCK', re.compile(rb'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----')),
    ('SECRET_ASSIGNMENT', re.compile(rb'(?im)(?:password|passwd|access_token|'
        rb'client_secret|api[_-]?key|auth[_-]?token|sqlcipher[_-]?key)'
        rb'\s*[=:]\s*[\x22\x27]?[^\s\x22\x27,;}]{8,}')),
    ('PERSONAL_EMAIL', re.compile(rb'(?i)\b[A-Za-z0-9._%+-]+@'
        rb'[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')),
    ('PERSONAL_PHONE', re.compile(rb'(?i)(?:phone|mobile|tel(?:ephone)?)'
        rb'\s*[=:]\s*[\x22\x27]?\+?[0-9 ()-]{10,}')),
)
RESTRICTED_DATA_KEYS = {'user_id', 'device_id', 'email', 'phone', 'address',
                        'learner_progress', 'review_history', 'next_review_epoch',
                        'srs_ledger', 'session_token', 'auth_token',
                        'sqlcipher_key', 'private_notes', 'telemetry'}


def short_hash(value):
    if isinstance(value, str):
        value = value.encode('utf-8', 'surrogateescape')
    return hashlib.sha256(value).hexdigest()[:16]


def git(root, *args):
    """Never relay stderr, which may contain sensitive paths or values."""
    try:
        return subprocess.run(['git', *args], cwd=root, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=30).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('GIT_UNAVAILABLE') from None


def allowed_path(name):
    if name in {'manifest.json', 'version.json', 'README.md', 'LICENSE',
                'NOTICE', 'ATTRIBUTION.md'}:
        return True
    parts = PurePosixPath(name).parts
    if not parts:
        return False
    root = parts[0]
    suffix = PurePosixPath(name).suffix.lower()
    if root == 'tools' and len(parts) >= 3 and parts[1] == 'public_safety':
        return suffix in TEXT_SUFFIXES or name.endswith('/LICENSE')
    if root in {'docs', 'catalog', 'standards', 'legal'}:
        return len(parts) >= 2 and suffix in TEXT_SUFFIXES
    if root in {'images', 'media'}:
        return len(parts) >= 2 and suffix in MEDIA_SUFFIXES
    if root == 'packs':
        return len(parts) == 2 and name.endswith('.pack.gz')
    return False


def path_violation(name):
    if not isinstance(name, str) or not name or '\x00' in name or '\\' in name:
        return 'UNSAFE_PATH'
    if name.startswith('/') or ':' in name or any(p in {'.', '..', ''} for p in name.split('/')):
        return 'UNSAFE_PATH'
    p = PurePosixPath(name)
    low = p.name.lower()
    if p.suffix.lower() in FORBIDDEN_SUFFIXES or low.endswith(('.db-wal', '.db-shm', '.sqlite-wal', '.sqlite-shm')):
        return 'FORBIDDEN_FILETYPE'
    if low.startswith(('.env', 'id_rsa', 'id_ed25519')) or SENSITIVE_NAMES.search(name):
        return 'FORBIDDEN_PATH'
    if PRIVATE_PATHS.search('/' + name):
        return 'PRIVATE_PATH'
    if not allowed_path(name):
        return 'UNAPPROVED_EXPORT_PATH'
    return None


def safe_internal_path(name):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        return False
    if name.startswith('/') or ':' in name or any(p in {'', '.', '..'} for p in name.split('/')):
        return False
    if any(part.lower().startswith('.env') for part in name.split('/')):
        return False
    if PurePosixPath(name).suffix.lower() in FORBIDDEN_SUFFIXES:
        return False
    if SENSITIVE_NAMES.search(name) or PRIVATE_PATHS.search('/' + name):
        return False
    return True


@dataclass
class Finding:
    rule: str
    handle: str
    severity: str = 'FAIL'
    fingerprint: str = ''


@dataclass
class ScanResult:
    files_checked: int = 0
    findings: list = field(default_factory=list)

    @property
    def state(self):
        if any(f.severity == 'FAIL' for f in self.findings):
            return 'FAIL'
        if self.findings:
            return 'BLOCKED'
        return 'PASS'

    def public_report(self):
        # No content, filenames, tokens, exceptions, URLs or source code.
        records = ', '.join(f'{f.rule}:{f.handle}' for f in self.findings[:20])
        if len(self.findings) > 20:
            records += ', ADDITIONAL_FINDINGS'
        return f'{self.state} files={self.files_checked} findings={len(self.findings)}' + (f' rules={records}' if records else '')


class PublicationGate:
    def __init__(self, root, *, check_history=False, evidence_dir=None):
        self.root = Path(root).resolve()
        self.check_history = check_history
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        self.result = ScanResult()
        self.provenance = None
        self.manifest = None

    def issue(self, rule, path='', severity='FAIL', blob=b''):
        handle = short_hash(path)
        self.result.findings.append(Finding(rule, handle, severity,
                                            short_hash(blob if blob else path + rule)))

    def blob_at_index_or_head(self, path):
        try:
            return git(self.root, 'show', ':' + path)
        except RuntimeError:
            try:
                return git(self.root, 'show', 'HEAD:' + path)
            except RuntimeError:
                return None

    def load_contracts(self):
        for path, attr in (('tools/public_safety/provenance.json', 'provenance'),
                           ('manifest.json', 'manifest')):
            data = self.blob_at_index_or_head(path)
            if data is not None:
                try:
                    value = json.loads(data.decode('utf-8'))
                    if not isinstance(value, dict):
                        raise ValueError()
                    setattr(self, attr, value)
                except (ValueError, UnicodeError):
                    self.issue('INVALID_CONTRACT', path)

    def check_provenance(self, path, data):
        exports = (self.provenance or {}).get('exports', {})
        item = exports.get(path) if isinstance(exports, dict) else None
        if not isinstance(item, dict):
            self.issue('MISSING_PROVENANCE', path, 'BLOCKED')
            return
        digest = hashlib.sha256(data).hexdigest()
        if item.get('sha256') != digest:
            self.issue('PROVENANCE_HASH_MISMATCH', path)
        if item.get('license') not in LICENSES or not all(
                isinstance(item.get(k), str) and item[k].strip()
                for k in ('source', 'rights_holder', 'attribution')):
            self.issue('LICENSE_EVIDENCE_INCOMPLETE', path, 'BLOCKED')
        if path.startswith('packs/'):
            languages = (self.manifest or {}).get('languages', [])
            matching = [x for x in languages if isinstance(x, dict) and
                        x.get('pack_file') == PurePosixPath(path).name] if isinstance(languages, list) else []
            if len(matching) != 1 or matching[0].get('sha256') != digest:
                self.issue('MANIFEST_INTEGRITY_MISMATCH', path)

    def check_text(self, path, data, json_payload=False):
        # Never decode into a diagnostic message.
        for rule, rx in SECRET_PATTERNS:
            if rx.search(data):
                self.issue(rule, path, blob=data)
        if not path.startswith('tools/public_safety/') and re.search(rb'(?i)(?:^|[\s\x22\x27])(?:lib/services/|'
                     rb'android/app/|ios/Runner/|/home/[^/\s]+/|'
                     rb'[A-Za-z]:\\Users\\|\.git/objects/)', data):
            # Source tests use composed fixtures, avoiding any embedded private path.
            self.issue('PRIVATE_SOURCE_REFERENCE', path)
        if json_payload:
            try:
                doc = json.loads(data)
            except (ValueError, UnicodeError):
                self.issue('INVALID_PUBLIC_JSON', path)
                return
            def inspect(item, depth=0):
                if depth > 20:
                    self.issue('JSON_TOO_DEEP', path, 'BLOCKED')
                    return
                if isinstance(item, dict):
                    for key, value in item.items():
                        if isinstance(key, str) and key.lower() in RESTRICTED_DATA_KEYS:
                            self.issue('RESTRICTED_USER_DATA', path)
                        inspect(value, depth + 1)
                elif isinstance(item, list):
                    for value in item:
                        inspect(value, depth + 1)
            inspect(doc)

    def check_archive(self, path, data, depth=0):
        if depth > 2:
            self.issue('ARCHIVE_NESTING_LIMIT', path, 'BLOCKED')
            return
        if data[:2] == b'PK':
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    members = archive.infolist()
                    if len(members) > MAX_MEMBERS:
                        self.issue('ARCHIVE_MEMBER_LIMIT', path, 'BLOCKED')
                        return
                    count = 0
                    for member in members:
                        inside = member.filename.rstrip('/')
                        if not safe_internal_path(inside):
                            self.issue('UNSAFE_ARCHIVE_MEMBER', path)
                            continue
                        if member.is_dir():
                            continue
                        if (member.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
                            self.issue('ARCHIVE_SYMLINK', path)
                            continue
                        if member.file_size > MAX_EXPANDED or count + member.file_size > MAX_EXPANDED:
                            self.issue('ARCHIVE_EXPANSION_LIMIT', path, 'BLOCKED')
                            return
                        payload = archive.read(member, pwd=None)
                        count += len(payload)
                        self.check_payload(path, payload, inside, depth + 1)
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
                self.issue('INVALID_ARCHIVE', path, 'BLOCKED')
            return
        # Detect gzipped content, including disallowed disguised archives.
        if data[:2] == b'\x1f\x8b':
            try:
                dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
                payload = dec.decompress(data, MAX_EXPANDED + 1)
                if len(payload) > MAX_EXPANDED or dec.unconsumed_tail or not dec.eof or dec.unused_data:
                    self.issue('ARCHIVE_EXPANSION_LIMIT', path, 'BLOCKED')
                    return
            except zlib.error:
                self.issue('INVALID_ARCHIVE', path, 'BLOCKED')
                return
            self.check_payload(path, payload, PurePosixPath(path).name[:-3], depth + 1)
            return
        if len(data) > 262 and data[257:262] == b'ustar':
            try:
                with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
                    members = archive.getmembers()
                    if len(members) > MAX_MEMBERS:
                        self.issue('ARCHIVE_MEMBER_LIMIT', path, 'BLOCKED')
                        return
                    total = 0
                    for member in members:
                        inside = member.name.rstrip('/')
                        if not safe_internal_path(inside) or not (member.isfile() or member.isdir()):
                            self.issue('UNSAFE_ARCHIVE_MEMBER', path)
                            continue
                        if member.isdir():
                            continue
                        total += member.size
                        if total > MAX_EXPANDED:
                            self.issue('ARCHIVE_EXPANSION_LIMIT', path, 'BLOCKED')
                            return
                        payload = archive.extractfile(member).read()
                        self.check_payload(path, payload, inside, depth + 1)
            except (OSError, ValueError, tarfile.TarError):
                self.issue('INVALID_ARCHIVE', path, 'BLOCKED')
            return
        # Only packs must be gzip; other binary types require provenance.
        if path.endswith('.pack.gz'):
            self.issue('INVALID_PACK_COMPRESSION', path)

    def check_payload(self, path, data, member, depth):
        if not safe_internal_path(member):
            self.issue('UNSAFE_ARCHIVE_MEMBER', path)
            return
        if data.startswith((b'PK', b'\x1f\x8b')) or (len(data) > 262 and data[257:262] == b'ustar'):
            self.check_archive(path, data, depth)
            return
        suffix = PurePosixPath(member).suffix.lower()
        if suffix in TEXT_SUFFIXES or path.endswith('.pack.gz'):
            if b'\x00' in data:
                self.issue('BINARY_CONTENT_DISGUISE', path)
                return
            try:
                data.decode('utf-8')
            except UnicodeError:
                self.issue('INVALID_TEXT_ENCODING', path, 'BLOCKED')
                return
            self.check_text(path, data, json_payload=(suffix in {'.json', '.jsonl'} or path.endswith('.pack.gz')))
        else:
            # Arbitrary opaque files inside an archive must be treated as restricted.
            self.issue('UNAPPROVED_ARCHIVE_PAYLOAD', path, 'BLOCKED')

    def check_one(self, path):
        bad = path_violation(path)
        if bad:
            self.issue(bad, path)
            return
        try:
            mode = git(self.root, 'ls-files', '--stage', '--', path).split(None, 1)[0]
            if mode != b'100644' and mode != b'100755':
                self.issue('UNSAFE_GIT_OBJECT_MODE', path)
                return
            data = git(self.root, 'show', ':' + path)
        except (RuntimeError, IndexError):
            self.issue('INDEX_BLOB_UNAVAILABLE', path, 'BLOCKED')
            return
        self.result.files_checked += 1
        if len(data) > MAX_BLOB:
            self.issue('STAGED_BLOB_TOO_LARGE', path, 'BLOCKED')
            return
        suffix = PurePosixPath(path).suffix.lower()
        if (suffix in TEXT_SUFFIXES and not (path.startswith('images/') or path.startswith('media/'))) or path in {'LICENSE', 'NOTICE'}:
            if b'\x00' in data:
                self.issue('BINARY_CONTENT_DISGUISE', path)
                return
            try:
                data.decode('utf-8')
            except UnicodeError:
                self.issue('INVALID_TEXT_ENCODING', path, 'BLOCKED')
                return
            self.check_text(path, data, json_payload=(suffix in {'.json', '.jsonl'}))
        elif path.endswith('.pack.gz'):
            self.check_provenance(path, data)
            if not data.startswith(b'\x1f\x8b'):
                self.issue('INVALID_PACK_COMPRESSION', path)
            else:
                self.check_archive(path, data)
        elif suffix in MEDIA_SUFFIXES:
            self.check_provenance(path, data)
            if suffix == '.svg':
                self.check_text(path, data)
            # Archives disguised as media are rejected.
            if data.startswith((b'PK', b'\x1f\x8b')):
                self.issue('ARCHIVE_DISGUISED_AS_MEDIA', path)
        else:
            self.issue('UNKNOWN_FILE_FORMAT', path)

    def check_history_names(self):
        # Metadata only; never read or reproduce historical blob contents.
        try:
            names = git(self.root, 'log', '--all', '--name-only', '-z',
                        '--format=', '--no-renames').split(b'\x00')
        except RuntimeError:
            self.issue('HISTORY_UNAVAILABLE', severity='BLOCKED')
            return
        seen = set()
        for raw in names:
            name = raw.decode('utf-8', 'surrogateescape').strip('\n')
            if not name or name in seen:
                continue
            seen.add(name)
            if path_violation(name) in {'FORBIDDEN_FILETYPE', 'FORBIDDEN_PATH', 'PRIVATE_PATH'}:
                self.issue('HISTORY_REVIEW', name, 'FAIL')

    def save_evidence(self):
        if not self.result.findings or not self.evidence_dir:
            return
        # Location MUST be under .git, not in a trackable repository path.
        git_dir = Path(git(self.root, 'rev-parse', '--absolute-git-dir').decode().strip()).resolve()
        destination = self.evidence_dir.resolve()
        if destination != git_dir and git_dir not in destination.parents:
            self.issue('EVIDENCE_STORAGE_UNSAFE', severity='BLOCKED')
            return
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        records = [{'rule': f.rule, 'path_sha256_short': f.handle,
                    'fingerprint_sha256_short': f.fingerprint, 'severity': f.severity}
                   for f in self.result.findings]
        payload = {'generated_utc': datetime.now(timezone.utc).isoformat(),
                   'state': self.result.state, 'findings': records,
                   'guidance': 'Review locally; revoke exposed credentials, notify owners and coordinate any historical cleanup. Never paste sensitive values in issues or logs.'}
        target = destination / ('report_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.json')
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, indent=2)

    def scan(self):
        try:
            toplevel = Path(git(self.root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
            if toplevel != self.root:
                self.issue('UNEXPECTED_REPO_ROOT', severity='BLOCKED')
                return self.result
            origin = git(self.root, 'remote', 'get-url', 'origin').decode().strip()
            remote = re.sub(r'^(?:https?://|ssh://git@|git@)', '', origin)
            remote = remote.replace(':', '/', 1).removesuffix('.git').strip('/')
            if remote != EXPECTED_REMOTE:
                self.issue('WRONG_PUBLIC_REPOSITORY', severity='BLOCKED')
                return self.result
            staged = git(self.root, 'diff', '--cached', '--name-status', '--no-renames', '-z').split(b'\x00')
        except (RuntimeError, UnicodeError):
            self.issue('GIT_CONTEXT_UNAVAILABLE', severity='BLOCKED')
            return self.result
        changes = []
        for i in range(0, len(staged) - 1, 2):
            flag = staged[i].decode('ascii', 'replace')
            name = staged[i + 1].decode('utf-8', 'surrogateescape')
            changes.append((flag, name))
        if not changes:
            self.issue('NO_STAGED_CHANGES', severity='BLOCKED')
            return self.result
        if len(changes) > MAX_STAGED:
            self.issue('STAGED_FILE_LIMIT', severity='BLOCKED')
            return self.result
        self.load_contracts()
        for status, path in changes:
            if status == 'D':
                # A deletion is not secret content, but deletions of contracts must be rejected.
                if path in {'tools/public_safety/provenance.json', 'manifest.json'}:
                    self.issue('REQUIRED_CONTRACT_REMOVED', path)
                continue
            if status not in {'A', 'M', 'T'}:
                self.issue('UNKNOWN_INDEX_CHANGE', path, 'BLOCKED')
                continue
            self.check_one(path)
        if self.check_history:
            self.check_history_names()
        if self.evidence_dir:
            try:
                self.save_evidence()
            except (OSError, RuntimeError):
                self.issue('EVIDENCE_WRITE_FAILED', severity='BLOCKED')
        return self.result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fail-closed public repository staged-content security gate')
    parser.add_argument('--repo', default='.', help='public git checkout root')
    parser.add_argument('--history', action='store_true', help='metadata-only historic path review')
    parser.add_argument('--save-private-evidence', action='store_true',
                        help='write redacted evidence to .git/public_safety_evidence')
    args = parser.parse_args(argv)
    root = Path(args.repo).resolve()
    evidence = root / '.git' / 'public_safety_evidence' if args.save_private_evidence else None
    try:
        result = PublicationGate(root, check_history=args.history, evidence_dir=evidence).scan()
    except Exception:
        print('BLOCKED files=0 findings=1 rules=INTERNAL_SCANNER_ERROR')
        return 2
    print(result.public_report())
    if result.state != 'PASS':
        print('Remediation: inspect privately; rotate/revoke any exposed credential. If already published, coordinate Git history cleanup manually after revocation. No history rewrite is performed.')
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[result.state]


if __name__ == '__main__':
    sys.exit(main())
