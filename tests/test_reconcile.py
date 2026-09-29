import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import workspace.reconcile as reconcile
from workspace.core import Ledger,render,restore,import_refined,import_inbox,generated_files
from workspace.reconcile import prepare,verify_projection
from test_workspace import sample

class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve();self.ledgers=[]
        self.remote=self.base/'remote.git';self.cmd(self.base,'init','--bare','--initial-branch=main',str(self.remote))
        self.a=self.base/'a';self.cmd(self.base,'clone',str(self.remote),str(self.a));self.ident(self.a)
        self.la=self.ledger('la');self.la.record('initial','turn',sample(),stamp='2026-01-01T00:00:00+09:00')
        render(self.la,self.a);self.commit(self.a);self.cmd(self.a,'push','origin','main')
        self.b=self.base/'b';self.cmd(self.base,'clone',str(self.remote),str(self.b));self.ident(self.b)
        self.lb=self.ledger('lb');restore(self.lb,self.b);prepare(self.b,self.lb,check_origin=False)
    def tearDown(self):
        for l in self.ledgers:l.db.close()
        self.tmp.cleanup()
    def ledger(self,name):
        l=Ledger(self.base/name);self.ledgers.append(l);return l
    def cmd(self,path,*args,check=True):
        r=subprocess.run(['git','-C',str(path),*args],capture_output=True,text=True)
        if check and r.returncode:raise AssertionError(r.stderr)
        return r
    def ident(self,p):
        self.cmd(p,'config','user.name','Test');self.cmd(p,'config','user.email','test@localhost')
    def commit(self,p):self.cmd(p,'add','--all');self.cmd(p,'commit','-m','test')
    def advance(self):
        self.la.record('host-a','turn',sample(status=['다른 컴퓨터 변경']),stamp='2026-01-02T00:00:00+09:00')
        render(self.la,self.a);self.commit(self.a);self.cmd(self.a,'push','origin','main')
    def test_autosave_metadata_does_not_poison_main_history(self):
        from workspace.runtime import validate_published_history
        self.cmd(self.b,'checkout','-b','codex/autosave/test')
        p=self.b/'.codex-autosave';p.mkdir();(p/'manifest.json').write_text('{}')
        self.commit(self.b);self.cmd(self.b,'checkout','main')
        validate_published_history(self.b)
        self.cmd(self.b,'checkout','codex/autosave/test')
        with self.assertRaisesRegex(ValueError,'unallowlisted_history'):validate_published_history(self.b)
    def test_remote_union_and_session_group_stability(self):
        original=self.lb.events()[0]['session_group']
        self.lb.record('host-b','pending',sample(todo=['진행 중 작업']),stamp='2026-01-03T00:00:00+09:00');render(self.lb,self.b)
        self.advance();prepare(self.b,self.lb,check_origin=False);render(self.lb,self.b)
        self.assertEqual(len(self.lb.events()),3);self.assertEqual(self.lb.events()[0]['session_group'],original)
        self.assertIn('진행 중 작업',(self.b/'memory/prototype.md').read_text())
        roundtrip=self.ledger('roundtrip');restore(roundtrip,self.b);out=self.base/'roundtrip-out';render(roundtrip,out)
        self.assertEqual(generated_files(self.b),generated_files(out))
        self.assertTrue((self.lb.state/'receive-journal/transaction.json').exists())
    def test_remote_generated_manual_edit_blocks_before_checkout(self):
        (self.a/'memory/prototype.md').write_text('manual remote edit');self.commit(self.a);self.cmd(self.a,'push','origin','main')
        before=self.cmd(self.b,'rev-parse','HEAD').stdout
        with self.assertRaisesRegex(ValueError,'generated_manual_edit'):prepare(self.b,self.lb,check_origin=False)
        self.assertEqual(before,self.cmd(self.b,'rev-parse','HEAD').stdout)
    def test_local_manual_edit_blocks(self):
        p=self.b/'memory/prototype.md';p.write_text('local manual edit')
        with self.assertRaisesRegex(ValueError,'generated_manual_edit'):prepare(self.b,self.lb,check_origin=False)
        with self.assertRaisesRegex(ValueError,'generated_manual_edit'):render(self.lb,self.b)
        self.assertEqual(p.read_text(),'local manual edit')
    def test_edit_during_fetch_is_not_blessed_as_generated(self):
        original=reconcile.git
        def race(root,*args):
            result=original(root,*args)
            if args[0]=='fetch':(self.b/'memory/prototype.md').write_text('concurrent user edit')
            return result
        with patch.object(reconcile,'git',race):
            with self.assertRaisesRegex(ValueError,'generated_manual_edit'):prepare(self.b,self.lb,check_origin=False)
        self.assertEqual((self.b/'memory/prototype.md').read_text(),'concurrent user edit')
    def test_dirty_source_receive_blocks(self):
        self.advance();(self.b/'draft.md').write_text('local work')
        with self.assertRaisesRegex(ValueError,'dirty_receive_blocked'):prepare(self.b,self.lb,check_origin=False)
        self.assertEqual((self.b/'draft.md').read_text(),'local work')
    def test_concurrent_push_and_divergence_no_overwrite(self):
        self.lb.record('host-b','turn',sample(status=['로컬 완료']),stamp='2026-01-03T00:00:00+09:00');render(self.lb,self.b);self.commit(self.b)
        self.advance();remote_before=self.cmd(self.a,'rev-parse','HEAD').stdout
        self.assertNotEqual(self.cmd(self.b,'push','origin','main',check=False).returncode,0)
        local_before=self.cmd(self.b,'rev-parse','HEAD').stdout
        with self.assertRaisesRegex(ValueError,'diverged_history'):prepare(self.b,self.lb,check_origin=False)
        self.assertEqual(local_before,self.cmd(self.b,'rev-parse','HEAD').stdout)
        self.assertEqual(remote_before,self.cmd(self.a,'rev-parse','HEAD').stdout)
    def test_immutable_conflict_atomic(self):
        event=next((self.b/'events').glob('*.json'));data=json.loads(event.read_text());data[0]['memory']['status']=['수정 충돌'];event.write_text(json.dumps(data))
        before=self.lb.events()
        with self.assertRaisesRegex(ValueError,'immutable_event_conflict'):import_refined(self.lb,self.b)
        self.assertEqual(before,self.lb.events())
    def test_local_stage_and_remote_event_merge(self):
        with self.lb.db:self.lb.db.execute("insert into topics values('prototype','archive')")
        render(self.lb,self.b);self.advance();prepare(self.b,self.lb,check_origin=False)
        self.assertEqual(dict(self.lb.db.execute('select * from topics')),{'prototype':'archive'})
    def test_inbox_from_remote_is_imported_once_and_immutable(self):
        folder=self.a/'inbox';folder.mkdir();p=folder/('b'*24+'.json')
        p.write_text(json.dumps({'stamp':'2026-01-04T00:00:00+09:00','memory':sample(todo=['외부에서 추가한 작업'])}))
        self.commit(self.a);self.cmd(self.a,'push','origin','main')
        prepare(self.b,self.lb,check_origin=False)
        self.assertEqual(import_inbox(self.lb,self.b),1)
        self.assertEqual(import_inbox(self.lb,self.b),0)
        render(self.lb,self.b);self.assertIn('외부에서 추가한 작업',(self.b/'memory/prototype.md').read_text())
        local=self.b/'inbox'/p.name;data=json.loads(local.read_text());data['memory']['todo']=['기존 항목 변경'];local.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'immutable_inbox_conflict'):import_inbox(self.lb,self.b)
    def test_stage_conflict_does_not_import_remote_events(self):
        with self.lb.db:self.lb.db.execute("insert into topics values('prototype','archive')")
        render(self.lb,self.b)
        with self.la.db:self.la.db.execute("insert into topics values('prototype','project')")
        self.advance();before=self.lb.events()
        with self.assertRaisesRegex(ValueError,'stage_conflict'):prepare(self.b,self.lb,check_origin=False)
        self.assertEqual(before,self.lb.events())
    def test_missing_generated_file_is_not_silently_recreated(self):
        (self.b/'memory/prototype.md').unlink()
        with self.assertRaisesRegex(ValueError,'generated_manual_edit'):render(self.lb,self.b)
    def test_legacy_projection_is_verified_without_losing_groups(self):
        verify_projection(self.a)
        self.assertEqual(self.la.events()[0]['session_group'],self.lb.events()[0]['session_group'])

if __name__=='__main__':unittest.main()
