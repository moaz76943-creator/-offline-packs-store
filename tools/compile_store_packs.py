#!/usr/bin/env python3
"""Build verified SQLite v2 gzip envelopes from canonical public lexical JSON.

Legacy manifest fields and existing package bytes are preserved. No network I/O.
Existing CLI: --source-dir, --output-dir, --manifest, --language, --dry-run.
Additional --fixture-only may only write outside this repository.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

from pack_v2.pipeline import (CONTRACT, FORMAT, MAPPING, VERSION, compile_pack,
                              check_envelope)

REPO_ROOT=Path(__file__).resolve().parent.parent
REPO_CDN='https://cdn.jsdelivr.net/gh/moaz76943-creator/-offline-packs-store@main/packs'
CODE=re.compile(r'^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$')


def file_hash(raw):
    return hashlib.sha256(raw).hexdigest()


def inside(path,root):
    return path.resolve().is_relative_to(root.resolve())


def atomic_write(path, data):
    if path.is_symlink():
        raise ValueError('symlinked output path forbidden')
    if path.is_file() and path.read_bytes()==data:
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    name=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.compile-',delete=False) as f:
            name=f.name
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return True

def check_legacy(languages,output):
    for item in languages:
        if not isinstance(item,dict):
            raise ValueError('invalid legacy language descriptor')
        keys=('pack_file','size_bytes','sha256')
        if not any(k in item for k in keys):
            continue
        if not all(k in item for k in keys):
            raise ValueError('partial legacy integrity information')
        name=item['pack_file']
        if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.pack.gz'):
            raise ValueError('unsafe legacy filename')
        path=output/name
        if not inside(path,output):
            raise ValueError('unsafe legacy pack path')
        raw=path.read_bytes()
        if len(raw)!=item['size_bytes'] or file_hash(raw)!=item['sha256']:
            raise ValueError('legacy package hash/size mismatch')
        if item.get('pack_url',f'{REPO_CDN}/{name}')!=f'{REPO_CDN}/{name}':
            raise ValueError('legacy package URL mismatch')

def run(args):
    if args.manifest.is_symlink():
        raise ValueError('symlinked manifest path forbidden')
    if args.fixture_only and (inside(args.output_dir,REPO_ROOT) or inside(args.manifest,REPO_ROOT)):
        raise ValueError('test-only fixtures may not be published in the public repository')
    if not args.source_dir.is_dir():
        raise FileNotFoundError('missing source directory')
    existing=json.loads(args.manifest.read_text('utf-8')) if args.manifest.exists() else {}
    if not isinstance(existing,dict):
        raise ValueError('manifest must be object')
    languages=existing.get('languages',[])
    previous=existing.get('packs',[])
    if not isinstance(languages,list) or not isinstance(previous,list):
        raise ValueError('manifest languages/packs must be arrays')
    check_legacy(languages,args.output_dir)
    indexed={}
    for item in previous:
        if not isinstance(item,dict) or not CODE.fullmatch(str(item.get('id',''))) or item['id'] in indexed:
            raise ValueError('invalid/duplicate previously published pack')
        indexed[item['id']]=item
        name=f"{item['id']}-{item.get('version',VERSION)}.pack.gz"
        if Path(name).name!=name:
            raise ValueError('unsafe retained filename')
        retained_path=args.output_dir/name
        if not inside(retained_path,args.output_dir):
            raise ValueError('unsafe retained package path')
        raw=retained_path.read_bytes()
        if len(raw)!=item.get('archiveSizeBytes') or file_hash(raw)!=item.get('sha256'):
            raise ValueError('retained package hash/size mismatch')
        if item.get('archiveUrl')!=f'{REPO_CDN}/{name}':
            raise ValueError('retained archive URL mismatch')
    sources={}
    for source in sorted(args.source_dir.iterdir()):
        if not source.is_file() or source.suffix not in ('.json','.sqlite') or source.name.endswith(('.meta.json','.grammar.json')):
            continue
        if not inside(source,args.source_dir):
            raise ValueError('unsafe source path: '+source.name)
        lang=source.stem
        if not CODE.fullmatch(lang) or lang in sources:
            raise ValueError('invalid/duplicate language file')
        sources[lang]=source
    if args.language:
        absent=set(args.language)-set(sources)
        if absent:
            raise FileNotFoundError('requested source missing: '+', '.join(sorted(absent)))
        sources={k:v for k,v in sources.items() if k in args.language}
    if not sources:
        raise FileNotFoundError('no approved lexical sources to compile')
    # All compilation and verification complete before touching output/manifest.
    with tempfile.TemporaryDirectory(prefix='store-pack-stage-') as stage_name:
        stage=Path(stage_name)
        produced={}
        for language,src in sorted(sources.items()):
            archive,item=compile_pack(src,language,stage,REPO_ROOT,args.fixture_only)
            item['archiveUrl']=f'{REPO_CDN}/{language}-{VERSION}.pack.gz'
            with __import__('gzip').GzipFile(fileobj=__import__('io').BytesIO(archive)) as gz:
                check_envelope(gz.read(),language)
            produced[language]=(archive,item)
            print(f'{"DRY-RUN" if args.dry_run else "VALID"} {language}: sha256={item["sha256"]}')
        for language,(raw,item) in produced.items():
            path=args.output_dir/f'{language}-{VERSION}.pack.gz'
            if not inside(path,args.output_dir):
                raise ValueError('unsafe output package path')
            if path.exists() and path.read_bytes()!=raw:
                raise ValueError(f'refusing to overwrite previously accepted package: {path.name}')
            indexed[language]=item
        updated=dict(existing)
        updated['schemaVersion']=MAPPING
        updated['format']=FORMAT
        updated['legacyCompatibility']={
            'format':'legacy-json-gzip','metadataField':'languages',
            'packDirectory':'packs/','schemaVersion':'legacy','checksumAlgorithm':'sha256'}
        updated['packs']=[indexed[k] for k in sorted(indexed)]
        manifest=(json.dumps(updated,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
        if args.dry_run:
            print('DRY-RUN: no package or manifest changed')
            return
        # Never overwrite a prior accepted blob. Crash before manifest replacement
        # leaves only unreferenced new files, not a corrupt published manifest.
        created=[]
        try:
            for language,(raw,_) in sorted(produced.items()):
                path=args.output_dir/f'{language}-{VERSION}.pack.gz'
                if not inside(path,args.output_dir):
                    raise ValueError('unsafe output package path')
                if not path.exists():
                    atomic_write(path,raw)
                    created.append(path)
            atomic_write(args.manifest,manifest)  # last publication step
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        print(f'PUBLISHED {len(produced)} verified package(s)')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,default=REPO_ROOT/'tools/sources')
    parser.add_argument('--output-dir',type=Path,default=REPO_ROOT/'packs')
    parser.add_argument('--manifest',type=Path,default=REPO_ROOT/'manifest.json')
    parser.add_argument('--language',action='append')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--fixture-only',action='store_true',help='accept synthetic test data outside repo only')
    args=parser.parse_args(argv)
    try:
        run(args)
    except (OSError,ValueError,TypeError,KeyError,IndexError,sqlite3.Error) as e:
        print(f'ERROR: {e}',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
