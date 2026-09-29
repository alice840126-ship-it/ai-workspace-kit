import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from workspace.core import Ledger, KST, now, topic_states, projection
from workspace.warm import accept_checkpoint, query_warm, promote_warm, collect_warm


def checkpoint(session='s1', turn='t1', **memory):
    p=dict(topic='warm-test',repo='',business=False,sensitive=False,context=['구조화 기억 검증'],status=['입력 완료'],decisions=[],todo=[],failed_approaches=[],links=[],completed_todo=[])
    p.update(memory)
    return dict(version=1,source='chatgpt',session=session,checkpoint=turn,stamp=now(),kind='confirmed_summary',verified=True,explicit_memory=False,next_context='기억 입력 경로 검증',memory=p)


class WarmTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.ledger=Ledger(Path(self.temp.name)/'state')
    def tearDown(self):
        self.ledger.db.close(); self.temp.cleanup()
    def test_input_and_dedup(self):
        d=checkpoint(); first=accept_checkpoint(self.ledger,d)
        self.assertTrue(first['changed']); self.assertFalse(accept_checkpoint(self.ledger,d)['changed'])
        d['checkpoint']='t2'; d['stamp']=now()
        self.assertEqual(accept_checkpoint(self.ledger,d),dict(id=first['id'],changed=False))
        self.assertEqual(len(query_warm(self.ledger,'구조화 기억')),1)
        self.assertEqual(query_warm(self.ledger,'absent'),[])
    def test_immutable(self):
        d=checkpoint(); accept_checkpoint(self.ledger,d);d['next_context']='다른 값'
        with self.assertRaisesRegex(ValueError,'immutable_warm'):accept_checkpoint(self.ledger,d)
    def test_no_status_only_publication(self):
        accept_checkpoint(self.ledger,checkpoint())
        self.assertEqual(promote_warm(self.ledger,set()),0)
        self.assertEqual(self.ledger.events(),[])
        self.assertFalse(any(n.startswith('events/') for n in projection(self.ledger)))
    def test_decision_promotes_idempotently(self):
        accept_checkpoint(self.ledger,checkpoint(decisions=['원본은 로컬 유지: 개인정보 보호']))
        self.assertEqual(promote_warm(self.ledger,set()),1)
        self.assertEqual(promote_warm(self.ledger,set()),0)
        self.assertEqual(topic_states(self.ledger.events())['warm-test']['stage'],'topic')
    def test_candidate_and_project(self):
        accept_checkpoint(self.ledger,checkpoint(decisions=['조회 우선 구현'],todo=['복원 검증']))
        accept_checkpoint(self.ledger,checkpoint('s2',decisions=['조회 우선 구현'],todo=['복원 검증']))
        self.assertEqual(promote_warm(self.ledger,set()),2)
        self.assertEqual(topic_states(self.ledger.events())['warm-test']['stage'],'candidate')
        accept_checkpoint(self.ledger,checkpoint('s3',repo='ai-workspace',business=True))
        self.assertEqual(promote_warm(self.ledger,{'ai-workspace'}),1)
        self.assertEqual(topic_states(self.ledger.events())['warm-test']['stage'],'project')
    def test_unknown_repository_local_only(self):
        accept_checkpoint(self.ledger,checkpoint(repo='unknown',decisions=['결정']))
        self.assertEqual(promote_warm(self.ledger,{'ai-workspace'}),0)
    def test_explicit_memory(self):
        d=checkpoint(); d['explicit_memory']=True;accept_checkpoint(self.ledger,d)
        self.assertEqual(promote_warm(self.ledger,set()),1)
    def test_expired(self):
        d=checkpoint(decisions=['옛 결정']);d['stamp']=(dt.datetime.now(KST)-dt.timedelta(days=4)).isoformat()
        accept_checkpoint(self.ledger,d)
        self.assertEqual(query_warm(self.ledger,'구조화'),[])
        self.assertEqual(promote_warm(self.ledger,set()),0)
    def test_reject_raw_secrets_unverified(self):
        for value in ['password=secretvalue','person@example.com','/Volumes/private','assistant: 전문','```code```']:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):accept_checkpoint(self.ledger,checkpoint(status=[value]))
        for key,val in [('verified',False),('kind','speculation'),('raw','text'),('stamp','2026-01-01')]:
            d=checkpoint();d[key]=val
            with self.assertRaises(ValueError):accept_checkpoint(self.ledger,d)
        self.assertEqual(self.ledger.events(),[])
    def test_inbox_and_safe_failure(self):
        folder=self.ledger.state/'warm-inbox';folder.mkdir()
        (folder/'good.json').write_text(json.dumps(checkpoint(decisions=['통합 결정'])))
        (folder/'bad.json').write_text(json.dumps(checkpoint(status=['person@example.com'])))
        result=collect_warm(self.ledger,set())
        self.assertEqual(result,dict(accepted=1,failed=1,promoted=1))
        self.assertEqual(collect_warm(self.ledger,set()),dict(accepted=0,failed=0,promoted=0))
        rows=list(self.ledger.db.execute('select * from warm_intake_failures'))
        self.assertEqual(len(rows),1);self.assertNotIn('person@example.com',str(rows))
    def test_no_intake_starvation(self):
        folder=self.ledger.state/'warm-inbox';folder.mkdir()
        for i in range(3): (folder/f'{i}.json').write_text(json.dumps(checkpoint(turn=f't{i}',status=[str(i)])))
        for _ in range(3):self.assertEqual(collect_warm(self.ledger,set(),limit=1)['accepted'],1)
    def test_distinct_sessions_not_turns(self):
        accept_checkpoint(self.ledger,checkpoint(todo=['작업']))
        accept_checkpoint(self.ledger,checkpoint(turn='t2',todo=['작업'],status=['후속']))
        self.assertEqual(promote_warm(self.ledger,set()),0)
        accept_checkpoint(self.ledger,checkpoint('s2',todo=['작업']))
        self.assertEqual(promote_warm(self.ledger,set()),3)
        self.assertEqual(topic_states(self.ledger.events())['warm-test']['sessions'],2)

if __name__=='__main__':unittest.main()
