import asyncio
import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from workspace.bridge import Bridge,create_server,audit_artifact_call
from workspace.core import Ledger,now


def checkpoint():
    return dict(version=1,source='aside',session='test-session',checkpoint='milestone',stamp=now(),kind='confirmed_summary',verified=True,explicit_memory=False,next_context='다음 검증',memory=dict(topic='bridge-test',repo='',business=False,sensitive=False,context=['브리지 구조 검증'],status=['확인 완료'],decisions=['정제 기억만 공유한다'],todo=[],failed_approaches=[],links=[],completed_todo=[]))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name).resolve()/'state';self.bridge=Bridge(self.state)
    def tearDown(self):self.tmp.cleanup()
    def test_write_is_local_only_and_idempotent(self):
        data=checkpoint();first=self.bridge.checkpoint(data);second=self.bridge.checkpoint(data)
        self.assertTrue(first['changed']);self.assertFalse(second['changed']);self.assertFalse(first['promoted'])
        ledger=Ledger(self.state)
        try:self.assertEqual(ledger.events(),[])
        finally:ledger.db.close()
        self.assertFalse((self.state/'history').exists())
    def test_recall_never_calls_cold_even_on_miss(self):
        with patch('workspace.retrieval.History',side_effect=AssertionError('Cold forbidden')):
            self.assertEqual(self.bridge.recall('missing')['layer'],'none')
            self.bridge.checkpoint(checkpoint())
            result=self.bridge.recall('브리지')
            self.assertTrue(result['ok']);self.assertEqual(result['layer'],'warm')
            self.assertFalse(result['cold_searched'])
        self.assertFalse((self.state/'history').exists())
    def test_refined_without_cold(self):
        self.state.mkdir();ledger=Ledger(self.state)
        try:ledger.record('session','turn',checkpoint()['memory'])
        finally:ledger.db.close()
        with patch('workspace.retrieval.History',side_effect=AssertionError('Cold forbidden')):
            self.assertEqual(self.bridge.recall('브리지')['layer'],'refined')
    def test_natural_request_keeps_topic_keywords(self):
        from workspace.bridge import query_keywords
        self.assertEqual(query_keywords('예전에 ExampleCo Slack 권한 얘기한것찾아봐'),'ExampleCo Slack 권한')
        self.assertEqual(query_keywords('DemoKit 어디까지 했어?'),'DemoKit')
        self.assertEqual(query_keywords('2026 ExampleCo 권한'),'2026 ExampleCo 권한')
        self.assertEqual(query_keywords('ExampleCo 어디까지 했지?'),'ExampleCo')
        self.assertEqual(query_keywords('전에 DemoKit 이어서 하자'),'DemoKit')
        self.assertEqual(query_keywords('ExampleCo 권한 작업 이어서 해줘'),'ExampleCo 권한')
        self.bridge.checkpoint(checkpoint())
        self.assertEqual(self.bridge.recall('예전에 브리지 이야기했던 거 찾아줘')['layer'],'warm')
    def test_secret_and_raw_rejection_does_not_echo_input(self):
        for text in ['user: raw transcript','person@example.com','/Users/private/data']:
            data=checkpoint();data['memory']['status']=[text]
            result=self.bridge.checkpoint(data)
            self.assertFalse(result['ok']);self.assertNotIn(text,json.dumps(result))
    def test_existing_scheduler_lock_is_respected(self):
        self.state.mkdir()
        with (self.state/'lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=self.bridge.checkpoint(checkpoint())
            self.assertEqual(result['code'],'workspace_busy')
        self.assertTrue(self.bridge.health()['ok'])
    def test_errors_do_not_expose_local_details(self):
        with patch('workspace.bridge.recall',side_effect=RuntimeError('/Users/private traceback secret')):
            result=self.bridge.recall('test')
        self.assertEqual(result,{'ok':False,'code':'workspace_request_rejected','retryable':False})
    def test_health_has_no_paths_or_source_content(self):
        result=self.bridge.health();self.assertFalse(result['cold_enabled']);self.assertEqual(result['transport'],'stdio')
        self.assertNotIn(str(self.state),json.dumps(result))
        self.assertEqual(result['publication']['state'],'not_configured')
    def test_publication_receipt_does_not_claim_live_remote_freshness(self):
        self.state.mkdir();(self.state/'github-repository.json').write_text('{}')
        ledger=Ledger(self.state)
        try:
            ledger.set('remote_verified','a'*40);ledger.set('synced_at',now());ledger.set('published_event_count',0)
        finally:ledger.db.close()
        self.assertEqual(self.bridge.health()['publication']['state'],'last_sync_verified')
        self.assertEqual(self.bridge.recall('브리지')['publication']['verification_scope'],'last_successful_sync_only')
        ledger=Ledger(self.state)
        try:ledger.record('session','turn',checkpoint()['memory'])
        finally:ledger.db.close()
        self.assertEqual(self.bridge.health()['publication']['state'],'local_refined_updates_after_sync')
        self.assertEqual(self.bridge.health()['publication']['last_verified_commit'],'a'*12)
    def test_recall_audit_records_layer_without_query_or_content(self):
        self.state.mkdir()
        audit_artifact_call(self.state,'recall',{'ok':True,'layer':'warm','results':[{'text':'synthetic private summary'}]})
        saved=json.loads((self.state/'bridge-call-audit.jsonl').read_text())
        self.assertEqual(saved['tool'],'workspace_recall')
        self.assertEqual(saved['layer'],'warm')
        self.assertEqual(saved['result_count'],1)
        self.assertNotIn('synthetic private summary',json.dumps(saved))
    def test_symlinked_ledger_blocked(self):
        self.state.mkdir();target=Path(self.tmp.name).resolve()/'other';target.write_text('untouched')
        (self.state/'ledger.sqlite').symlink_to(target)
        self.assertFalse(self.bridge.health()['ok']);self.assertEqual(target.read_text(),'untouched')
    def test_opt_in_cold_sanitizes_excerpts_and_locators(self):
        bridge=Bridge(self.state,allow_cold=True)
        fixture={'layer':'cold','cold_searched':True,'results':[{
            'date':'2026-09-29','project':'','session':'session-id','score':-2,
            'working_directory':'/Users/private/project','branch':'branch',
            'source':{'database':'/Users/private/history.sqlite','offset':1},
            'context':[{'role':'user','text':'확인 /tmp/private-file person@example.com','locator':{'path':'/Volumes/SSD/raw'},'truncated':False}]}]}
        with patch('workspace.bridge.recall',return_value=fixture) as call:
            result=bridge.recall('확인')
        self.assertTrue(call.call_args.kwargs['allow_cold']);self.assertTrue(result['ok'])
        encoded=json.dumps(result)
        for forbidden in ('working_directory','locator','/Users/','/Volumes/','/tmp/','person@example.com'):
            self.assertNotIn(forbidden,encoded)
        item=result['results'][0]
        self.assertEqual(len(item['source_id']),24);self.assertEqual(item['session'],'session-id')
        self.assertTrue(bridge.health()['cold_enabled'])

    def test_common_credentials_rejected_and_cold_redacted(self):
        credentials=[
            'Cookie: session=synthetic-browser-cookie',
            'Set-Cookie: session=synthetic; HttpOnly',
            'Authorization: Basic synthetic-test-value',
            'session=synthetic-browser-cookie',
            'cookie="synthetic-cookie"',
            'token: synthetic-token',
            '{"session":"synthetic-cookie"}',
            '{"password":"synthetic-password"}',
            'xoxb-'+'synthetic-example-only',
            'AKIA'+'A'*16,
            'AIza'+'x'*35,
        ]
        for value in credentials:
            with self.subTest(shape=value[:10]):
                data=checkpoint();data['memory']['status']=[value]
                self.assertFalse(self.bridge.checkpoint(data)['ok'])
                fixture={'layer':'cold','cold_searched':True,'results':[{'session':'s','date':'2026-09-29','project':'','score':-1,'source':{},'context':[{'role':'user','text':value}]}]}
                with patch('workspace.bridge.recall',return_value=fixture):
                    result=Bridge(self.state,allow_cold=True).recall('test')
                self.assertTrue(result['ok']);self.assertNotIn(value,json.dumps(result))

    def test_unix_windows_paths_masked_and_urls_dates_preserved(self):
        from workspace.core import safe,redact_local_paths
        paths=['/etc/secret','/srv/private','/mnt/archive','/root/file',r'C:\Users\Example\file',r'\\server\share\file',r'\\?\C:\private\file','~/private','/custom-root/file','file:///etc/private-test','path:/srv/private-test']
        for value in paths:
            with self.subTest(shape=value):
                with self.assertRaises(ValueError):safe(value)
                self.assertNotIn(value,redact_local_paths(value))
        for value in ['https://github.com/example/repo/blob/main/file.py','2026/09/29','1/2','a / b','../daily/2026-09-29.md']:
            self.assertEqual(safe(value),value)
            self.assertEqual(redact_local_paths(value),value)
        from workspace.core import SECRET
        self.assertIsNone(SECRET.search('"session": "stable-conversation-id"'))

    def test_sdk_protocol_in_memory(self):
        try:from mcp import Client
        except ImportError:self.skipTest('run in workspace-bridge environment for SDK tests')
        async def run():
            async with Client(create_server(self.state,audit_calls=True)) as client:
                tools=await client.list_tools()
                self.assertEqual({t.name for t in tools.tools},{'workspace_recall','workspace_checkpoint','workspace_health','search_local','read_local_artifact'})
                result=await client.call_tool('workspace_checkpoint',{'checkpoint':checkpoint()})
                self.assertFalse(result.is_error);self.assertTrue(result.structured_content['ok'])
                recalled=await client.call_tool('workspace_recall',{'query':'브리지'})
                self.assertEqual(recalled.structured_content['layer'],'warm')
                audits=[json.loads(line) for line in (self.state/'bridge-call-audit.jsonl').read_text().splitlines()]
                self.assertEqual(audits[-1]['tool'],'workspace_recall')
                self.assertEqual(audits[-1]['layer'],'warm')
                invalid=await client.call_tool('workspace_recall',{'query':{'private':'/Users/private/example'}})
                self.assertNotIn('/Users/private/example',str(invalid))
                self.assertFalse(invalid.structured_content['ok'])
                invalid=await client.call_tool('workspace_checkpoint',{})
                self.assertFalse(invalid.structured_content['ok'])
                health=await client.call_tool('workspace_health',{})
                self.assertFalse(health.structured_content['cold_enabled'])
        asyncio.run(run())
    def test_sdk_stdio_real_subprocess(self):
        try:from mcp import Client,StdioServerParameters
        except ImportError:self.skipTest('run in workspace-bridge environment for SDK tests')
        async def run():
            script=Path(__file__).resolve().parents[1]/'workspace/bridge.py'
            server=StdioServerParameters(command=sys.executable,args=[str(script),'--state',str(self.state)],cwd=self.tmp.name)
            async with Client(server) as client:
                result=await client.call_tool('workspace_health',{})
                self.assertTrue(result.structured_content['ok']);self.assertFalse(result.structured_content['cold_enabled'])
        asyncio.run(run())

if __name__=='__main__':unittest.main()

class ArtifactProtocolTests(unittest.TestCase):
    def test_read_only_server_search_then_fresh_read(self):
        try:from mcp import Client
        except ImportError:self.skipTest('MCP SDK required')
        from workspace.artifacts import ArtifactIndex
        async def run(state,root):
            async with Client(create_server(state,read_only=True)) as client:
                listed=await client.list_tools()
                names={t.name for t in listed.tools}
                self.assertNotIn('workspace_checkpoint',names)
                self.assertIn('search_local',names);self.assertIn('workspace_recall',names)
                found=await client.call_tool('search_local',{'query':'ExampleCo 견적서'})
                result=found.structured_content['results'][0]
                self.assertEqual(result['path'],str(root/'quote.txt'))
                read=await client.call_tool('read_local_artifact',{'artifact_id':result['id']})
                self.assertIn('교육 3회',read.structured_content['text'])
                (root/'quote.txt').write_text('changed')
                stale=await client.call_tool('read_local_artifact',{'artifact_id':result['id']})
                self.assertEqual(stale.structured_content['status'],'source_changed_reindex_required')
                invalid=await client.call_tool('read_local_artifact',{'artifact_id':'/etc/passwd'})
                self.assertNotIn('/etc/passwd',str(invalid))
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve();state=base/'state';state.mkdir();root=base/'work';root.mkdir()
            (root/'quote.txt').write_text('ExampleCo 견적서 교육 3회')
            st=root.stat();(state/'artifact-roots.json').write_text(json.dumps({'roots':[dict(path=str(root),label='ExampleCo',device=st.st_dev,inode=st.st_ino)]}))
            index=ArtifactIndex(state)
            try:index.index()
            finally:index.close()
            asyncio.run(run(state,root))


class CallAuditTests(unittest.TestCase):
    def test_metadata_only_and_success_after_read(self):
        with tempfile.TemporaryDirectory() as directory:
            result = {'status': 'ok', 'id': 'a' * 32, 'text': 'private source secret',
                      'path': '/private/source', 'error': 'private error'}
            self.assertIs(audit_artifact_call(directory, 'read', result), result)
            path = Path(directory) / 'bridge-call-audit.jsonl'
            logged = json.loads(path.read_text())
            self.assertTrue(logged['ok']); self.assertTrue(logged['text_returned'])
            self.assertEqual(logged['artifact_id'], 'a' * 32)
            self.assertNotIn('private', path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            audit_artifact_call(directory, 'read', {'status': 'not_found', 'id': 'secret-invalid-id'})
            failed = json.loads(path.read_text().splitlines()[-1])
            self.assertFalse(failed['ok']); self.assertFalse(failed['text_returned'])
            self.assertNotIn('artifact_id', failed)

    def test_no_symlink_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / 'target'; target.write_text('unchanged')
            (root / 'bridge-call-audit.jsonl').symlink_to(target)
            with patch('sys.stderr'):
                audit_artifact_call(root, 'search', {'status': 'ok', 'results': []})
            self.assertEqual(target.read_text(), 'unchanged')

    def test_fifo_does_not_block_read_completion(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            os.mkfifo(Path(directory) / 'bridge-call-audit.jsonl')
            code = "from workspace.bridge import audit_artifact_call; import sys; audit_artifact_call(sys.argv[1], 'read', {'status':'ok','text':'body'})"
            result = subprocess.run([sys.executable, '-c', code, directory], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b'workspace_call_audit_unavailable', result.stderr)
