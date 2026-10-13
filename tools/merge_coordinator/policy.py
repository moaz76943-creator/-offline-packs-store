"""Deterministic fail-closed PR classification."""
import re
from dataclasses import dataclass, field, asdict
from fnmatch import fnmatch

STATES = ('VERIFIED_READY','WAITING_CHECKS','DRAFT','BLOCKED_SKIP_CI','MERGE_CONFLICT','DEPENDENCY_BLOCKED','SEMANTIC_CONFLICT','DUPLICATE','SUPERSEDED','SECURITY_REVIEW','RIGHTS_REVIEW','HUMAN_REVIEW','UNVERIFIED')
SKIP = re.compile(r'\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]|(?im:^skip-checks:\s*true\s*$)', re.I)
DEPENDS = re.compile(r'(?im)^depends-on:\s*#([1-9]\d*)\s*$')
RISK = {
 'RIGHTS_REVIEW': ('legal/**','tools/attribution/**','tools/translation_provenance/**','tools/contribution_gate/**','tools/source_rights/**','licenses/**','**/*license*','**/*rights*','**/*provenance*'),
 'SECURITY_REVIEW': ('.github/workflows/**','.github/CODEOWNERS','**/*security*','tools/merge_coordinator/**','tools/ci_policy/**','community/review/**','**/*permission*','**/*auth*'),
 'HUMAN_REVIEW': ('**/*.sqlite','**/*.db','assets/**','packs/**','store/**','tools/release_publication/**','tools/final_release_evidence/**','tools/pack_manifest/**','tools/release_validation/**','tools/pack_conformance/**','**/*schema*','**/*migration*','**/*manifest*','**/*publication*','**/*release*','**/*generated*','catalog/**'),
}

@dataclass
class Pull:
 number:int
 head:str
 base:str
 draft:bool
 files:tuple[str,...]=()
 changed:bool=True
 mergeable:bool|None=None
 mergeable_state:str=''
 head_message:str=''
 body:str=''
 title:str=''
 checks:dict=field(default_factory=dict)
 required_checks:tuple[str,...]=()
 approvals:int=0
 required_approvals:int=1
 change_requested:bool=False
 author:str=''
 labels:tuple[str,...]=()
 @property
 def dependencies(self):
  return {int(x) for x in DEPENDS.findall(self.body)}

@dataclass
class Decision:
 number:int
 head:str
 base:str
 state:str
 reasons:list[str]
 depends_on:list[int]=field(default_factory=list)
 conflicts_with:list[int]=field(default_factory=list)
 changed_files:int=0
 def json(self):
  return asdict(self)

def high_risk(files):
 for classification in ('RIGHTS_REVIEW','SECURITY_REVIEW','HUMAN_REVIEW'):
  for name in files:
   if any(fnmatch(name.lower(),pat.lower()) for pat in RISK[classification]):
    return classification
 return None

def graph(prs):
 conflicts={p.number:set() for p in prs}
 deps={p.number:p.dependencies for p in prs}
 by_path={}
 for p in prs:
  for path in p.files:
   by_path.setdefault(path,set()).add(p.number)
 for numbers in by_path.values():
  for n in numbers:
   conflicts[n].update(numbers-{n})
 return conflicts,deps
