"""Test an ownership-blocked patch only in a temporary copy of real modules."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PATCH=ROOT/'tools/gha_factory/dispatcher/repairs/exec03.patch'

class CandidatePatch(unittest.TestCase):
    def test_real_patched_dispatcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for prefix in ('tools/gha_factory/dispatcher','tests/gha_factory/dispatcher'):
                shutil.copytree(ROOT/prefix,root/prefix,ignore=shutil.ignore_patterns('__pycache__'))
            for args in (['git','apply','--check',str(PATCH)],['git','apply',str(PATCH)]):
                r=subprocess.run(args,cwd=root,capture_output=True,text=True,timeout=10)
                self.assertEqual(r.returncode,0,r.stderr)
            env=dict(os.environ);env.pop('GITHUB_TOKEN',None)
            for args in ([sys.executable,'-m','unittest','discover','-s','tests/gha_factory/dispatcher','-p','test_queue.py','-v'],[sys.executable,'tests/gha_factory/dispatcher/repair_cases/lifecycle_cases.py']):
                r=subprocess.run(args,cwd=root,env=env,capture_output=True,text=True,timeout=30)
                self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                print(r.stderr,file=sys.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
