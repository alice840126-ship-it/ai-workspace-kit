import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from workspace.kit import init,bind,allow_root,run
from workspace.settings import repository,expected_origin
from workspace.bridge import Bridge
from workspace.demo import main as demo
from test_bridge import checkpoint
from argparse import Namespace

class KitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name).resolve();self.state=self.base/'state';self.memory=self.base/'memory'
    def tearDown(self):self.tmp.cleanup()
    def test_bridge_rejects_state_in_public_checkout(self):
        repo=self.base/'public';repo.mkdir();(repo/'.git').mkdir()
        result=Bridge(repo/'state').checkpoint(checkpoint())
        self.assertFalse(result['ok']);self.assertFalse((repo/'state').exists())
    def test_demo_complete_without_network(self):
        with patch('subprocess.run',side_effect=AssertionError('no external processes')),contextlib.redirect_stdout(io.StringIO()) as out:demo()
        self.assertTrue(json.loads(out.getvalue())['ok'])
    def test_init_refuses_existing_user_files(self):
        self.memory.mkdir();f=self.memory/'important.txt';f.write_text('preserve')
        with self.assertRaises(ValueError):init(self.memory,self.state)
        self.assertEqual(f.read_text(),'preserve')
    def test_init_rejects_state_under_memory(self):
        with self.assertRaisesRegex(ValueError,'separate_state'):init(self.memory,self.memory/'state')
    def test_init_rejects_state_in_git(self):
        self.state.mkdir();(self.state/'.git').mkdir()
        with self.assertRaisesRegex(ValueError,'state_inside_git'):init(self.memory,self.state)
    def test_existing_state_is_not_imported_by_accident(self):
        self.state.mkdir();(self.state/'unrelated').write_text('private')
        with self.assertRaisesRegex(ValueError,'state_directory_not_empty'):init(self.memory,self.state)
    def test_public_binding_rejected(self):
        init(self.memory,self.state)
        with patch('subprocess.run',return_value=subprocess.CompletedProcess([],0,'false\n','')):
            with self.assertRaisesRegex(ValueError,'private_repo_unverified'):bind(self.memory,self.state,'example/public')
        self.assertFalse((self.state/'github-repository.json').exists())
    def test_wrong_origin_rejected(self):
        init(self.memory,self.state)
        replies=[subprocess.CompletedProcess([],0,'true\n',''),subprocess.CompletedProcess([],0,'https://github.com/other/repo.git','')]
        with patch('subprocess.run',side_effect=replies):
            with self.assertRaisesRegex(ValueError,'unexpected_remote'):bind(self.memory,self.state,'example/private')
    def test_private_binding_is_configurable(self):
        init(self.memory,self.state)
        replies=[subprocess.CompletedProcess([],0,'true\n',''),subprocess.CompletedProcess([],0,'https://github.com/example/private.git','')]
        with patch('subprocess.run',side_effect=replies):bind(self.memory,self.state,'example/private')
        self.assertEqual(repository(self.state),'example/private');self.assertEqual(expected_origin(self.state),'https://github.com/example/private.git')
    def test_status_is_local_and_does_not_verify_remote(self):
        init(self.memory,self.state)
        with patch('subprocess.run',side_effect=AssertionError('status must stay local')):
            result=run(Namespace(command='status',memory=self.memory,state=self.state))
        self.assertEqual(result['publication']['state'],'not_configured')
    def test_checkpoint_promotes_and_tick_never_summarizes(self):
        init(self.memory,self.state);data=checkpoint();data['explicit_memory']=True
        args=Namespace(command='checkpoint',memory=self.memory,state=self.state)
        with patch('sys.stdin',io.StringIO(json.dumps(data))):result=run(args)
        self.assertEqual(result['warm']['promoted'],1)
        with patch('workspace.runtime.summarize',side_effect=AssertionError('no model')),patch('workspace.history.History.index',side_effect=AssertionError('no chat scan')):
            run(Namespace(command='tick',memory=self.memory,state=self.state))
        self.assertTrue((self.memory/'memory/bridge-test.md').is_file())
    def test_root_failure_does_not_change_existing_config(self):
        init(self.memory,self.state);docs=self.base/'documents';docs.mkdir();allow_root(self.state,docs,'demo')
        config=self.state/'artifact-roots.json';before=config.read_bytes()
        with self.assertRaises(ValueError):allow_root(self.state,Path.home(),'bad')
        self.assertEqual(before,config.read_bytes())
