"""Combine immutable, independent shard receipts without inferring any edges."""
import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from .graph import AdmissionError, digest, pinned, registry_ids, write_json

def aggregate(registry, artifact_dir, output):
    ids = registry_ids(registry)
    root = Path(artifact_dir)
    folders = sorted(x for x in root.glob("directed-graph-shard-*") if x.is_dir() and not x.is_symlink())
    if not folders or len(folders) > 16:
        raise AdmissionError("INCOMPLETE_SHARD_SET")
    keys = ("registry_sha256","source_ledger_sha256","lexical_sha256",
            "candidate_sha256","review_sha256","interface_language",
            "shard_count","run_id","run_attempt","commit_sha")
    common = None
    found = set()
    totals = Counter()
    pair_counts = Counter()
    seen_translation_ids = set()
    for folder in folders:
        receipt_path, dbpath = folder / "receipt.json", folder / "graph.sqlite"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if pinned(dbpath) != receipt.get("database_sha256"):
            raise AdmissionError("SHARD_SQLITE_SHA_MISMATCH")
        identity = tuple(receipt.get(key) for key in keys)
        if common is None:
            common = identity
            if receipt.get("registry_sha256") != digest(registry):
                raise AdmissionError("REGISTRY_SHA_MISMATCH")
        if identity != common:
            raise AdmissionError("SHARD_PROVENANCE_CONFLICT")
        idx = receipt.get("shard_index")
        count = receipt.get("shard_count")
        if type(idx) is not int or type(count) is not int or not 0 <= idx < count or idx in found:
            raise AdmissionError("DUPLICATE_OR_INVALID_SHARD")
        found.add(idx)
        with sqlite3.connect("file:" + str(dbpath.resolve()) + "?mode=ro", uri=True) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            edges = db.execute("""SELECT translation_id,source_language,target_language,status
                                  FROM edges""")
            local_counts = Counter()
            for tid, a, b, status in edges:
                if (not isinstance(tid, str) or
                        int(hashlib.sha256(tid.encode("utf-8")).hexdigest(),16) % count != idx or
                        tid in seen_translation_ids):
                    raise AdmissionError("DUPLICATED_OR_MISSHARDED_EDGE")
                seen_translation_ids.add(tid)
                local_counts[(a,b,status)] += 1
            rows = [(a,b,st,n) for (a,b,st),n in local_counts.items()]
        for a,b,status,n in rows:
            if a not in ids or b not in ids or a == b or status not in ("verified","review_required"):
                raise AdmissionError("INVALID_SHARD_EDGE")
            pair_counts[(a,b,status)] += n
        for field in ("verified","review_required","blocked","shard_candidates"):
            n = receipt.get("counts",{}).get(field)
            if type(n) is not int or n < 0:
                raise AdmissionError("INVALID_SHARD_COUNT")
            totals[field] += n
        if sum(n for *_,st,n in rows if st == "verified") != receipt["counts"]["verified"]:
            raise AdmissionError("VERIFIED_COUNT_MISMATCH")
        if sum(n for *_,st,n in rows if st == "review_required") != receipt["counts"]["review_required"]:
            raise AdmissionError("REVIEW_COUNT_MISMATCH")
    if found != set(range(common[keys.index("shard_count")])):
        raise AdmissionError("INCOMPLETE_SHARD_SET")
    pairs = []
    for a in ids:
        for b in ids:
            if a == b:
                continue
            v,r = pair_counts[(a,b,"verified")],pair_counts[(a,b,"review_required")]
            pairs.append({"source_language":a,"target_language":b,
                          "verified":v,"review_required":r,
                          "unavailable":v+r == 0,
                          "status":"verified" if v else ("review_required" if r else "unavailable")})
    summary = {"schema_version":"1.0.0","directed_pair_capacity":9900,
               "actual_pair_count":sum(not x["unavailable"] for x in pairs),
               "unavailable_pairs":sum(x["unavailable"] for x in pairs),
               "counts":dict(totals),"shards_verified":len(found),
               "candidate_sha256":common[keys.index("candidate_sha256")],
               "run_id":common[keys.index("run_id")],
               "commit_sha":common[keys.index("commit_sha")]}
    write_json(output,{"summary":summary,"pairs":pairs})
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry",default="catalog/language_registry.v1.json")
    p.add_argument("--artifacts",required=True)
    p.add_argument("--out",required=True)
    x=p.parse_args()
    print(json.dumps(aggregate(x.registry,x.artifacts,x.out),sort_keys=True))

if __name__=="__main__":
    main()
