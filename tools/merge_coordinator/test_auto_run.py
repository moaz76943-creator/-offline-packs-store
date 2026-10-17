import unittest
from unittest.mock import patch
from auto_run import run_auto
from test_auto_policy import SHA, MAIN, PR, CHECKS, DOC
class FakeGH:
  def __init__(self,pr=PR,files=DOC,comments=None):
    self.pr=pr; self.files=files; self.comments=comments or []; self.merges=[]; self.main=MAIN; self.q=0
  def page(self,path,limit=300):
    if path.startswith('/pulls?'):return [{'number':1,'head':{'sha':SHA},'state':'open','draft':False}]
    if path.endswith('/comments'):return self.comments
    return []
  def main_sha(self):return self.main
  def query_pr(self,num,head):self.q+=1;return self.pr,CHECKS,[],self.files,'feat: docs'
  def get(self,path):
    if path=='/branches/main':return {'name':'main','protected':True}
    return [{'type':'required_status_checks','parameters':{'strict_required_status_checks_policy':True,'required_status_checks':[{'context':'public-pr-merge-gate'}]}},{'type':'pull_request','parameters':{'required_approving_review_count':1}},{'type':'non_fast_forward'},{'type':'deletion'}]
  def squash(self,num,head):self.merges.append((num,head));return {'merged':True,'sha':'c'*40}
class FlowTests(unittest.TestCase):
  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'false'})
  def test_dry_run_does_not_merge(self):
    f=FakeGH();self.assertEqual(run_auto(f,MAIN),0);self.assertEqual(f.merges,[])
  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_safe_merge(self):
    import sys, types
    m=types.ModuleType('protection_gate');m.allowed=lambda branch,rules:True
    with patch.dict(sys.modules,{'protection_gate':m}):
      f=FakeGH();self.assertEqual(run_auto(f,MAIN),0);self.assertEqual(f.merges,[(1,SHA)]);self.assertEqual(f.q,2)
  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_review_comments_block(self):
    f=FakeGH(comments=[{'body':'P1 outstanding'}]);self.assertEqual(run_auto(f,MAIN),0);self.assertEqual(f.merges,[])
  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_sensitive_paths_block(self):
    f=FakeGH(files=[{'filename':'legal/ledger/sources.json','status':'modified'}]);self.assertEqual(run_auto(f,MAIN),0);self.assertEqual(f.merges,[])
