import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from workspace.core import Ledger
from workspace.runtime import collect,process
from workspace.alerts import held_counts
from test_workspace import sample

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.l=Ledger(self.root/'ledger');self.l.set('since',200)
        self.home=self.root/'fake-codex';self.home.mkdir()
        m=sqlite3.connect(self.home/'state_5.sqlite');m.execute('create table threads(id,agent_role,source)');m.execute("insert into threads values('s',null,'app')");m.commit();m.close()
        self.h=sqlite3.connect(self.home/'thread_history_1.sqlite');self.h.execute('create table thread_turns(thread_id,turn_id,completed_at,status,final_agent_item_id)');self.h.execute('create table thread_items(thread_id,turn_id,item_id,item_json)')
    def tearDown(self):self.h.close();self.l.db.close();self.tmp.cleanup()
    def add(self,turn,status='completed',text='작업 완료',stamp=3000000000000,attempts=0):
        eid=hashlib.sha256(('s:'+turn).encode()).hexdigest()[:24]
        self.h.execute('insert into thread_turns values(?,?,?,?,?)',('s',turn,stamp,status,'f'))
        self.h.execute('insert into thread_items values(?,?,?,?)',('s',turn,'f',json.dumps({'type':'agentMessage','phase':'final_answer','text':text})));self.h.commit()
        with self.l.db:self.l.db.execute('insert into attempts values(?,?,?)',(eid,'held',attempts))
        return eid
    def test_default_never_retries_held_and_limit_is_preserved(self):
        self.add('old',stamp=100);self.add('allowed');self.add('exhausted',attempts=3)
        self.assertEqual(collect(self.l,self.home),[])
        self.assertEqual([r[1] for r in collect(self.l,self.home,retry_held=True)],['allowed'])
    def test_retry_keeps_sensitive_and_incomplete_prefilters(self):
        self.add('sensitive',text='test@example.com');self.add('incomplete',status='interrupted')
        self.assertEqual(collect(self.l,self.home,retry_held=True),[])
        self.assertEqual(held_counts(self.l),{'source_incomplete':1,'source_sensitive':1})
        self.assertEqual([r[0] for r in self.l.db.execute('select attempts from attempts')],[1,1])
    def test_retry_validation_is_not_relaxed(self):
        self.add('link')
        with patch('workspace.runtime.summarize',side_effect=ValueError('unapproved_link')):
            self.assertEqual(process(self.l,self.home,retry_held=True),0)
        self.assertEqual(held_counts(self.l),{'unapproved_link':1});self.assertEqual(self.l.events(),[])
    def test_valid_retry_commits_only_refined_memory(self):
        self.add('good')
        with patch('workspace.runtime.summarize',return_value=sample()):
            self.assertEqual(process(self.l,self.home,retry_held=True),1)
        self.assertEqual(len(self.l.events()),1);self.assertEqual(held_counts(self.l),{})
    def test_provider_block_cannot_be_bypassed(self):
        self.l.set('compaction_blocked','true')
        with patch('workspace.runtime.collect') as get:
            with self.assertRaisesRegex(ValueError,'compaction_blocked'):process(self.l,self.home,retry_held=True)
            get.assert_not_called()
    def test_monotonic_budget_leaves_next_attempt_unstarted(self):
        first=self.add('first');second=self.add('second')
        with patch('workspace.runtime.time.monotonic',side_effect=[0,1,12]),patch('workspace.runtime.summarize',return_value=sample()) as summarize:
            self.assertEqual(process(self.l,self.home,retry_held=True,budget_seconds=100),1)
            self.assertEqual(summarize.call_count,1)
        self.assertEqual(self.l.db.execute('select status,attempts from attempts where id=?',(second,)).fetchone(),('held',0))
        self.assertEqual(self.l.get('compaction_budget_deferred'),'true')

if __name__=='__main__':unittest.main()
