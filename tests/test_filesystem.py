import asyncio
import base64
import errno
import json
import os
import subprocess
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from workspace.filesystem import Filesystem, snapshot, rename_atomic
from workspace.bridge import create_server


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.fs = Filesystem(self.root/'state')
        self.path = self.root/'sample.txt'

    def tearDown(self): self.temp.cleanup()

    def create(self, content='first'):
        result = self.fs.call('write', path=str(self.path), content=content, expected_version='missing')
        self.assertTrue(result['ok'], result)
        return result

    def test_create_edit_read_diff_restore(self):
        first = self.create()
        edited = self.fs.call('edit', path=str(self.path), old_text='first', new_text='second', expected_version=first['after']['version'])
        self.assertTrue(edited['verified'], edited)
        read = self.fs.call('read', path=str(self.path))
        self.assertEqual(read['content'], 'second')
        diff = self.fs.call('diff', operation_id=edited['operation_id'])
        self.assertIn('-first', diff['diff'])
        restored = self.fs.call('restore', operation_id=edited['operation_id'], expected_version=read['version'])
        self.assertTrue(restored['verified'], restored)
        self.assertEqual(self.path.read_text(), 'first')
        history = self.fs.call('history')
        self.assertEqual(len(history['operations']), 3)
        self.assertNotIn('second', json.dumps(history))

    def test_same_size_mtime_concurrent_change_is_detected(self):
        first = self.create('AAAA'); info = self.path.stat()
        self.path.write_text('BBBB'); os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
        result = self.fs.call('write', path=str(self.path), content='CCCC', expected_version=first['after']['version'])
        self.assertEqual(result['code'], 'version_conflict')
        self.assertEqual(self.path.read_text(), 'BBBB')

    def test_no_clobber_create_move_restore(self):
        first = self.create()
        self.assertEqual(self.fs.call('write',path=str(self.path),content='bad',expected_version='missing')['code'],'version_conflict')
        other = self.root/'other'; other.write_text('existing')
        result = self.fs.call('move', source=str(self.path), destination=str(other), expected_version=first['after']['version'])
        self.assertEqual(result['code'], 'version_conflict'); self.assertEqual(other.read_text(),'existing')
        deleted = self.fs.call('delete', path=str(self.path), expected_version=first['after']['version'])
        self.path.write_text('new work')
        result = self.fs.call('restore',operation_id=deleted['operation_id'],expected_version='missing')
        self.assertEqual(result['code'],'version_conflict'); self.assertEqual(self.path.read_text(),'new work')

    def test_binary_and_utf8_paging(self):
        data = bytes(range(256))
        result = self.fs.call('write',path=str(self.path),content=base64.b64encode(data).decode(),encoding='base64',expected_version='missing')
        self.assertTrue(result['ok'])
        read = self.fs.call('read',path=str(self.path),encoding='base64',limit=100)
        self.assertEqual(base64.b64decode(read['content']),data[:100]); self.assertTrue(read['truncated'])
        self.assertEqual(self.fs.call('read',path=str(self.path))['code'],'invalid_text_encoding')
        self.assertEqual(self.fs.call('write',path=str(self.root/'invalid'),content='$$',encoding='base64',expected_version='missing')['code'],'invalid_arguments')
        self.path.write_text('가나다')
        read = self.fs.call('read',path=str(self.path),limit=4)
        self.assertEqual(read['content'],'가'); self.assertEqual(read['next_offset'],3)

    def test_directory_move_delete_restore(self):
        folder = self.root/'folder'
        self.assertTrue(self.fs.call('mkdir',path=str(folder))['verified'])
        (folder/'a').write_text('a')
        moved = self.fs.call('move',source=str(folder),destination=str(self.root/'renamed'),expected_version=snapshot(folder)['version'])
        self.assertTrue(moved['ok'], moved)
        deleted = self.fs.call('delete',path=str(self.root/'renamed'),expected_version=moved['after']['version'])
        self.assertTrue(deleted['verified'], deleted)
        restored = self.fs.call('restore',operation_id=deleted['operation_id'],expected_version='missing')
        self.assertTrue(restored['ok'], restored); self.assertEqual((self.root/'renamed'/'a').read_text(),'a')

    def test_bulk_delete_confirmation_bound_to_version(self):
        folder = self.root/'many'; folder.mkdir()
        for i in range(10): (folder/str(i)).write_text(str(i))
        version = snapshot(folder)['version']
        result = self.fs.call('delete',path=str(folder),expected_version=version)
        self.assertEqual(result['code'],'confirmation_required'); self.assertTrue(folder.exists())
        (folder/'new').write_text('new')
        stale = self.fs.call('delete',path=str(folder),expected_version=version,confirmation_token=result['confirmation_token'],user_confirmed=True)
        self.assertEqual(stale['code'],'version_conflict'); self.assertTrue(folder.exists())
        version = snapshot(folder)['version']
        plan = self.fs.call('delete',path=str(folder),expected_version=version)
        done = self.fs.call('delete',path=str(folder),expected_version=version,confirmation_token=plan['confirmation_token'],user_confirmed=True)
        self.assertTrue(done['verified'],done)

    def test_commit_race_preserves_external_content(self):
        first = self.create('before')
        def race(source,destination,**kwargs):
            self.path.write_text('external change')
            return rename_atomic(source,destination,**kwargs)
        with patch('workspace.filesystem.rename_atomic',side_effect=race):
            result = self.fs.call('write',path=str(self.path),content='agent change',expected_version=first['after']['version'])
        self.assertEqual(result['code'],'commit_race_preserved')
        self.assertEqual(Path(result['recovery_path']).read_text(),'external change')
        self.assertFalse(result['ok'])

    def test_journal_failure_prevents_mutation(self):
        self.path.write_text('before')
        with patch.object(self.fs,'save',side_effect=OSError(errno.ENOSPC,'full')):
            result = self.fs.call('write',path=str(self.path),content='after',expected_version=snapshot(self.path)['version'])
        self.assertEqual(result['code'],'disk_full'); self.assertEqual(self.path.read_text(),'before')

    def test_permission_error_preserves_original(self):
        first = self.create()
        with patch('workspace.filesystem.rename_atomic',side_effect=PermissionError(errno.EACCES,'denied')):
            result = self.fs.call('write',path=str(self.path),content='new',expected_version=first['after']['version'])
        self.assertEqual(result['code'],'permission_denied'); self.assertEqual(self.path.read_text(),'first')
        self.assertEqual(result['outcome'],'inspect_required')

    def test_symlink_not_followed_and_fifo_not_opened(self):
        self.path.write_text('original'); link=self.root/'link'; link.symlink_to(self.path)
        result = self.fs.call('write',path=str(link),content='bad',expected_version=snapshot(link)['version'])
        self.assertEqual(result['code'],'not_regular_file'); self.assertEqual(self.path.read_text(),'original')
        fifo=self.root/'fifo'; os.mkfifo(fifo)
        self.assertEqual(self.fs.call('read',path=str(fifo))['code'],'unsupported_file_type')

    def test_copy_tree_preserves_contents(self):
        folder=self.root/'src'; folder.mkdir(); (folder/'a').write_bytes(b'\x00\xff'); (folder/'link').symlink_to('a')
        result=self.fs.call('copy',source=str(folder),destination=str(self.root/'copy'),expected_version=snapshot(folder)['version'])
        self.assertTrue(result['verified'],result); self.assertEqual((self.root/'copy'/'a').read_bytes(),b'\x00\xff')
        self.assertTrue((self.root/'copy'/'link').is_symlink())
        restored=self.fs.call('restore',operation_id=result['operation_id'],expected_version=result['after']['version'])
        self.assertTrue(restored['verified'],restored); self.assertFalse((self.root/'copy').exists())

    def test_utf8_page_must_advance(self):
        self.path.write_text('가')
        for limit in (1,2):
            result=self.fs.call('read',path=str(self.path),limit=limit)
            self.assertEqual(result['code'],'utf8_page_too_small')
        self.path.write_bytes(b'\xe3')
        self.assertEqual(self.fs.call('read',path=str(self.path))['code'],'invalid_text_encoding')

    def test_concurrent_call_cannot_erase_failure_receipt(self):
        first=self.create(); entered=threading.Event(); proceed=threading.Event(); results=[]
        def blocked_rename(*args,**kwargs):
            entered.set(); proceed.wait(3)
            raise OSError(errno.ENOSPC,'full')
        def mutate():
            results.append(self.fs.call('write',path=str(self.path),content='after',expected_version=first['after']['version']))
        with patch('workspace.filesystem.rename_atomic',side_effect=blocked_rename):
            worker=threading.Thread(target=mutate); worker.start(); self.assertTrue(entered.wait(3))
            busy=self.fs.call('inspect',path=str(self.path))
            self.assertEqual(busy['code'],'filesystem_busy'); self.assertNotIn('operation_id',busy)
            proceed.set(); worker.join(3)
        self.assertIn('operation_id',results[0]); self.assertIn('recovery_path',results[0])

    @unittest.skipUnless(os.uname().sysname=='Darwin','macOS metadata')
    def test_macos_metadata_preserved(self):
        self.path.write_text('before')
        subprocess.run(['/usr/bin/xattr','-w','com.example.aiworkspace.test','metadata',str(self.path)],check=True)
        first=snapshot(self.path)
        result=self.fs.call('write',path=str(self.path),content='after',expected_version=first['version'])
        self.assertTrue(result['verified'],result)
        for path in (str(self.path),result['backup']):
            self.assertEqual(subprocess.check_output(['/usr/bin/xattr','-p','com.example.aiworkspace.test',path]).strip(),b'metadata')

    def test_commit_journal_failure_reports_prepared(self):
        first=self.create()
        save=self.fs.save
        def fail_finish(record):
            if record['status']=='verified': raise OSError(errno.ENOSPC,'full')
            return save(record)
        with patch.object(self.fs,'save',side_effect=fail_finish):
            result=self.fs.call('write',path=str(self.path),content='after',expected_version=first['after']['version'])
        self.assertEqual(result['journal_status'],'prepared')
        self.assertEqual(self.path.read_text(),'after')
        self.assertEqual(Path(result['recovery_path']).read_text(),'first')

    def test_search_arbitrary_folder_and_journal_protection(self):
        self.create('needle')
        result=self.fs.call('search',root=str(self.root),pattern='*.txt',query='needle')
        self.assertEqual(result['results'][0]['path'],str(self.path))
        self.assertEqual(self.fs.call('delete',path=str(self.fs.state),expected_version='bad')['code'],'journal_protected')

    def test_protocol_opt_in_and_real_operations(self):
        from mcp import Client
        async def run():
            async with Client(create_server(self.root/'old',read_only=True)) as client:
                names={t.name for t in (await client.list_tools()).tools}
                self.assertEqual(names,{'workspace_recall','workspace_health','search_local','read_local_artifact'})
            async with Client(create_server(self.root/'state',read_only=True,filesystem=True)) as client:
                listed=(await client.list_tools()).tools
                self.assertEqual(len(listed),17)
                self.assertTrue(next(t for t in listed if t.name=='local_file_write').annotations.destructive_hint)
                create=await client.call_tool('local_file_create',{'path':str(self.path),'content':'first'})
                data=create.structured_content
                if data is None: data=json.loads(create.content[0].text)
                self.assertTrue(data['verified'],data)
                edit=await client.call_tool('local_file_edit',{'path':str(self.path),'old_text':'first','new_text':'second','expected_version':data['after']['version']})
                self.assertFalse(edit.is_error)
                read=await client.call_tool('local_file_read',{'path':str(self.path)})
                data=read.structured_content
                if data is None: data=json.loads(read.content[0].text)
                self.assertEqual(data['content'],'second')
        asyncio.run(run())


if __name__=='__main__': unittest.main()
