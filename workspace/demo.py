"""Synthetic, temporary end-to-end demo. No credentials, network or model calls."""
import json
from pathlib import Path
import tempfile
from .kit import init,allow_root
from .core import now,render
from .bridge import Bridge
from .warm import collect_warm
from .artifacts import ArtifactIndex

def main():
    with tempfile.TemporaryDirectory(prefix='workspace-demo-') as temp:
        base=Path(temp).resolve();state=base/'state';memory=base/'memory';docs=base/'documents';docs.mkdir()
        init(memory,state)
        (docs/'quotation.txt').write_text('ExampleCo 견적서\n합계 2,200,000원 VAT 포함\n사용자 교육 2회\n구축 범위: 문서 분류, 검색 연결, 운영 안내서\n')
        summary=dict(topic='demokit',repo='',business=False,sensitive=False,context=['가상 문서 검색 프로젝트'],status=['설계 완료'],decisions=['원본은 로컬에 유지한다'],todo=['원본 검색 검증'],failed_approaches=[],links=[],completed_todo=[])
        envelope=dict(version=1,source='manual',session='demo-session',checkpoint='design',stamp=now(),kind='confirmed_summary',verified=True,explicit_memory=True,next_context='DemoKit 검증',memory=summary)
        bridge=Bridge(state)
        first=bridge.checkpoint(envelope);second=bridge.checkpoint(envelope)
        assert first['changed'] and not second['changed']
        with bridge.locked() as ledger:
            promoted=collect_warm(ledger,set());render(ledger,memory)
            assert promoted['promoted']==1
        allow_root(state,docs,'ExampleCo demo')
        index=ArtifactIndex(state)
        try:index.index(budget=10)
        finally:index.close()
        found=bridge.artifact('search',query='ExampleCo 견적서',limit=5)
        assert len(found['results'])==1
        read=bridge.artifact('read',artifact_id=found['results'][0]['id'])
        assert '2,200,000' in read['text'] and '2회' in read['text']
        (docs/'quotation.txt').unlink()  # Synthetic fixture only.
        missing=bridge.artifact('read',artifact_id=found['results'][0]['id'])
        assert not missing.get('text')
        print(json.dumps({'ok':True,'checkpoint_deduplicated':True,'promoted':1,
          'memory_files':[p.name for p in (memory/'memory').glob('*.md')],
          'fresh_source_text':read['text'],'missing_source':missing,
          'network_calls':0,'model_calls':0},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
