import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from workspace.core import Ledger,validate,render,query,topic_states,KST,restore
from workspace.runtime import collect,select_model

def sample(**kw):
    d=dict(topic='prototype',repo='',business=False,sensitive=False,context=['작업 흐름 검증'],status=['검증 완료'],decisions=[],todo=[],failed_approaches=[],links=[],completed_todo=[]);d.update(kw);return d

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.l=Ledger(self.root/'state')
    def tearDown(self):self.l.db.close();self.tmp.cleanup()
    def test_privacy_and_schema(self):
        for text in ['담당자 홍길동, 서울특별시 강남구 테헤란로 123, 계좌 1234567890123','test@example.com','010-1234-5678','/Users/sample/private','password=unknownpassword','https://a.test/?token=notallowed']:
            with self.assertRaises(ValueError):validate(sample(status=[text]))
        with self.assertRaises(ValueError):validate(sample(topic='../escape'))
        with self.assertRaises(ValueError):validate(sample(sensitive=True))
        with self.assertRaises(ValueError):validate(sample(links=['https://private.test']))
    def test_idempotence_conflict(self):
        self.assertTrue(self.l.record('s1','t1',sample())[1]);self.assertFalse(self.l.record('s1','t1',sample())[1])
        with self.assertRaises(ValueError):self.l.record('s1','t1',sample(status=['변경']))
    def test_lifecycle_and_latest(self):
        self.l.record('s1','t1',sample());self.assertEqual(topic_states(self.l.events())['prototype']['stage'],'session')
        self.l.record('s2','t2',sample(todo=['다음 검증'],decisions=['원본은 로컬에 둔다: 개인정보 보호']))
        states=render(self.l,self.root/'repo');self.assertEqual(states['prototype']['stage'],'candidate')
        self.assertIn('prototype',query(self.l,'새 프로젝트 후보?'))
        self.l.record('s3','t3',sample(repo='prototype',todo=[],completed_todo=['다음 검증']));render(self.l,self.root/'repo')
        body=(self.root/'repo/memory/prototype.md').read_text();self.assertIn('Stage: project',body);self.assertIn('개인정보 보호',body)
        self.assertNotIn('다음 검증',body.split('## TODO')[1].split('## FAILED')[0])
        # Source IDs and raw chats are not exported.
        exported=(self.root/'repo/events'/f'{dt.datetime.now(KST).date()}.json').read_text();self.assertNotIn('"session"',exported)
    def test_symlink_protection(self):
        out=self.root/'repo';out.mkdir();(out/'INDEX.md').symlink_to(self.root/'outside')
        with self.assertRaises(ValueError):render(self.l,out)
    def test_native_scope_and_dedup(self):
        home=self.root/'codex';home.mkdir();m=sqlite3.connect(home/'state_5.sqlite');m.execute('create table threads(id,agent_role,source)');m.execute("insert into threads values('s1',null,'app')");m.commit();m.close()
        h=sqlite3.connect(home/'thread_history_1.sqlite');h.execute('create table thread_turns(thread_id,turn_id,completed_at,status,final_agent_item_id)');h.execute('create table thread_items(thread_id,turn_id,item_id,item_json)')
        for t,stamp in [('old',100),('new',3000000000000)]:
            h.execute('insert into thread_turns values(?,?,?,?,?)',('s1',t,stamp,'completed','f'))
            h.execute('insert into thread_items values(?,?,?,?)',('s1',t,'f',json.dumps({'type':'agentMessage','phase':'final_answer','text':'작업 완료'})))
        h.commit();h.close();self.l.set('since',200)
        rows=collect(self.l,home);self.assertEqual([x[1] for x in rows],['new'])
        self.l.record('s1','new',sample());self.assertEqual(collect(self.l,home),[])
    def test_parent_symlink(self):
        out=self.root/'repo';out.mkdir();outside=self.root/'outside';outside.mkdir();(out/'memory').symlink_to(outside)
        self.l.record('s1','t1',sample())
        with self.assertRaises(ValueError):render(self.l,out)
        self.assertFalse((outside/'prototype.md').exists())
    def test_todo_survives_unrelated_update(self):
        self.l.record('s1','t1',sample(todo=['미완료 작업']))
        self.l.record('s1','t2',sample(status=['추가 확인']))
        self.assertIn('미완료 작업',topic_states(self.l.events())['prototype']['latest']['todo'])
    def test_project_does_not_regress(self):
        self.l.record('s1','t1',sample(repo='prototype',todo=['미완료 작업']))
        self.l.record('s1','t2',sample(status=['후속 확인']))
        result=topic_states(self.l.events())['prototype']
        self.assertEqual(result['stage'],'project');self.assertEqual(result['latest']['repo'],'prototype')
    def test_restore_from_refined_events(self):
        self.l.record('s1','t1',sample());self.l.record('s2','t2',sample(todo=['유지'],decisions=['결정 이유']))
        render(self.l,self.root/'repo');other=Ledger(self.root/'restored')
        self.assertEqual(restore(other,self.root/'repo'),2)
        self.assertEqual(topic_states(other.events())['prototype']['stage'],'candidate')
        with self.assertRaises(ValueError):restore(other,self.root/'repo')
        other.db.close()
    def test_model_pair_from_catalog(self):
        m={'slug':'current-efficient','description':'Fast and affordable model for easier tasks.','priority':3,'default_reasoning_level':'medium','supported_reasoning_levels':[{'effort':'medium'}]}
        self.assertEqual(select_model({'models':[m]}),('current-efficient','medium'))
        m['supported_reasoning_levels']=[]
        with self.assertRaises(RuntimeError):select_model({'models':[m]})
    def test_business_candidate(self):
        self.l.record('s1','t1',sample(business=True,todo=['고객 흐름 검증'],decisions=['조회부터 구현']))
        self.assertEqual(topic_states(self.l.events())['prototype']['stage'],'candidate')

if __name__=='__main__':unittest.main()
