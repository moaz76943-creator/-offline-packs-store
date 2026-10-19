import unittest
from unittest.mock import patch
from auto_run import run_auto
from test_auto_policy import SHA, MAIN, PR, CHECKS, DOC
class FakeGH:
  def __init__(self,pr=PR,files=DOC,comments=None,base_sha=MAIN):
    self.pr=pr; self.files=files; self.comments=comments or []; self.merges=[]; self.main=MAIN; self.q=0; self.base_sha=base_sha
  def page(self,path,limit=300):
    if path.startswith('/pulls?'):return [{'number':1,'head':{'sha':SHA},'base':{'ref':'main','sha':self.base_sha},'state':'open','draft':False}]
    return []
  def request(self,path,method='GET',data=None):
    if path != '/graphql': raise ValueError('unexpected API call')
    return {'data': {'repository': {'pullRequest': {'reviewThreads': {
        'nodes': [{'isResolved':False}] if self.comments else [],
        'pageInfo': {'hasNextPage':False,'endCursor':None}
    }}}}}
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
  def test_unresolved_review_comments_block(self):
    f=FakeGH(comments=[{'body':'P1 outstanding'}]);self.assertEqual(run_auto(f,MAIN),0);self.assertEqual(f.merges,[])
  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_resolved_historical_comments_do_not_block(self):
    import sys, types
    m=types.ModuleType('protection_gate');m.allowed=lambda branch,rules:True
    with patch.dict(sys.modules,{'protection_gate':m}):
      f=FakeGH();self.assertEqual(run_auto(f,MAIN),0)
      self.assertEqual(f.merges,[(1,SHA)])
  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_sensitive_paths_block(self):
    f=FakeGH(files=[{'filename':'legal/ledger/sources.json','status':'modified'}]);self.assertEqual(run_auto(f,MAIN),0);self.assertEqual(f.merges,[])

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_stale_base_short_circuits_before_expensive_api_calls(self):
    f=FakeGH(base_sha='d'*40)
    self.assertEqual(run_auto(f, MAIN), 0)
    self.assertEqual(f.q, 0)
    self.assertEqual(f.merges, [])

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_stale_base_after_main_advances_is_not_merged(self):
    f=FakeGH()
    f.main='e'*40
    self.assertEqual(run_auto(f, MAIN), 0)
    self.assertEqual(f.merges, [])
