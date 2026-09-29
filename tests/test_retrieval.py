import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from workspace.core import Ledger
from workspace.retrieval import recall,maintenance
from workspace.history import History

class RetrievalTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.l=Ledger(self.root/'state')
 def tearDown(self):self.l.db.close();self.tmp.cleanup()
 def test_warm_short_circuit(self):
  with patch('workspace.retrieval.query_warm',return_value=[{'topic':'alpha'}]),patch('workspace.retrieval.History') as cold:
   self.assertEqual(recall(self.l,'alpha')['layer'],'warm');cold.assert_not_called()
 def test_refined_short_circuit(self):
  d={'topic':'alpha','repo':'','business':False,'sensitive':False,**{k:[] for k in ['context','status','decisions','todo','failed_approaches','links','completed_todo']}};d['status']=['검증 완료'];self.l.record('session','turn',d)
  with patch('workspace.retrieval.History') as cold:
   self.assertEqual(recall(self.l,'alpha')['layer'],'refined');cold.assert_not_called()
 def test_newer_refined_replaces_stale_warm_without_cold(self):
  d={'topic':'alpha','repo':'','business':False,'sensitive':False,**{k:[] for k in ['context','status','decisions','todo','failed_approaches','links','completed_todo']}}
  d['status']=['최신 완료'];self.l.record('s','t',d,'2026-09-29T12:00:00+09:00')
  warm={'topic':'alpha','stamp':'2026-09-29T11:00:00+09:00','source':'aside','memory':{'status':['진행 중']}}
  with patch('workspace.retrieval.query_warm',return_value=[warm,warm]),patch('workspace.retrieval.History') as cold:
   result=recall(self.l,'alpha');self.assertEqual(result['layer'],'refined');self.assertEqual(len(result['results']),1)
   self.assertEqual(result['results'][0]['memory']['status'],['최신 완료']);self.assertIn('stamp',result['results'][0]);cold.assert_not_called()
  warm['stamp']='2026-09-29T04:00:00+00:00'
  with patch('workspace.retrieval.query_warm',return_value=[warm]),patch('workspace.retrieval.History') as cold:
   self.assertEqual(recall(self.l,'alpha')['layer'],'warm');cold.assert_not_called()
 def test_disabled_maintenance(self):
  with patch('workspace.retrieval.History') as cold:
   maintenance(self.l,self.root,self.root);cold.assert_not_called()
 def test_no_git_index(self):
  p=self.root/'repo';(p/'.git').mkdir(parents=True)
  with self.assertRaisesRegex(ValueError,'outside_git'):History(p/'state')

class IsolationTests(unittest.TestCase):
 def test_new_failure_preserves_base_engine(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);l=Ledger(root/'state');(l.state/'retrieval-enabled').touch()
   with patch('workspace.retrieval.repositories',return_value=set()),patch('workspace.retrieval.collect_warm',return_value={}),patch('workspace.retrieval.History',side_effect=ValueError('private untrusted text')):
    maintenance(l,root,root)
   status=json.loads(l.get('history_last_index'));self.assertEqual(status['code'],'ValueError');self.assertEqual(status['status'],'error');self.assertIn('time',status);self.assertEqual(l.get('history_last_error'),l.get('history_last_index'));l.close() if hasattr(l,'close') else l.db.close()
 def test_old_decision_stays_refined(self):
  with tempfile.TemporaryDirectory() as folder:
   l=Ledger(Path(folder)/'state');p={'topic':'alpha','repo':'','business':False,'sensitive':False,**{k:[] for k in ['context','status','decisions','todo','failed_approaches','links','completed_todo']}}
   p['decisions']=['예전 권한 설계'];l.record('one','a',p);p['decisions']=[];p['status']=['다른 상태'];l.record('two','a',p)
   with patch('workspace.retrieval.History') as cold:
    self.assertEqual(recall(l,'권한 설계')['layer'],'refined');cold.assert_not_called()
   l.db.close()
