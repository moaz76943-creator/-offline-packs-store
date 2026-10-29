import unittest
import urllib.error
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
  def squash(self,num,head):
    self.merges.append((num,head));self.main='c'*40
    return {'merged':True,'sha':self.main}
class FlowTests(unittest.TestCase):
  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_candidate_read_failure_does_not_starve_verified_peer(self):
    import sys, types
    m=types.ModuleType('protection_gate');m.allowed=lambda branch,rules:True
    for stage in ('query', 'threads', 'fresh_query', 'fresh_threads'):
      for error in (urllib.error.HTTPError('https://api.github.com',404,'gone',{},None),
                    urllib.error.HTTPError('https://api.github.com',503,'unavailable',{},None),
                    urllib.error.URLError('transport unavailable')):
        with self.subTest(stage=stage,error=type(error).__name__), patch.dict(sys.modules,{'protection_gate':m}):
          class MixedQueue(FakeGH):
            def __init__(self):
              super().__init__();self.reads={};self.threads={}
            def page(self,path,limit=300):
              if path.startswith('/pulls?'):
                return [{'number':n,'head':{'sha':SHA},'base':{'ref':'main','sha':self.main},
                         'state':'open','draft':False} for n in (2,1)]
              return []
            def query_pr(self,num,head):
              self.reads[num]=self.reads.get(num,0)+1
              if num==2 and ((stage=='query') or (stage=='fresh_query' and self.reads[num]%2==0)):
                raise error
              return super().query_pr(num,head)
            def request(self,path,method='GET',data=None):
              num=data['variables']['number'];self.threads[num]=self.threads.get(num,0)+1
              if num==2 and ((stage=='threads') or (stage=='fresh_threads' and self.threads[num]%2==0)):
                raise error
              return super().request(path,method,data)
          f=MixedQueue()
          self.assertEqual(run_auto(f,MAIN),0)
          self.assertEqual(f.merges,[(1,SHA)])

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_account_authorization_and_rate_limit_errors_stop_batch(self):
    for code in (401,403,429):
      for stage in ('query','threads'):
        with self.subTest(code=code,stage=stage):
          class AccountFailure(FakeGH):
            def query_pr(self,num,head):
              if stage=='query':raise urllib.error.HTTPError('https://api.github.com',code,'blocked',{},None)
              return super().query_pr(num,head)
            def request(self,path,method='GET',data=None):
              raise urllib.error.HTTPError('https://api.github.com',code,'blocked',{},None)
          f=AccountFailure()
          with self.assertRaises(urllib.error.HTTPError):run_auto(f,MAIN)
          self.assertEqual(f.merges,[])

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_missing_thread_evidence_never_authorizes_merge(self):
    class MissingThreads(FakeGH):
      def request(self,path,method='GET',data=None):return {'errors':[{'message':'unavailable'}]}
    f=MissingThreads()
    self.assertEqual(run_auto(f,MAIN),0)
    self.assertEqual(f.merges,[])

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
  def test_one_scheduled_run_drains_multiple_verified_prs_with_fresh_base_checks(self):
    import sys, types
    m=types.ModuleType('protection_gate');m.allowed=lambda branch,rules:True
    class QueueGH(FakeGH):
      def __init__(self):
        super().__init__();self.remaining=[1,2,3];self.base_history=[]
      def page(self,path,limit=300):
        if path.startswith('/pulls?'):
          return [{'number':n,'head':{'sha':format(n,'040x')},'base':{'ref':'main','sha':self.main},
                   'state':'open','draft':False} for n in self.remaining]
        return []
      def query_pr(self,num,head):
        self.q+=1
        self.base_history.append(self.main)
        return ({**PR,'head':{'sha':head,'repo':{'full_name':'moaz76943-creator/-offline-packs-store'}},
                 'base':{'ref':'main','sha':self.main}},
                {'check_runs':[{**CHECKS['check_runs'][0],'head_sha':head}]},[],self.files,'feat: docs')
      def squash(self,num,head):
        self.merges.append((num,head));self.remaining.remove(num)
        self.main=format(num+100,'040x')
        return {'merged':True,'sha':self.main}
    with patch.dict(sys.modules,{'protection_gate':m}):
      f=QueueGH()
      self.assertEqual(run_auto(f,MAIN),0)
      self.assertEqual([n for n,h in f.merges],[3,2,1])
      self.assertEqual(f.remaining,[])
      self.assertEqual(len(set(f.base_history)),3)
      self.assertEqual(f.q,6)

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_batched_merging_is_bounded_to_eight_transitions(self):
    import sys, types
    m=types.ModuleType('protection_gate');m.allowed=lambda branch,rules:True
    class LargeQueueGH(FakeGH):
      def __init__(self):super().__init__();self.remaining=list(range(1,20))
      def page(self,path,limit=300):
        if path.startswith('/pulls?'):
          return [{'number':n,'head':{'sha':format(n,'040x')},
                   'base':{'ref':'main','sha':self.main},'state':'open','draft':False}
                  for n in self.remaining]
        return []
      def query_pr(self,num,head):
        self.q+=1
        return ({**PR,'head':{'sha':head,'repo':{'full_name':'moaz76943-creator/-offline-packs-store'}},
                 'base':{'ref':'main','sha':self.main}},
                {'check_runs':[{**CHECKS['check_runs'][0],'head_sha':head}]},[],self.files,'feat: docs')
      def squash(self,num,head):
        self.merges.append((num,head));self.remaining.remove(num)
        self.main=format(num+100,'040x')
        return {'merged':True,'sha':self.main}
    with patch.dict(sys.modules,{'protection_gate':m}):
      f=LargeQueueGH();self.assertEqual(run_auto(f,MAIN),0)
      self.assertEqual(len(f.merges),8)
      self.assertEqual(len(f.remaining),11)

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_external_main_movement_stops_without_another_merge(self):
    import sys, types
    m=types.ModuleType('protection_gate');m.allowed=lambda branch,rules:True
    class ExternalMoveGH(FakeGH):
      def squash(self,num,head):
        self.merges.append((num,head))
        self.main='e'*40
        return {'merged':True,'sha':'d'*40}
    with patch.dict(sys.modules,{'protection_gate':m}):
      f=ExternalMoveGH();self.assertEqual(run_auto(f,MAIN),0)
      self.assertEqual(len(f.merges),1)

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_oversized_candidate_does_not_starve_independent_ready_pr(self):
    import sys, types
    m=types.ModuleType('protection_gate');m.allowed=lambda branch,rules:True
    class MixedQueue(FakeGH):
      def page(self,path,limit=300):
        if path.startswith('/pulls?'):
          return [{'number':n,'head':{'sha':SHA},'base':{'ref':'main','sha':self.main},
                   'state':'open','draft':False} for n in (2,1)]
        return []
      def query_pr(self,num,head):
        self.q+=1
        if num == 2:
          raise ValueError('pagination limit exceeded; fail closed')
        return self.pr,CHECKS,[],self.files,'feat: docs'
    with patch.dict(sys.modules,{'protection_gate':m}):
      f=MixedQueue()
      self.assertEqual(run_auto(f, MAIN), 0)
      self.assertEqual(f.merges, [(1,SHA)])
      self.assertGreaterEqual(f.q, 3)

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_pagination_failure_never_merges_unverified_candidate(self):
    class OnlyOversized(FakeGH):
      def query_pr(self,num,head):
        raise ValueError('pagination limit exceeded; fail closed')
    f=OnlyOversized()
    self.assertEqual(run_auto(f, MAIN), 0)
    self.assertEqual(f.merges, [])

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_sensitive_paths_block(self):
    f=FakeGH(files=[{'filename':'legal/ledger/sources.json','status':'modified'}]);self.assertEqual(run_auto(f,MAIN),0);self.assertEqual(f.merges,[])

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_stale_list_base_is_rechecked_instead_of_silently_discarded(self):
    import sys, types
    m=types.ModuleType('protection_gate');m.allowed=lambda branch,rules:True
    with patch.dict(sys.modules,{'protection_gate':m}):
      f=FakeGH(base_sha='d'*40)
      self.assertEqual(run_auto(f, MAIN), 0)
      self.assertEqual(f.q, 2)
      self.assertEqual(f.merges, [(1,SHA)])

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_stale_base_with_fresh_nonmergeable_pr_never_merges(self):
    f=FakeGH(pr={**PR, 'mergeable_state':'behind'},base_sha='d'*40)
    self.assertEqual(run_auto(f, MAIN), 0)
    self.assertEqual(f.q, 1)
    self.assertEqual(f.merges, [])

  @patch.dict('os.environ', {'INTEGRATOR_APPLY':'true'})
  def test_stale_base_after_main_advances_is_not_merged(self):
    f=FakeGH()
    f.main='e'*40
    self.assertEqual(run_auto(f, MAIN), 0)
    self.assertEqual(f.merges, [])

