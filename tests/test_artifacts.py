import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch
from workspace.artifacts import ArtifactIndex

class ArtifactsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base/'work'; self.root.mkdir()
        self.state = self.base/'state'; self.state.mkdir()
        self.config()
        self.index = ArtifactIndex(self.state)
    def tearDown(self):
        self.index.close(); self.tmp.cleanup()
    def config(self):
        s=self.root.stat()
        (self.state/'artifact-roots.json').write_text(json.dumps({'roots':[{'path':str(self.root),'label':'ExampleCo','device':s.st_dev,'inode':s.st_ino}]}))
    def write(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
    def test_index_read_incremental_restart_change(self):
        p=self.write('견적서.txt','ExampleCo 견적서 금액 10,000,000원 VAT 별도 교육 3회')
        self.assertEqual(self.index.index()['indexed'],1)
        result=self.index.search('ExampleCo 견적서')['results'][0]
        self.assertEqual(result['path'],str(p)); identity=result['id']
        self.assertIn('교육 3회',self.index.read(identity)['text'])
        with patch.object(self.index,'_extract',side_effect=AssertionError('unchanged reread')):
            self.assertEqual(self.index.index()['unchanged'],1)
        self.index.close();self.index=ArtifactIndex(self.state)
        self.assertEqual(len(self.index.search('견적서')['results']),1)
        p.write_text('ExampleCo 견적서 교육 4회')
        self.assertEqual(self.index.read(identity)['status'],'source_changed_reindex_required')
        self.index.index()
        self.assertIn('4회',self.index.read(identity)['text'])
        self.assertEqual(self.index.db.execute('select count(*) from artifacts').fetchone()[0],1)
    def test_natural_followup_uses_labeled_partial_candidates_and_source_read(self):
        self.write('ExampleCo_견적서.txt','ExampleCo 견적서 금액 10,000,000원 VAT 별도 교육 3회')
        self.write('unrelated.txt','시설 관리 일정')
        self.write('Other_교육.txt','다른 고객 교육 5회')
        self.index.index()
        exact=self.index.search('ExampleCo 견적서')['results']
        self.assertEqual(exact[0]['match_mode'],'all_terms')
        followup=self.index.search('ExampleCo 견적서 교육 횟수')['results']
        self.assertEqual([r['filename'] for r in followup],['ExampleCo_견적서.txt'])
        self.assertEqual(followup[0]['match_mode'],'partial_terms')
        self.assertIn('교육 3회',self.index.read(followup[0]['id'])['text'])
        self.assertEqual(self.index.search('ExampleCo 교육')['results'][0]['filename'],'ExampleCo_견적서.txt')
        self.assertEqual(self.index.search('찾을수없는 고유표현')['results'],[])
    def test_deny_secret_symlink_hardlink_and_allowlist_revocation(self):
        self.write('.env','ExampleCo')
        self.write('node_modules/quote.txt','ExampleCo')
        self.write('config.json','ExampleCo')
        self.write('leak.txt','ExampleCo api_key='+('sk-'+'a'*30))
        safe=self.write('ok.txt','ExampleCo contact foo@example.test 교육 3회')
        outside=self.base/'outside.txt';outside.write_text('ExampleCo private')
        (self.root/'link.txt').symlink_to(outside)
        os.link(outside,self.root/'hard.txt')
        self.index.index()
        results=self.index.search('ExampleCo')['results']
        self.assertEqual([r['filename'] for r in results],['ok.txt'])
        data=self.index.read(results[0]['id'])['text']
        self.assertNotIn('foo@example',data); self.assertIn('교육 3회',data)
        (self.state/'artifact-roots.json').write_text('{"roots":[]}')
        self.assertEqual(self.index.search('ExampleCo')['results'],[])
        self.assertEqual(self.index.read(results[0]['id'])['status'],'not_allowed')
        self.index.index();self.assertEqual(self.index.db.execute('select count(*) from artifacts').fetchone()[0],0)
    def test_disconnected_root_and_replaced_identity(self):
        self.write('quote.txt','ExampleCo 견적서')
        self.index.index();identity=self.index.search('견적서')['results'][0]['id']
        self.root.rename(self.base/'detached')
        self.assertEqual(self.index.read(identity)['status'],'root_unavailable')
        result=self.index.search('견적서')['results'][0]
        self.assertEqual(result['snippet'],'');self.assertEqual(result['status'],'root_unavailable')
        self.root.mkdir()
        self.assertEqual(self.index.read(identity)['status'],'root_identity_changed')
        with patch('workspace.artifacts.Path.stat',side_effect=FileNotFoundError):
            self.assertEqual(self.index._availability({'path':'/Volumes/ssd/work','device':1,'inode':2}),'external_ssd_disconnected')
    def test_read_symlink_swap_and_pagination(self):
        p=self.write('quote.txt','ExampleCo '+('교육 3회 '*100))
        self.index.index();identity=self.index.search('ExampleCo')['results'][0]['id']
        first=self.index.read(identity,limit=30);self.assertEqual(first['next_offset'],30)
        self.assertEqual(len(first['text']),30)
        p.unlink();p.symlink_to(self.base/'outside')
        self.assertNotEqual(self.index.read(identity)['status'],'ok')
    def test_docx_and_failed_extraction_not_indexed(self):
        with zipfile.ZipFile(self.root/'quote.docx','w') as f:
            f.writestr('word/document.xml','<w:document xmlns:w="urn:w"><w:p><w:r><w:t>ExampleCo 견적서 교육 3회</w:t></w:r></w:p></w:document>')
        self.write('bad.docx','not a zip')
        self.assertEqual(self.index.index()['errors'],1)
        r=self.index.search('견적서')['results'][0]
        self.assertIn('교육 3회',self.index.read(r['id'])['text'])
    def test_no_implicit_roots_and_root_symlink(self):
        (self.state/'artifact-roots.json').unlink()
        self.assertEqual(self.index.index()['status'],'not_configured')
        self.assertEqual(self.index.read('../anything')['status'],'not_found')
        self.root.rename(self.base/'real');self.root.symlink_to(self.base/'real')
        self.config()
        self.assertEqual(self.index.index()['roots'][0]['status'],'root_not_allowed')

    def test_budget_queue_resumes_and_other_root_not_starved(self):
        second=self.base/'second';second.mkdir();(second/'quote.txt').write_text('ExampleCo second')
        value=json.loads((self.state/'artifact-roots.json').read_text())
        st=second.stat();value['roots'].append({'label':'second','path':str(second),'device':st.st_dev,'inode':st.st_ino})
        (self.state/'artifact-roots.json').write_text(json.dumps(value))
        for i in range(4): self.write(f'{i}.txt','ExampleCo first')
        original=self.index._extract
        def slow(*args):
            time.sleep(.06)
            return original(*args)
        with patch.object(self.index,'_extract',side_effect=slow):
            self.index.index(budget=.05)
            self.index.close();self.index=ArtifactIndex(self.state)
            self.index.index(budget=.2)
        self.assertTrue(any(r['collection']=='second' for r in self.index.search('ExampleCo',20)['results']))
        self.index.index()
        self.assertEqual(self.index.db.execute('select count(*) from artifacts').fetchone()[0],5)

    def test_json_escaped_credentials_and_malformed_fail_closed(self):
        self.write('export.json',r'{"topic":"ExampleCo", "\u0070assword":"SYNTHETIC_ONLY_12345"}')
        self.write('export.jsonl',r'{"topic":"ExampleCo", "\u0070assword":"SYNTHETIC_ONLY_12345"}')
        self.write('broken.json','{"topic":"ExampleCo"')
        self.write('good.json','{"topic":"ExampleCo 견적서", "education":"3회"}')
        self.index.index()
        found=self.index.search('ExampleCo')['results']
        self.assertEqual([r['filename'] for r in found],['good.json'])
        self.assertNotIn('SYNTHETIC',str(self.index.db.execute('select text from artifacts').fetchall()))
    def test_all_subject_terms_required(self):
        self.write('storage.txt','Storage tablet')
        self.write('quote.txt','ExampleCo 견적서 교육 3회')
        self.index.index()
        self.assertEqual([r['filename'] for r in self.index.search('ExampleCo 견적서')['results']],['quote.txt'])

    def test_policy_change_invalidates_derived_text(self):
        self.write('quote.txt','ExampleCo 견적서')
        self.index.index()
        self.index.db.execute("update artifact_meta set value='old' where key='policy_version'")
        self.index.db.commit();self.index.close();self.index=ArtifactIndex(self.state)
        self.assertEqual(self.index.search('ExampleCo')['results'],[])
        self.assertTrue((self.root/'quote.txt').exists())
        self.index.index();self.assertEqual(len(self.index.search('ExampleCo')['results']),1)
