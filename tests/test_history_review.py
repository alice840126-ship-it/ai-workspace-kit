"""Independent regressions for malformed, changing and skewed historical inputs."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from workspace.history import History


class HistoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.history=History(self.root/'derived');self.source=self.root/'rollout.jsonl'
    def tearDown(self):
        self.history.close();self.tmp.cleanup()
    @staticmethod
    def meta():return {'type':'session_meta','payload':{'id':'review-session','cwd':'/tmp/review'}}
    @staticmethod
    def message(text):
        return {'type':'response_item','timestamp':'2026-09-29T01:00:00Z',
                'payload':{'type':'message','role':'user','content':[{'type':'input_text','text':text}]}}
    def write(self,items):
        self.source.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in items))
    def index(self):return self.history.file(self.source,time.monotonic()+5)
    def test_session_diversity_despite_105_repeated_matches(self):
        for i in range(105):
            self.history.put('repeat'+str(i),'many','','fixture',{},'',i,self.message('ExampleCo Slack 권한')['payload'])
        self.history.put('other','other-session','','fixture',{},'',0,self.message('ExampleCo Slack 권한 추가 확인')['payload'])
        self.history.db.commit()
        result=self.history.search('ExampleCo Slack 권한')
        self.assertEqual({x['session'] for x in result},{'many','other-session'})
    def test_korean_particles_keep_keyword_match(self):
        self.write([self.meta(),self.message('Slack 권한을 검토하고 이미지의 생성을 확인했다')]);self.index()
        self.assertEqual(len(self.history.search('Slack 권한')),1)
        self.assertEqual(len(self.history.search('이미지 생성')),1)
        self.assertEqual(self.history.search('권한 결제'),[])
    def test_scalar_and_invalid_json_do_not_block_later_messages(self):
        self.write([self.meta(),[],None,42,'invalid shape',self.message('beforemarker')])
        with self.source.open('a') as out:
            out.write('{invalid json}\n')
            out.write(json.dumps(self.message('aftermarker'))+'\n')
        before=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.index()
        self.assertEqual(self.history.stats()['messages'],2)
        self.assertTrue(self.history.search('aftermarker'))
        self.assertEqual(self.index(),(0,0))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),before)
    def test_same_size_rewrite_replaces_fts_content(self):
        self.write([self.meta(),self.message('oldmarker')]);self.index()
        oldstat=self.source.stat()
        self.write([self.meta(),self.message('newmarker')])
        self.assertEqual(self.source.stat().st_size,oldstat.st_size)
        os.utime(self.source,ns=(oldstat.st_atime_ns,oldstat.st_mtime_ns+1000000))
        self.index()
        self.assertEqual(self.history.search('oldmarker'),[])
        self.assertTrue(self.history.search('newmarker'))
        self.assertEqual(self.history.stats()['messages'],1)
    def test_truncation_discards_removed_message(self):
        self.write([self.meta(),self.message('remainingmarker'),self.message('removedmarker')]);self.index()
        self.write([self.meta(),self.message('remainingmarker')]);self.index()
        self.assertTrue(self.history.search('remainingmarker'))
        self.assertEqual(self.history.search('removedmarker'),[])
        self.assertEqual(self.history.stats()['messages'],1)
    def test_old_cached_credential_redacted_at_query_time(self):
        self.write([self.meta(),self.message('needle cached report')]);self.index()
        # Simulate a derived row from a previous redactor version, not a native file.
        cached='needle Cookie: session=synthetic-browser-cookie'
        self.history.db.execute('update messages set text=?',(cached,));self.history.db.commit()
        result=self.history.search('needle')
        self.assertTrue(result)
        self.assertNotIn('synthetic-browser-cookie',json.dumps(result))

    def test_returned_context_has_locator_and_bounded_text(self):
        self.write([self.meta(),self.message('prior marker'),self.message('needle '+('padding '*1000)),self.message('after marker')]);self.index()
        results=self.history.search('needle',context=1)
        self.assertEqual(len(results),1)
        snippets=results[0]['context'];self.assertEqual(len(snippets),3)
        for snippet in snippets:
            self.assertLessEqual(len(snippet['text']),1400)
            loc=snippet['locator']
            with self.source.open('rb') as source:
                source.seek(loc['offset']);row=json.loads(source.read(loc['bytes']))
            self.assertEqual(row['type'],'response_item')
        self.assertIn('untrusted',results[0]['trust'])

if __name__=='__main__':unittest.main()
