"""Loss-aware Wiktextract adapter. No source approval or generated linguistic data."""
import hashlib
import json
import unicodedata
from tools.gha_factory.admission.pipeline import script_valid
from tools.sources.pilot5.pipeline import POS

VERSION = 'content-ingestion-1.0.0'


class Reject(ValueError):
    pass


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def stable(prefix, *parts):
    return prefix+'.'+hashlib.sha256(canonical(parts).encode('utf-8')).hexdigest()


def partition(identity, count):
    if type(count) is not int or not 1<=count<=4096:
        raise Reject('INVALID_PARTITION_COUNT')
    return int(hashlib.sha256(identity.encode()).hexdigest(),16)%count


def text(value, max_size=10000):
    if not isinstance(value,str) or not value.strip() or len(value)>max_size:
        raise Reject('INVALID_TEXT')
    try:
        value.encode('utf-8',errors='strict')
    except UnicodeError as exc:
        raise Reject('INVALID_UNICODE') from exc
    if any(unicodedata.category(c) in ('Cs','Cc') and c not in '\n\t' for c in value):
        raise Reject('INVALID_UNICODE')
    return unicodedata.normalize('NFC',value)


def strings(value, maximum=256):
    if not isinstance(value,list) or len(value)>maximum:
        raise Reject('INVALID_TAGS')
    return sorted({text(x,256) for x in value})


def provenance(source, locator):
    # Legal input approval is NOT downstream lexical publication approval.
    return {'source_id':source['source_id'],'origin_url':source['origin_url'],
            'publisher':source['publisher'],'dataset_version':source['dataset_version'],
            'retrieval_id':source['retrieval']['identity'],'license_id':source['license']['id'],
            'artifact_sha256':source['retrieval']['sha256'],'record_locator':locator,
            'publication_approved':False,'fixture_only':source.get('fixture_only',False)}


def extract(row, source, registry, language, locator):
    if not isinstance(row,dict) or row.get('lang_code')!=language:
        raise Reject('WRONG_LANGUAGE')
    if row.get('source_id',source['source_id'])!=source['source_id']:
        raise Reject('WRONG_SOURCE')
    if row.get('license_id',source['license']['id'])!=source['license']['id']:
        raise Reject('WRONG_LICENSE')
    entry=next((r for r in registry['languages'] if r['id']==language),None)
    if entry is None:
        raise Reject('UNREGISTERED_LANGUAGE')
    script=row.get('script',entry['default_script'])
    word=text(row.get('word'),256)
    if script not in entry['scripts'] or not script_valid(word,script):
        raise Reject('WRONG_OR_UNSUPPORTED_SCRIPT')
    pos=POS.get(row.get('pos')) if isinstance(row.get('pos'),str) else None
    if not pos:
        raise Reject('UNSUPPORTED_POS')
    etym=row.get('etymology_number')
    if etym is not None and (type(etym) is not int or etym<0):
        raise Reject('INVALID_ETYMOLOGY')
    etym_text=text(row['etymology_text']) if row.get('etymology_text') is not None else None
    dialect=text(row['dialect'],256) if row.get('dialect') is not None else None
    # No casefold: Turkish I/i and native spellings remain distinct.
    identity=(language,script,word,pos,etym,dialect,etym_text)
    lid=stable('lex',source['source_id'],*identity)
    src=provenance(source,locator)
    direction=registry['scripts'][script]['direction']
    lex={'lexeme_id':lid,'language':language,'script':script,'lemma':word,
         'surface':word,'pos':pos,'direction':'ttb' if direction.startswith('ttb') else direction,
         'source':src}
    if dialect:lex['dialect']=dialect
    if etym is not None or row.get('etymology_text'):
        lex['homograph_key']=stable('etym',etym,etym_text)
    review=[];morph={};tags=strings(row.get('tags',[]))
    genders=set(tags)&{'masculine','feminine','neuter','common-gender'}
    if len(genders)==1:morph['gender']=next(iter(genders))
    elif genders:review.append('AMBIGUOUS_GENDER')
    for key,field in [('root','roots'),('pattern','patterns')]:
        if row.get(key) is not None:morph[field]=[text(row[key],256)]
    forms=row.get('forms',[])
    if not isinstance(forms,list) or len(forms)>1024:raise Reject('OVERSIZED_FORMS')
    for form in forms:
        if not isinstance(form,dict):raise Reject('INVALID_FORM')
        surface=text(form.get('form'),512);ft=strings(form.get('tags',[]))
        features={'source_tags':canonical(ft)}
        for key,opts in [('number',{'singular','plural','dual'}),
                         ('tense',{'past','present','future','preterite','perfect','pluperfect'}),
                         ('mood',{'indicative','subjunctive','imperative','conditional'}),
                         ('person',{'first-person','second-person','third-person'}),
                         ('case',{'nominative','accusative','dative','genitive','vocative'}),
                         ('degree',{'comparative','superlative','positive'})]:
            found=set(ft)&opts
            if len(found)==1:features[key]=next(iter(found))
            elif found:review.append('AMBIGUOUS_FORM_'+key.upper())
        item={'surface':surface,'features':features,'attested':True,'source':src}
        if form.get('auxiliary') is not None:item['auxiliary']=text(form['auxiliary'],128)
        if form.get('roman') is not None:item['variant']=text(form['roman'],512)
        bucket=('articles' if {'article','definite'}<=set(ft) else
                'classifiers' if 'classifier' in ft else
                'irregular_forms' if 'irregular' in ft else
                'conjugations' if pos=='verb' else 'inflections')
        if item not in morph.setdefault(bucket,[]):morph[bucket].append(item)
    if morph:lex['morphology']=morph
    sounds=row.get('sounds',[])
    if not isinstance(sounds,list) or len(sounds)>256:raise Reject('OVERSIZED_SOUNDS')
    for sound in sounds:
        if not isinstance(sound,dict):raise Reject('INVALID_SOUND')
        for key,notation in [('ipa','ipa'),('roman','romanization')]:
            if sound.get(key) is not None:
                item={'notation':notation,'value':text(sound[key],1024),'source':src}
                st=strings(sound.get('tags',[]))
                if st:item['dialect']='; '.join(st)
                if item not in lex.setdefault('pronunciations',[]):lex['pronunciations'].append(item)
    raw_senses=row.get('senses')
    if not isinstance(raw_senses,list) or not 1<=len(raw_senses)<=128:raise Reject('INVALID_SENSES')
    senses=[];links=[];seen=set()
    for sense in raw_senses:
        if not isinstance(sense,dict):raise Reject('INVALID_SENSE')
        glosses=sense.get('glosses')
        if not isinstance(glosses,list) or not 1<=len(glosses)<=64:raise Reject('INVALID_GLOSSES')
        definition='\n'.join(text(g) for g in glosses)
        # Entire attested sense identity preserves qualifiers and distinct meanings.
        sid=stable('sense',lid,sense)
        if sid in seen:continue
        seen.add(sid)
        senses.append({'sense_id':sid,'lexeme_id':lid,'definition':definition,
                       'concept_id':stable('concept.unmapped',sid),'source':src})
        translations=sense.get('translations',[])
        if not isinstance(translations,list) or len(translations)>512:raise Reject('INVALID_TRANSLATIONS')
        for tr in translations:
            if not isinstance(tr,dict):raise Reject('INVALID_TRANSLATION')
            target=tr.get('lang_code')
            if target not in {r['id'] for r in registry['languages']}:
                review.append('UNREGISTERED_TRANSLATION_TARGET');continue
            links.append({'from_sense_id':sid,'to_sense_id':None,
                          'source_language':language,'target_language':target,
                          'text':text(tr.get('word'),512),'source':src,
                          'status':'REVIEW_REQUIRED_TARGET_SENSE',
                          'confidence':'SOURCE_ATTESTED_UNRESOLVED',
                          'evidence':tr})
    top_translations=row.get('translations',[])
    if not isinstance(top_translations,list) or len(top_translations)>512:
        raise Reject('INVALID_TRANSLATIONS')
    for tr in top_translations:
        if not isinstance(tr,dict):raise Reject('INVALID_TRANSLATION')
        target=tr.get('lang_code')
        if target not in {r['id'] for r in registry['languages']}:
            review.append('UNREGISTERED_TRANSLATION_TARGET');continue
        links.append({'from_sense_id':None,'to_sense_id':None,
                      'source_language':language,'target_language':target,
                      'text':text(tr.get('word'),512),'source':src,
                      'status':'REVIEW_REQUIRED_SOURCE_AND_TARGET_SENSE',
                      'confidence':'SOURCE_ATTESTED_UNRESOLVED','evidence':tr})
    doc={'contract_version':'1.0.0','document_id':stable('batch',lid),
         'lexemes':[lex],'senses':senses,'translations':[],'examples':[],'relations':[]}
    return {'lexeme':lex,'senses':senses,'links':links,'review':sorted(set(review)),
            'logical_identity':stable('logical',*identity),'document':doc}
