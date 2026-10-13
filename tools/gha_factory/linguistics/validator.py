"""GHA-04 independent, read-only morphology QA; never approves or publishes sources.

Canonical input is standards/morphology/form.schema.json (v1). Source rights,
lexeme joins, and proficiency assignments remain upstream responsibilities.
All inspections retain Unicode and bound memory with streaming + disk SQLite.
"""
import hashlib
import json
import re
import sqlite3
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

FIELDS = frozenset(('language_code','lemma_id','sense_id','lemma','form','features',
                    'root','pattern','processes','components','morphemes',
                    'vowel_harmony_class','segmentation','script',
                    'orthographic_variant','source_id','evidence_version'))
REQUIRED = frozenset(('language_code','lemma_id','sense_id','lemma','form',
                      'features','source_id','evidence_version'))
PERSON = frozenset(('first','second','third'))
GERMAN_NUMBER = frozenset(('singular','plural'))
GERMAN_CASE = frozenset(('nominative','accusative','dative','genitive'))
GERMAN_GENDER = frozenset(('masculine','feminine','neuter'))
MORPHEME_FIELDS = frozenset(('surface','kind','position','allomorph'))
MORPHEME_KINDS = frozenset(('root','prefix','suffix','infix','clitic','stem','pattern','compound_member'))
SHA = re.compile(r'^[0-9a-f]{64}$')


class LinguisticError(ValueError):
    """Invalid attestation or unverifiable morphological structure."""


def _text(v, name):
    if not isinstance(v, str) or not v.strip() or any(
            unicodedata.category(ch) in ('Cc','Cs') for ch in v):
        raise LinguisticError('invalid Unicode text: '+name)


def validate_form(record, registered_languages, *, pos=None):
    """Validate a single canonical attestation; do NOT infer missing forms.

    Optional pos is independently linked lexical metadata, not guessed from text.
    """
    if not isinstance(record, dict) or not REQUIRED <= record.keys() or record.keys() - FIELDS:
        raise LinguisticError('noncanonical morphology form schema')
    lang=record['language_code']
    if not isinstance(lang,str) or lang not in registered_languages:
        raise LinguisticError('unregistered language identity')
    for key in REQUIRED - {'features'}:
        _text(record[key],key)
    if not record['lemma_id'].startswith(lang+':') or not record['sense_id'].startswith(lang+':'):
        raise LinguisticError('lemma/sense identity must be language-scoped')
    features=record['features']
    if not isinstance(features,dict):
        raise LinguisticError('features must be a map')
    for name,value in features.items():
        _text(name,'feature name');_text(value,'feature value')
    for key in ('root','pattern','vowel_harmony_class','script','orthographic_variant'):
        if key in record:
            _text(record[key],key)
    for key in ('processes','components','segmentation'):
        if key in record:
            v=record[key]
            if not isinstance(v,list) or any(not isinstance(x,str) for x in v):
                raise LinguisticError('invalid '+key)
            for item in v:_text(item,key)
            if key=='processes' and len(set(v))!=len(v):
                raise LinguisticError('duplicate morphological processes')
    if 'morphemes' in record:
        ms=record['morphemes']
        if not isinstance(ms,list):raise LinguisticError('invalid morpheme array')
        for m in ms:
            if not isinstance(m,dict) or not {'surface','kind','position'}<=m.keys() or m.keys()-MORPHEME_FIELDS:
                raise LinguisticError('invalid morpheme schema')
            _text(m['surface'],'morpheme')
            if m['kind'] not in MORPHEME_KINDS or type(m['position']) is not int or m['position']<0:
                raise LinguisticError('invalid morpheme type/position')
            if 'allomorph' in m:_text(m['allomorph'],'allomorph')
    if pos is not None and pos not in ('noun','verb','adjective','adverb','other'):
        raise LinguisticError('unknown independently supplied POS')
    if lang in ('de','es','fr') and 'person' in features and features['person'] not in PERSON | frozenset(('1','2','3')):
        raise LinguisticError('invalid person tag')
    if lang=='de' and 'number' in features and features['number'] not in GERMAN_NUMBER:
        raise LinguisticError('invalid German number tag')
    if lang=='de':
        if features.get('case','nominative') not in GERMAN_CASE:
            raise LinguisticError('invalid German case')
        if features.get('grammatical_gender','neuter') not in GERMAN_GENDER:
            raise LinguisticError('invalid German grammatical gender')
    if lang=='ar' and 'root' in record:
        pieces=record['root'].split('-')
        if len(pieces) not in (3,4) or any(
                len(piece)!=1 or not ('\u0621'<=piece<='\u064a') for piece in pieces):
            raise LinguisticError('invalid explicit Arabic root')
    if lang=='ar' and 'pattern' in record and 'root' not in record:
        raise LinguisticError('Arabic pattern requires attested root evidence')
    # For other languages, morphology is intentionally not generalized from de.
    return True


def shard_for(record, shard_count):
    """Stable membership only; no files or corpus is written by this module."""
    if type(shard_count) is not int or not 1<=shard_count<=2**31:
        raise LinguisticError('invalid shard count')
    identity='\x00'.join(record[k] for k in ('language_code','source_id','lemma_id','sense_id'))
    return int.from_bytes(hashlib.sha256(identity.encode('utf-8')).digest()[:8],'big')%shard_count


def _unique_pairs(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise LinguisticError('duplicate JSON key')
        result[k]=v
    return result


def _signature(record):
    """Exact same form and tags cannot contradict lexical root or pattern."""
    key=[record[k] for k in ('language_code','lemma_id','sense_id','form')]
    key.append(record['features'])
    a=json.dumps(key,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    b=json.dumps([record.get('root'),record.get('pattern')],ensure_ascii=False)
    return hashlib.sha256(a.encode()).hexdigest(),b


def audit_stream(path, declared_sha256, registered_languages, source_id, *, shards=16,
                 max_line_bytes=1_048_576):
    """Hash and structurally QA an input snapshot without licensing it.

    SQLite temp UNIQUE index bounds RAM even for large JSONL. This method
    cannot admit, publish, grade, or dispatch a corpus: upstream GHA-01/02/03
    and Route 05 evidence approvals are mandatory for those separate steps.
    """
    if not isinstance(declared_sha256,str) or not SHA.fullmatch(declared_sha256):
        raise LinguisticError('missing source SHA-256')
    _text(source_id,'source_id')
    if type(max_line_bytes) is not int or not 1<=max_line_bytes<=1_048_576:
        raise LinguisticError('unsafe JSONL line bound')
    shard_for({'language_code':'x','source_id':'x','lemma_id':'x','sense_id':'x'},shards)
    counts=Counter();part_counts=Counter();digest=hashlib.sha256();n=0
    with tempfile.TemporaryDirectory(prefix='gha04-qa-') as temp:
        with sqlite3.connect(str(Path(temp)/'seen.sqlite')) as db:
            db.execute('CREATE TABLE seen (id TEXT PRIMARY KEY, facts TEXT NOT NULL)')
            with Path(path).open('rb') as stream:
                for line_no,raw in enumerate(stream,1):
                    digest.update(raw)
                    if len(raw)>max_line_bytes:
                        raise LinguisticError(f'line {line_no}: oversized JSONL record')
                    if not raw.strip():continue
                    try:
                        obj=json.loads(raw.decode('utf-8'),object_pairs_hook=_unique_pairs,
                                       parse_constant=lambda v: (_ for _ in ()).throw(LinguisticError('nonfinite number')))
                    except (UnicodeError,ValueError) as exc:
                        raise LinguisticError(f'line {line_no}: invalid JSON') from exc
                    validate_form(obj, registered_languages)
                    if obj['source_id']!=source_id:
                        raise LinguisticError(f'line {line_no}: source ID conflict')
                    key,facts=_signature(obj)
                    prev=db.execute('SELECT facts FROM seen WHERE id=?',(key,)).fetchone()
                    if prev and prev[0]!=facts:
                        raise LinguisticError(f'line {line_no}: contradictory attestation')
                    if not prev:db.execute('INSERT INTO seen VALUES (?,?)',(key,facts))
                    n+=1;counts[obj['language_code']]+=1
                    part_counts[str(shard_for(obj,shards)).zfill(len(str(shards-1)))]+=1
            if digest.hexdigest()!=declared_sha256:
                raise LinguisticError('source artifact SHA-256 mismatch')
    return {'status':'QA_ONLY_BLOCKED_SOURCE','records':n,
            'languages':dict(sorted(counts.items())),'shards':dict(sorted(part_counts.items())),
            'artifact_sha256':digest.hexdigest(),'distributable':False}


def _within_one_edit(a,b):
    a=unicodedata.normalize('NFC',a);b=unicodedata.normalize('NFC',b)
    if abs(len(a)-len(b))>1:return False
    if len(a)>len(b):a,b=b,a
    i=j=edits=0
    while i<len(a) and j<len(b):
        if a[i]==b[j]:i+=1;j+=1
        else:
            edits+=1
            if edits>1:return False
            if len(a)==len(b):i+=1
            j+=1
    return edits+(len(b)-j)<=1


def _arabic_mark_only_difference(a, b):
    """Do not equate distinct Arabic marks without same-sense evidence."""
    def unmarked(value):
        return ''.join(ch for ch in value if not unicodedata.combining(ch))
    return a != b and unmarked(a) == unmarked(b)


def classify_answer(submitted, expected, other_attestations=()):
    """Only a *same-sense* attested alternate can prove morphology error.

    Never accept guessed compounds, spell-correct invented forms or conflate
    different senses. Unverifiable responses remain 'unverified'.
    """
    if not isinstance(submitted,str):raise LinguisticError('answer must be text')
    answer=submitted.strip()
    answer_nfc=unicodedata.normalize('NFC',answer)
    expected_nfc=unicodedata.normalize('NFC',expected['form'])
    if answer_nfc==expected_nfc:return 'correct'
    same=[r for r in other_attestations if r.get('language_code')==expected['language_code']
          and r.get('lemma_id')==expected['lemma_id'] and r.get('sense_id')==expected['sense_id']]
    if any(isinstance(r.get('form'),str) and unicodedata.normalize('NFC',r['form'])==answer_nfc
           and r.get('features')==expected['features'] for r in same):
        return 'correct'
    if any(isinstance(r.get('form'),str) and unicodedata.normalize('NFC',r['form'])==answer_nfc
           and r.get('features')!=expected['features'] for r in same):
        return 'morphology_error'
    if expected['language_code']=='ar' and _arabic_mark_only_difference(answer_nfc,expected_nfc):
        return 'unverified'
    if _within_one_edit(answer_nfc,expected_nfc):return 'spelling_error'
    return 'unverified'
