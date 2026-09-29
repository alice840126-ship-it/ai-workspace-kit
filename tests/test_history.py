import hashlib,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from workspace.history import History,ro,narrative

class HistoryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.h=History(self.root/'derived');self.file=self.root/'rollout.jsonl'
 def tearDown(self):self.h.close();self.tmp.cleanup()
 def write(self,values,mode='w'):
  with self.file.open(mode) as f:
   for v in values:f.write(json.dumps(v,ensure_ascii=False)+'\n')
 def meta(self):return {'type':'session_meta','payload':{'id':'test-session','cwd':'/tmp/project'}}
 def msg(self,text):return {'type':'response_item','timestamp':'2026-09-29T01:00:00Z','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':text}]}}
 def runfile(self):return self.h.file(self.file,time.monotonic()+5)
 def test_append_dedup_partial_and_readonly(self):
  self.write([self.meta(),self.msg('ExampleCo Slack 권한을 검토')]);before=self.file.read_bytes();self.runfile()
  self.assertEqual(before,self.file.read_bytes());self.assertEqual(self.runfile(),(0,0))
  self.assertEqual(len(self.h.search('ExampleCo Slack 권한')),1)
  with self.file.open('ab') as f:f.write(json.dumps(self.msg('DemoKit 이미지 생성'),ensure_ascii=False).encode())
  self.runfile();self.assertEqual(self.h.stats()['messages'],1)
  with self.file.open('ab') as f:f.write(b'\n')
  self.runfile();self.assertEqual(self.h.stats()['messages'],2);self.runfile();self.assertEqual(self.h.stats()['messages'],2)
 def test_replaced_file(self):
  self.write([self.meta(),self.msg('old')]);self.runfile();self.file.unlink();self.write([self.meta(),self.msg('new')]);self.runfile()
  self.assertEqual(self.h.search('old'),[]);self.assertTrue(self.h.search('new'))
 def test_nonconversation_and_secrets(self):
  self.assertIsNone(narrative({'type':'reasoning','text':'private'}));self.assertIsNone(narrative({'type':'function_call_output','text':'private'}));self.assertIsNone(narrative([]))
  self.write([[],self.meta(),self.msg('sample api_key=abcdefghijklmn'),{'type':'response_item','payload':{'type':'reasoning','text':'private'}}]);self.runfile()
  text=self.h.db.execute('select text from messages').fetchone()[0];self.assertNotIn('abcdefghijklmn',text)
 def test_fts_query_escaped(self):
  self.write([self.meta(),self.msg('DemoKit 이미지 생성')]);self.runfile();self.assertIsInstance(self.h.search('" OR *'),list)
 def setupnative(self):
  m=sqlite3.connect(self.root/'state_5.sqlite');m.execute('create table threads(id,cwd,git_origin_url,git_branch)');m.execute("insert into threads values('s1','/tmp/project','','main')");m.commit();m.close()
  h=sqlite3.connect(self.root/'thread_history_1.sqlite');h.executescript('create table thread_items(thread_id,turn_id,item_id,rollout_ordinal,created_at_ms,item_json,item_type,updated_at_ordinal);create table thread_realtime_items(thread_id,item_id,rollout_ordinal,created_at_ms,item_json,item_type);create table thread_history_projection_state(thread_id);insert into thread_history_projection_state values("s1");')
  h.execute('insert into thread_items values(?,?,?,?,?,?,?,?)',('s1','t1','i1',1,1000,json.dumps({'type':'agentMessage','text':'initial'}),'agentMessage',1));h.commit();return h
 def test_native_update_and_readonly(self):
  source=self.setupnative();before=(self.root/'thread_history_1.sqlite').read_bytes()
  self.h.native(self.root,time.monotonic()+5);self.assertEqual(before,(self.root/'thread_history_1.sqlite').read_bytes());self.assertTrue(self.h.search('initial'))
  source.execute('update thread_items set item_json=?,updated_at_ordinal=2',(json.dumps({'type':'agentMessage','text':'updated'}),));source.commit()
  self.h.native(self.root,time.monotonic()+5);self.assertEqual(self.h.search('initial'),[]);self.assertTrue(self.h.search('updated'));self.assertEqual(self.h.native(self.root,time.monotonic()+5)[0],0)
  c=ro(self.root/'thread_history_1.sqlite')
  with self.assertRaises(sqlite3.OperationalError):c.execute('delete from thread_items')
  c.close();source.close()
 def test_voice(self):
  source=self.setupnative();source.execute('insert into thread_realtime_items values(?,?,?,?,?,?)',('s1','voice1',3,2000,json.dumps({'type':'transcript_segment','role':'user','text':'음성 기억'}),'transcript_segment'));source.commit()
  self.h.native(self.root,time.monotonic()+5);self.assertTrue(self.h.search('음성 기억'));source.close()

 def test_composite_native_cursor_resumes_ties(self):
  source=self.setupnative()
  for i in range(2,15):
   source.execute('insert into thread_items values(?,?,?,?,?,?,?,?)',('s1','t1',str(i),i,1000,json.dumps({'type':'agentMessage','text':'message '+str(i)}),'agentMessage',1))
  source.commit()
  self.h.db.execute('insert into cursors values(?,?,?,?)',('s1','native',1,7));self.h.db.commit()
  self.h.native(self.root,time.monotonic()+5)
  # Read the boundary and rows following it, rather than replaying the whole tie group.
  self.assertEqual(self.h.db.execute('select count(*) from messages').fetchone()[0],8)
  source.close()
 def test_projection_change_gets_priority(self):
  source=self.setupnative();source.execute('alter table thread_history_projection_state add column next_rollout_ordinal integer default 10');source.commit()
  self.h.native(self.root,time.monotonic()+5)
  self.assertEqual(self.h.db.execute('select tail from native_tail where sid="s1"').fetchone()[0],10)
  source.execute('update thread_history_projection_state set next_rollout_ordinal=20');source.commit();self.h.native(self.root,time.monotonic()+5)
  self.assertEqual(self.h.db.execute('select tail from native_tail where sid="s1"').fetchone()[0],20);source.close()

 def test_changed_late_file_prioritized_under_budget(self):
  from unittest.mock import patch
  home=self.root/'home';folder=home/'sessions';folder.mkdir(parents=True);(home/'archived_sessions').mkdir()
  for name in ('a','b','z'):
   self.file=folder/(name+'.jsonl');self.write([{'type':'session_meta','payload':{'id':name}},self.msg('original')]);self.runfile()
  self.write([self.msg('newlyadded')],mode='a')
  original=self.h.file
  def slow_file(path,deadline):
   result=original(path,deadline);time.sleep(.06);return result
  with patch.object(self.h,'native',return_value=(0,0)),patch.object(self.h,'file',side_effect=slow_file):self.h.index(home,budget=.05)
  self.assertTrue(self.h.search('newlyadded'))

if __name__=='__main__':unittest.main()
