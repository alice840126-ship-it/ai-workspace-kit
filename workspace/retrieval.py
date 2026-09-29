"""Priority retrieval: caller Hot context -> recent -> refined -> explicit local cold."""
import json
import datetime as dt
import sqlite3
from .core import now
from .core import topic_states
from .history import History,terms
from .warm import query_warm,collect_warm


def repositories(root):
    return {r['name'] for r in json.loads((root/'audit/repositories.json').read_text())['repositories']}|{'ai-workspace'}


def recall(ledger,text,*,cold=False,allow_cold=True):
    if not isinstance(text,str) or not 1<=len(text)<=500:raise ValueError('invalid_retrieval_query')
    if not cold:
        warm=query_warm(ledger,text)
        needle=set(terms(text));hits=[]
        if needle:
            for topic,st in topic_states(ledger.events()).items():
                memory=dict(st['latest'])
                for field in ('decisions','failed_approaches'):
                    memory[field]=list(dict.fromkeys(t for e in st['events'] for t in e['payload'][field]))[-24:]
                if needle.issubset(set(terms(topic+' '+json.dumps(memory,ensure_ascii=False)))):
                    hits.append({'topic':topic,'stage':st['stage'],'stamp':st['events'][-1]['stamp'],'source':'local_refined','memory':memory})
        if warm:
            # A recent checkpoint must not hide a newer state of the same topic.
            by_topic={h['topic']:h for h in hits}
            results=[];seen=set()
            for item in warm:
                topic=item['topic']
                if topic in seen:continue
                seen.add(topic)
                newer=by_topic.get(topic)
                if newer and dt.datetime.fromisoformat(newer['stamp']) > dt.datetime.fromisoformat(item['stamp']):
                    results.append(newer)
                else:results.append(item)
            layers={'refined' if r.get('source')=='local_refined' else 'warm' for r in results}
            layer=next(iter(layers)) if len(layers)==1 else 'mixed'
            return {'layer':layer,'results':results,'cold_searched':False}
        if hits:return {'layer':'refined','results':hits[:5],'cold_searched':False}
    if not allow_cold:
        return {'layer':'none','results':[],'cold_searched':False,'next_step':'No refined match. Cold access is disabled for this interface.'}
    with_history=History(ledger.state/'history')
    try:found=with_history.search(text)
    finally:with_history.close()
    return {'layer':'cold','results':found,'cold_searched':True,
            'next_step':None if found else 'Try fewer factual keywords, then consult the linked project GitHub. No automatic repository crawl.'}


def maintenance(ledger,root,home):
    """Invoked under the existing tick lock; no new scheduling or LLM calls."""
    enabled=ledger.state/'retrieval-enabled'
    if not enabled.exists():return
    try:
        warm=collect_warm(ledger,repositories(root));ledger.set('warm_last_collection',json.dumps(warm))
    except (OSError,ValueError,sqlite3.Error,TypeError,KeyError) as error:
        failure=json.dumps({'status':'error','code':type(error).__name__,'time':now()})
        ledger.set('warm_last_collection',failure);ledger.set('warm_last_error',failure)
    try:
        history=History(ledger.state/'history')
        try:result=history.index(home,budget=12)
        finally:history.close()
        ledger.set('history_last_index',json.dumps(result))
    except (OSError,ValueError,sqlite3.Error,TypeError,KeyError) as error:
        # An optional local search failure must not stop existing refined collection.
        failure=json.dumps({'status':'error','code':type(error).__name__,'time':now()})
        ledger.set('history_last_index',failure);ledger.set('history_last_error',failure)

    # Keep document extraction separate from native session indexing/publication.
    if (ledger.state/'artifact-roots.json').is_file():
        try:
            from .artifacts import ArtifactIndex
            artifacts=ArtifactIndex(ledger.state)
            try: result=artifacts.index(budget=5)
            finally: artifacts.close()
            ledger.set('artifact_last_index',json.dumps(result))
        except Exception as error:
            ledger.set('artifact_last_index',json.dumps({'status':'error','code':type(error).__name__,'time':now()}))
