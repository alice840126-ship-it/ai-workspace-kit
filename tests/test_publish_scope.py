from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import workspace.runtime as runtime
import workspace.reconcile as reconcile
from workspace.core import render
import test_reconcile as fixtures
from test_workspace import sample

class PublishScopeTests(unittest.TestCase):
    setUp=fixtures.ReconcileTests.setUp
    tearDown=fixtures.ReconcileTests.tearDown
    ledger=fixtures.ReconcileTests.ledger
    cmd=fixtures.ReconcileTests.cmd
    ident=fixtures.ReconcileTests.ident
    commit=fixtures.ReconcileTests.commit
    def publish(self,include_source):
        run=subprocess.run;git=runtime.git;prepare=reconcile.prepare
        def offline(args,*pos,**kw):
            if args[0]=='gh':return subprocess.CompletedProcess(args,0,'true\n','')
            if args[0]=='gitleaks':return subprocess.CompletedProcess(args,0,'','')
            return run(args,*pos,**kw)
        def origin(root,*args):
            if args==('remote','get-url','origin'):return 'https://github.com/example/private-memory.git'
            return git(root,*args)
        with patch('workspace.settings.repository',return_value='example/private-memory'),patch.object(runtime.subprocess,'run',offline),patch.object(runtime,'git',origin),patch.object(reconcile,'prepare',lambda root,l:prepare(root,l,check_origin=False)):
            return runtime.publish(self.b,self.lb,include_source=include_source)
    def edit_source(self):
        p=self.b/'workspace/in-progress.py';p.parent.mkdir();p.write_text('unfinished = True\n');return p
    def test_tick_publishes_memory_without_staging_source(self):
        source=self.edit_source();self.lb.record('new','work',sample(status=['정제된 상태']),stamp='2026-01-03T00:00:00+09:00');render(self.lb,self.b)
        sha=self.publish(False)
        self.assertEqual(source.read_text(),'unfinished = True\n')
        self.assertIn('workspace/',self.cmd(self.b,'status','--porcelain').stdout)
        self.assertEqual(self.cmd(self.b,'diff','--cached','--name-only').stdout,'')
        self.assertNotEqual(self.cmd(self.b,'show',sha+':workspace/in-progress.py',check=False).returncode,0)
        self.assertIn('정제된 상태',self.cmd(self.b,'show',sha+':memory/prototype.md').stdout)
        self.assertNotIn('workspace/in-progress.py',self.cmd(self.b,'log','-1','--pretty=format:','--name-only').stdout)
    def test_explicit_sync_can_publish_verified_source(self):
        self.edit_source();sha=self.publish(True)
        self.assertIn('unfinished',self.cmd(self.b,'show',sha+':workspace/in-progress.py').stdout)
        self.assertEqual(self.cmd(self.b,'status','--porcelain').stdout,'')
    def test_tick_does_not_push_preexisting_source_commit(self):
        self.edit_source();self.commit(self.b)
        remote=self.cmd(self.b,'ls-remote','origin','refs/heads/main').stdout
        with self.assertRaisesRegex(ValueError,'source_publish_requires_explicit_sync'):self.publish(False)
        self.assertEqual(self.cmd(self.b,'ls-remote','origin','refs/heads/main').stdout,remote)

if __name__=='__main__':unittest.main()
