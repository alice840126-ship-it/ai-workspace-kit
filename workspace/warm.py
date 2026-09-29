"""Local, structured recent checkpoints; only promoted refined payloads enter Git."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from .core import KST, safe, validate, now

ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
ENVELOPE = {'version', 'source', 'session', 'checkpoint', 'stamp', 'kind',
            'verified', 'explicit_memory', 'next_context', 'memory'}


def schema(ledger):
    ledger.db.executescript('''
    create table if not exists external_checkpoints(
      id text primary key, source text not null, session text not null,
      checkpoint text not null, stamp text not null, received text not null,
      fingerprint text not null unique, envelope text not null,
      promoted_event text, unique(source,session,checkpoint));
    create table if not exists warm_intake_failures(
      file_key text primary key, code text not null, stamp text not null);
    create table if not exists warm_intake_files(file_key text primary key, signature text not null);
    ''')


def validate_checkpoint(data):
    if not isinstance(data, dict) or set(data) != ENVELOPE:
        raise ValueError('invalid_warm_schema')
    if type(data['version']) is not int or data['version'] != 1:
        raise ValueError('invalid_warm_version')
    if data['source'] not in ('chatgpt', 'codex', 'manual', 'aside'):
        raise ValueError('invalid_warm_source')
    for key in ('session', 'checkpoint'):
        if not isinstance(data[key], str) or not ID.fullmatch(data[key]):
            raise ValueError('invalid_warm_id')
    if data['kind'] != 'confirmed_summary' or data['verified'] is not True:
        raise ValueError('unverified_warm_checkpoint')
    if type(data['explicit_memory']) is not bool:
        raise ValueError('invalid_warm_flag')
    if not isinstance(data['stamp'], str):
        raise ValueError('invalid_warm_stamp')
    try:
        stamp = dt.datetime.fromisoformat(data['stamp'])
    except ValueError:
        raise ValueError('invalid_warm_stamp') from None
    if stamp.tzinfo is None or stamp > dt.datetime.now(KST) + dt.timedelta(minutes=5):
        raise ValueError('invalid_warm_stamp')
    validate(data['memory'])
    safe(data['next_context'])
    # A bounded summary contract, not a transcript or arbitrary message storage API.
    text = '\n'.join([data['next_context'], *[s for k, v in data['memory'].items() if isinstance(v, list) for s in v]])
    if len(text) > 6000 or re.search(r'(?im)^\s*(?:user|assistant|system|developer|사용자|도구 출력)\s*:', text) or '```' in text:
        raise ValueError('raw_content_not_allowed')
    if any(len(s) > 600 for k,v in data['memory'].items() if isinstance(v,list) for s in v) or len(data['next_context']) > 600:
        raise ValueError('warm_summary_too_long')
    if not any(data['memory'][k] for k in ('context','status','decisions','todo')):
        raise ValueError('empty_warm_checkpoint')
    return data


def accept_checkpoint(ledger, data):
    """Validate before persistence; deterministic immutable dedup within a session."""
    validate_checkpoint(data)
    schema(ledger)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True)
    eid = hashlib.sha256(':'.join(data[k] for k in ('source','session','checkpoint')).encode()).hexdigest()[:24]
    found = ledger.db.execute('select envelope from external_checkpoints where id=?', (eid,)).fetchone()
    if found:
        if found[0] != encoded:
            raise ValueError('immutable_warm_conflict')
        return {'id': eid, 'changed': False}
    semantic = {k:data[k] for k in ('source','session','memory','next_context','explicit_memory')}
    fingerprint = hashlib.sha256(json.dumps(semantic, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    duplicate = ledger.db.execute('select id from external_checkpoints where fingerprint=?', (fingerprint,)).fetchone()
    if duplicate:
        return {'id': duplicate[0], 'changed': False}
    with ledger.db:
        ledger.db.execute('insert into external_checkpoints values(?,?,?,?,?,?,?,?,NULL)',
                         (eid,data['source'],data['session'],data['checkpoint'],data['stamp'],now(),fingerprint,encoded))
    return {'id': eid, 'changed': True}


def _rows(ledger, days=3):
    schema(ledger)
    if not 1 <= days <= 30:
        raise ValueError('invalid_warm_window')
    cutoff = dt.datetime.now(KST)-dt.timedelta(days=days)
    result=[]
    for eid,envelope,promoted in ledger.db.execute('select id,envelope,promoted_event from external_checkpoints'):
        data=json.loads(envelope)
        if dt.datetime.fromisoformat(data['stamp']) >= cutoff:
            result.append((eid,data,promoted))
    return sorted(result,key=lambda r:dt.datetime.fromisoformat(r[1]['stamp']))


def query_warm(ledger, text, *, days=3, limit=5):
    """Recent summaries only; all query terms must match. No Cold scan fallback here."""
    if not isinstance(text,str) or not text.strip() or len(text)>500 or not 1<=limit<=20:
        raise ValueError('invalid_warm_query')
    terms=re.findall(r'[\w-]+',text.casefold())
    if not terms: return []
    results=[]
    for eid,data,promoted in _rows(ledger,days):
        haystack=json.dumps({'memory':data['memory'],'next_context':data['next_context']},ensure_ascii=False).casefold()
        if all(term in haystack for term in terms):
            results.append({'id':eid,'stamp':data['stamp'],'topic':data['memory']['topic'],
                            'source':data['source'],'memory':data['memory'],
                            'next_context':data['next_context'],'promoted':bool(promoted)})
    return list(reversed(results))[:limit]


def promote_warm(ledger, allowed_repos, *, days=3):
    """Feed strong verified signals to the existing lifecycle; never create repos."""
    rows=_rows(ledger,days)
    topics={}
    for row in rows: topics.setdefault(row[1]['memory']['topic'],[]).append(row)
    promoted=0
    for topic,items in topics.items():
        distinct=len({(d['source'],d['session']) for _,d,_ in items})
        for eid,data,event in items:
            if event: continue
            validate_checkpoint(data)
            p=data['memory']
            if p['repo'] and p['repo'] not in allowed_repos:
                continue  # Local only until the existing repository registry confirms ownership.
            # A decision alone is a durable fact; one-off status/search/chat is not.
            durable=bool(data['explicit_memory'] or p['decisions'] or
                         (p['todo'] and (p['repo'] or p['links'] or p['business'] or distinct>=2)) or
                         (p['status'] and p['repo'] and (p['business'] or distinct>=2)))
            if not durable: continue
            session='warm'+hashlib.sha256((data['source']+':'+data['session']).encode()).hexdigest()[:24]
            event_id,_=ledger.record(session,eid,p,data['stamp'])
            with ledger.db:
                ledger.db.execute('update external_checkpoints set promoted_event=? where id=?',(event_id,eid))
            promoted+=1
    return promoted


def collect_warm(ledger, allowed_repos, *, limit=100):
    """Collect a private local inbox. Never place this inbox in the Git checkout."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('invalid_warm_limit')
    schema(ledger)
    folder=ledger.state/'warm-inbox'
    if folder.is_symlink(): raise ValueError('symlink_blocked')
    folder.mkdir(mode=0o700,exist_ok=True)
    accepted=failed=processed=0
    for path in sorted(folder.glob('*.json')):
        file_key=hashlib.sha256(path.name.encode()).hexdigest()[:24]
        signature=None
        try:
            stat=path.lstat()
            signature=f'{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}'
            previous=ledger.db.execute('select signature from warm_intake_files where file_key=?',(file_key,)).fetchone()
            if previous and previous[0]==signature: continue
            if processed>=limit: break
            processed+=1
            if path.is_symlink() or not path.is_file() or path.stat().st_size>32000:
                raise ValueError('invalid_warm_file')
            accepted+=int(accept_checkpoint(ledger,json.loads(path.read_text()))['changed'])
            with ledger.db: ledger.db.execute('delete from warm_intake_failures where file_key=?',(file_key,))
        except (ValueError,OSError,TypeError,KeyError) as error:
            # Error codes only, no source text or private file names in diagnostics.
            codes={'invalid_warm_schema','invalid_warm_version','invalid_warm_source','invalid_warm_id',
                   'unverified_warm_checkpoint','invalid_warm_flag','invalid_warm_stamp','raw_content_not_allowed',
                   'warm_summary_too_long','empty_warm_checkpoint','immutable_warm_conflict','invalid_warm_file',
                   'sensitive_or_invalid_text','sensitive_or_invalid_flag','unapproved_link','invalid_schema',
                   'invalid_topic','invalid_repo','invalid_list','control_character'}
            code=str(error) if str(error) in codes else 'warm_intake_rejected'
            with ledger.db:
                ledger.db.execute('insert or replace into warm_intake_failures values(?,?,?)',(file_key,code,now()))
            failed+=1
        if signature is not None:
            with ledger.db: ledger.db.execute('insert or replace into warm_intake_files values(?,?)',(file_key,signature))
    return {'accepted':accepted,'failed':failed,'promoted':promote_warm(ledger,allowed_repos)}
