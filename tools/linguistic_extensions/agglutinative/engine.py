"""Read-only, source-gated, on-demand morphology for 14 independently registered languages.

A canonical capability declaration is NOT a licensed form or a productive grammar.
No vowel-harmony, consonant-gradation, suffix, transliteration or paradigm generator exists.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SHARD_DIR = 'tools/linguistic_extensions/agglutinative/shards'
MAX_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 10000
MAX_LINE = 16384
MAX_LOOKUP = 128
HEX64 = re.compile(r'^[0-9a-f]{64}$')
PATH = re.compile(r'^' + re.escape(SHARD_DIR) + r'/([a-z]{2})/([A-Za-z0-9_-]+)\\.jsonl$')

# Explicit language identity; family is never used to infer word-formation rules.
MODELS = {
    'tr': ('Turkic', 'turkish'), 'az': ('Turkic', 'azerbaijani'),
    'uz': ('Turkic', 'uzbek'), 'kk': ('Turkic', 'kazakh'),
    'ky': ('Turkic', 'kyrgyz'), 'tk': ('Turkic', 'turkmen'),
    'tt': ('Turkic', 'tatar'), 'ba': ('Turkic', 'bashkir'),
    'ug': ('Turkic', 'uyghur'), 'fi': ('Uralic', 'finnish'),
    'et': ('Uralic', 'estonian'), 'hu': ('Uralic', 'hungarian'),
    'mn': ('Mongolic', 'mongolian'), 'eu': ('Isolate', 'basque'),
}
# Distinct lexical properties are inspectable; no productive ordering is implied.
DIMENSIONS = ('case','number','possession','person','tense','aspect','mood',
              'agreement','ergativity','vowel_harmony','suffix_order',
              'consonant_gradation','stem_alternation','compounding',
              'derivation','voice','definiteness')
CANONICAL = {'case':'case','number':'number','aspect':'aspect',
             'compounding':'compound','person':'person','tense':'tense',
             'mood':'mood','agreement':'agreement','vowel_harmony':'vowel_harmony',
             'voice':'voice','definiteness':'definiteness'}
ALLOWED_KINDS = {'root','stem','prefix','suffix','infix','clitic','compound_member'}
ALLOWED_PROCESSES = {'vowel_harmony','consonant_gradation','stem_alternation',
                     'compound','suffixation','prefixation','derivation','cliticization'}
SCRIPT_NAMES = {'Latn':'LATIN', 'Cyrl':'CYRILLIC', 'Arab':'ARABIC', 'Mong':'MONGOLIAN'}


class EvidenceError(ValueError):
    """Unverified data, mismatched registration or unsafe morphology."""


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError('duplicate JSON key')
        result[key] = value
    return result


def _json(path):
    with path.open(encoding='utf-8') as handle:
        return json.load(handle, object_pairs_hook=_pairs)


def _nfc(value, label, max_length=256):
    if not isinstance(value,str) or not value or len(value)>max_length or unicodedata.normalize('NFC',value)!=value:
        raise EvidenceError(f'non-NFC, empty or oversized {label}')
    if any(unicodedata.category(ch) == 'Cc' for ch in value):
        raise EvidenceError(f'control code in {label}')
    return value


def _script_ok(value, script):
    expected=SCRIPT_NAMES[script]
    for character in value:
        if not character.isalpha():
            continue
        unicode_name=unicodedata.name(character,'')
        # Arabic mark, Mongolian combining marks are not alphabetic by category.
        if not unicode_name.startswith(expected+' '):
            return False
    return True


class Extension:
    """Read-only bounded-shard audit/lookup. Never synthesizes unseen forms."""

    def __init__(self,root=REPO_ROOT):
        self.root=Path(root).resolve()
        registry=_json(self.root/'catalog/language_registry.v1.json')
        self.features=_json(self.root/'standards/morphology/feature_overrides.json')
        self.ledger=_json(self.root/'legal/ledger/sources.json')
        registered=registry.get('languages')
        if not isinstance(registered,list) or len(registered)!=100 or len({r['id'] for r in registered})!=100:
            raise EvidenceError('canonical 100-language registry required')
        index={r['id']:r for r in registered}
        self.registry={}
        for code,(family,model) in MODELS.items():
            lang=index.get(code)
            if lang is None or lang.get('family') != family or not lang.get('scripts'):
                raise EvidenceError('unexpected canonical language identity: '+code)
            self.registry[code]=lang
        self.variants={(v['language_id'],v['tag']):v for v in registry['locale_variants']}
        self.sources={s['source_id']:s for s in self.ledger['sources']}
        if len(self.sources)!=len(self.ledger['sources']):
            raise EvidenceError('ambiguous source identifiers')

    @property
    def languages(self):
        return tuple(MODELS)

    def profile(self,language):
        if language not in self.registry:
            raise EvidenceError('language not in isolated scope')
        record=self.registry[language]
        flags=set(record['morphology']['features'])
        overrides=self.features['overrides'].get(language,{})
        dimensions={}
        for dim in DIMENSIONS:
            if dim in ('case','number','aspect') and dim in flags:
                status='canonical_declared'
            elif overrides.get(CANONICAL.get(dim,''))=='supported':
                status='canonical_declared'
            else:
                status='unknown'
            dimensions[dim]=status
        return {'language_code':language,'family':record['family'],
                'model':MODELS[language][1], 'scripts':list(record['scripts']),
                'default_script':record['default_script'],
                'registry_review_status':record['morphology']['review_status'],
                'dimensions':dimensions,'forms_status':'not_admitted',
                'generative_rules_enabled':False,
                'coverage':{'lemmas':0,'forms':0,'covered_dimensions':[],
                            'unknown_dimensions':list(DIMENSIONS),'unknown_case_inventory':True}}

    def _path(self,language,shard):
        if language not in self.registry:
            raise EvidenceError('unregistered language')
        if not isinstance(shard,str):
            raise EvidenceError('invalid shard path')
        match=PATH.fullmatch(shard)
        if not match or match.group(1)!=language:
            raise EvidenceError('invalid language-scoped shard path')
        file=self.root/shard
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(self.root/SHARD_DIR):
            raise EvidenceError('missing, linked or escaping shard')
        if file.stat().st_size>MAX_BYTES:
            raise EvidenceError('oversized shard')
        return file

    def _admission(self,shard,digest):
        candidates=[]
        daily=self.root/'legal/ledger/daily'
        for file in sorted(daily.glob('????-??-??.json')):
            doc=_json(file)
            if doc.get('schema_version')!='1.0.0':
                raise EvidenceError('invalid daily ledger version')
            for candidate in doc.get('release_candidates',[]):
                if candidate.get('artifact_path')==shard:
                    candidates.append(candidate)
        if len(candidates)!=1:
            raise EvidenceError('shard has no unique reviewed release admission')
        candidate=candidates[0]
        if candidate.get('kind')!='morphology' or candidate.get('sha256')!=digest:
            raise EvidenceError('checkpoint digest differs from admitted shard')
        review=candidate.get('review') or {}
        if not review.get('reviewer') or not str(review.get('decision_url','')).startswith('https://'):
            raise EvidenceError('no manual release review')
        refs=candidate.get('source_refs')
        if not isinstance(refs,list) or not refs:
            raise EvidenceError('missing reviewed source references')
        approved={}
        for ref in refs:
            source=self.sources.get(ref.get('source_id'))
            if (source is None or source.get('kind')!='morphology'
                    or source.get('status')!='APPROVED_FOR_REDISTRIBUTION'
                    or source.get('dataset_version')!=ref.get('dataset_version')
                    or source.get('retrieval',{}).get('sha256')!=ref.get('artifact_sha256')
                    or not HEX64.fullmatch(str(ref.get('artifact_sha256','')))
                    or not source.get('review',{}).get('reviewer')
                    or not str(source.get('review',{}).get('decision_url','')).startswith('https://')
                    or not candidate.get('notices',{}).get(ref.get('source_id'))):
                raise EvidenceError('unapproved or mismatched source provenance')
            if ref['source_id'] in approved:
                raise EvidenceError('duplicate source reference')
            approved[ref['source_id']]=(ref['dataset_version'],ref['artifact_sha256'])
        return approved

    def _iter(self,file):
        with file.open('rb') as stream:
            for line_no,raw in enumerate(stream,1):
                if len(raw)>MAX_LINE:
                    raise EvidenceError('oversized JSONL record')
                if not raw.strip():
                    continue
                try:
                    record=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs)
                except (UnicodeError,json.JSONDecodeError) as err:
                    raise EvidenceError(f'bad UTF-8/JSON at line {line_no}') from err
                yield record

    def _record(self,record,language,approved):
        if not isinstance(record,dict) or set(record)-{'language_code','lemma_id','sense_id','lemma','form','script','variant','features','morphemes','processes','evidence'}:
            raise EvidenceError('unknown form fields')
        if record.get('language_code')!=language:
            raise EvidenceError('cross-language record')
        for key in ('lemma_id','sense_id','lemma','form'):
            _nfc(record.get(key),key)
        if any(not record[key].startswith(language+':') for key in ('lemma_id','sense_id')):
            raise EvidenceError('cross-language lemma or sense')
        script=record.get('script')
        if script not in self.registry[language]['scripts']:
            raise EvidenceError('unregistered script')
        if not _script_ok(record['lemma'],script) or not _script_ok(record['form'],script):
            raise EvidenceError('record script does not match original writing')
        variant=record.get('variant')
        if variant is not None:
            v=self.variants.get((language,variant))
            if v is None or v.get('script')!=script:
                raise EvidenceError('cross-language or unsanctioned script variant')
        tags=record.get('features')
        if not isinstance(tags,dict) or len(tags)>len(DIMENSIONS) or not tags or any(k not in DIMENSIONS for k in tags):
            raise EvidenceError('unknown morphology dimensions')
        for value in tags.values():
            _nfc(value,'feature',80)
        if 'ergativity' in tags and language!='eu':
            raise EvidenceError('Basque-only ergativity label in other language')
        morphemes=record.get('morphemes',[])
        if not isinstance(morphemes,list) or len(morphemes)>32:
            raise EvidenceError('unbounded morphemes')
        for index,part in enumerate(morphemes):
            if not isinstance(part,dict) or set(part)-{'kind','surface','position','slot'}:
                raise EvidenceError('invalid morpheme')
            if part.get('position')!=index or part.get('kind') not in ALLOWED_KINDS:
                raise EvidenceError('morphemes out of attested order')
            _nfc(part.get('surface'),'morpheme surface')
            if 'slot' in part and part['slot'] not in DIMENSIONS:
                raise EvidenceError('unknown suffix slot')
        processes=record.get('processes',[])
        if (not isinstance(processes,list) or any(not isinstance(p,str) for p in processes)
                or len(set(processes))!=len(processes) or not set(processes)<=ALLOWED_PROCESSES):
            raise EvidenceError('unknown morphological processes')
        ev=record.get('evidence')
        if not isinstance(ev,dict) or ev.get('generated') is not False:
            raise EvidenceError('generated/unverified form rejected')
        if ev.get('status')!='verified' or not _nfc(ev.get('attestation_id'),'attestation'):
            raise EvidenceError('unverified attestation')
        if (ev.get('source_id') not in approved or
                approved[ev['source_id']] != (ev.get('dataset_version'),ev.get('artifact_sha256'))):
            raise EvidenceError('record provenance not admitted')

    def audit(self,language,shard):
        file=self._path(language,shard)
        with file.open('rb') as source_stream:
            digest=hashlib.file_digest(source_stream,'sha256').hexdigest()
        approved=self._admission(shard,digest)
        lemmas=set(); keys=set(); seen_dimensions=set(); scripts=set(); forms=0
        for record in self._iter(file):
            forms+=1
            if forms>MAX_RECORDS:
                raise EvidenceError('too many records in shard')
            self._record(record,language,approved)
            key=(record['lemma_id'],record['sense_id'],record['form'],record['script'],
                 record.get('variant'),tuple(sorted(record['features'].items())))
            if key in keys:
                raise EvidenceError('duplicate attested form')
            keys.add(key);lemmas.add(record['lemma_id']);scripts.add(record['script']);seen_dimensions.update(record['features'])
        return {'language_code':language,'shard':shard,'checkpoint_sha256':digest,
                'lemmas':len(lemmas),'forms':forms,'scripts':sorted(scripts),
                'covered_dimensions':sorted(seen_dimensions),
                'unknown_dimensions':sorted(set(DIMENSIONS)-seen_dimensions),
                'unknown_case_inventory': 'case' not in seen_dimensions,
                'generated_forms':0,'unverified_forms':0,
                'run_id':'set_by_hosted_workflow_only'}

    def lookup(self,language,lemma_id,features=None,script=None,shard=None,sense_id=None):
        if language not in self.registry or not isinstance(lemma_id,str) or not lemma_id.startswith(language+':'):
            raise EvidenceError('cross-language or unknown lemma')
        if features is None: features={}
        if not isinstance(features,dict) or any(k not in DIMENSIONS or not isinstance(v,str) for k,v in features.items()):
            raise EvidenceError('unknown query feature')
        if script is not None and script not in self.registry[language]['scripts']:
            raise EvidenceError('script not registered')
        if shard is None:
            return {'status':'unknown','forms':[]}
        file=self._path(language,shard)
        self.audit(language,shard) # fail entire shard closed before returning any record
        matches=[]
        for row in self._iter(file):
            if (row['lemma_id']==lemma_id and (sense_id is None or row['sense_id']==sense_id)
                    and (script is None or row['script']==script)
                    and all(row['features'].get(k)==v for k,v in features.items())):
                matches.append(row)
                if len(matches)>MAX_LOOKUP:
                    raise EvidenceError('lookup result bound exceeded')
        return {'status':'verified' if matches else 'unknown','forms':matches}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language',required=True,choices=MODELS)
    parser.add_argument('--shard',help='Approved public JSONL relative path, optional for capability check')
    parser.add_argument('--root',type=Path,default=REPO_ROOT)
    args=parser.parse_args()
    ext=Extension(args.root)
    print(json.dumps(ext.audit(args.language,args.shard) if args.shard else ext.profile(args.language),
                     sort_keys=True,ensure_ascii=False))


if __name__=='__main__':
    main()
