from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
FIELDS = ('context', 'status', 'decisions', 'todo', 'failed_approaches', 'links', 'completed_todo')
SECRET = re.compile(r'(?i)(?:sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9]{12,}|github_pat_[a-z0-9_]+|\b\d{7,12}:[a-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY|(?:password|passwd|api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*["\']?[^\s"\']{6,}|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|\b01[016789][- ]?\d{3,4}[- ]?\d{4}\b|\b\d{6}[- ]?[1-4]\d{6}\b|https?://[^\s]+[?&](?:token|key|secret)=|/Users/[^/\s]+|/Volumes/|(?:담당자|성명|연락처|계좌|주민번호|주소)\s*[:：]?\s*\S+|(?:서울특별시|경기도|부산광역시)\s+\S+|\b\d{10,16}\b)')
# Shared rejection/redaction boundary for refined inputs and derived Cold excerpts.
# Synthetic fixtures exercise shapes only; no real credentials belong in this repo.
CREDENTIAL = r"(?:\b(?:Cookie|Set-Cookie|Authorization|Proxy-Authorization)\s*:\s*[^\r\n]+|\b(?:session(?:[_-]?(?:id|key|token))?(?![\"'])|cookie|refresh[_-]?token|id[_-]?token|token|credential|client[_-]?secret|aws[_-]?secret[_-]?access[_-]?key)[\"']?\s*[:=]\s*(?:[\"'][^\"'\r\n]+[\"']|[^\s,;]+)|\bBearer\s+\S+|\bxox[baprs]-[A-Za-z0-9-]{8,}|\bxapp-[A-Za-z0-9-]{8,}|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bAIza[A-Za-z0-9_-]{35}\b|\bya29\.[A-Za-z0-9._-]{12,}|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
# Leading slash paths, drive-letter paths and UNC. Numeric fractions and ordinary
# web URL separators are excluded by the prefix boundary and initial component.
LOCAL_PATH = r"(?<![\w.:/\\])(?:~[/\\]|[A-Za-z]:[/\\]|\\\\(?:[?.]\\)?|/)(?:[^\W\d]|[_.])[^\s<>\"'`|,;\r\n]*"
QUOTED_CREDENTIAL = r'''\b(?:password|passwd|api[_ -]?key|access[_ -]?token|secret)["']\s*[:=]\s*(?:["'][^"'\r\n]+["']|[^\s,;}]+)'''
URI_PATH = r'''(?:\bfile://[^\s<>"'`]+|(?<!https)(?<!http):/(?!/)[^\s<>"'`]+)'''
SECRET = re.compile(SECRET.pattern + '|' + CREDENTIAL + '|' + LOCAL_PATH + '|' + QUOTED_CREDENTIAL + '|' + URI_PATH)
# Serialized event metadata legitimately has a session identifier. Narrative
# fields and historical text have no such exception: JSON-looking credentials
# are still credentials. Keep those two scan contexts separate.
TEXT_SECRET = re.compile(SECRET.pattern + r'''|\bsession(?:[_-]?(?:id|key|token))?["']\s*[:=]\s*(?:["'][^"'\r\n]+["']|[^\s,;}]+)''')


def redact_local_paths(text):
    # Preserve complete HTTP(S) URLs before considering local-path tokens.
    pattern=re.compile(r"(?P<url>https?://[^\s<>\"'`]+)|(?P<path>"+URI_PATH+'|'+LOCAL_PATH+r")",re.I)
    return pattern.sub(lambda m:m.group(0) if m.group('url') else '[local-path]',text)

SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')

def now():
    return dt.datetime.now(KST).isoformat(timespec='microseconds')

def safe(text):
    if not isinstance(text, str) or len(text) > 2400 or TEXT_SECRET.search(text):
        raise ValueError('sensitive_or_invalid_text')
    if any(ord(c) < 32 and c not in '\n\t' for c in text):
        raise ValueError('control_character')
    return text

def validate(value):
    required = {'topic', 'repo', 'business', 'sensitive', *FIELDS}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('invalid_schema')
    if value['sensitive'] is not False or not isinstance(value['business'], bool):
        raise ValueError('sensitive_or_invalid_flag')
    if not isinstance(value['topic'],str) or not SLUG.fullmatch(value['topic']):
        raise ValueError('invalid_topic')
    if not isinstance(value['repo'],str) or (value['repo'] and not SLUG.fullmatch(value['repo'])):
        raise ValueError('invalid_repo')
    for key in FIELDS:
        if not isinstance(value[key], list) or len(value[key]) > 8:
            raise ValueError('invalid_list')
        for s in value[key]: safe(s)
    for link in value['links']:
        if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./#-]*)?',link):
            raise ValueError('unapproved_link')
    return value

def atomic(path, text):
    path = Path(path)
    for parent in (path, *path.parents):
        if parent.is_symlink(): raise ValueError('symlink_blocked')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.workspace-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

class Ledger:
    def __init__(self, state):
        self.state=Path(state).resolve(); self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.state,0o700)
        self.db=sqlite3.connect(self.state/'ledger.sqlite',timeout=15)
        self.db.execute('pragma journal_mode=WAL')
        self.db.executescript('''
        create table if not exists meta(key text primary key,value text not null);
        create table if not exists events(id text primary key,session text not null,turn text not null,stamp text not null,payload text not null);
        create table if not exists event_groups(id text primary key,group_id text not null);
        create table if not exists attempts(id text primary key,status text not null,attempts integer not null default 0);
        create table if not exists attempt_reasons(id text primary key,reason text not null);
        create table if not exists topics(name text primary key,stage text not null);
        ''')
        self.db.commit()
    def get(self,key,default=None):
        row=self.db.execute('select value from meta where key=?',(key,)).fetchone()
        return row[0] if row else default
    def set(self,key,value):
        with self.db:self.db.execute('insert or replace into meta values(?,?)',(key,str(value)))
    def record(self, session, turn, payload, stamp=None):
        validate(payload)
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',session+turn):
            raise ValueError('invalid_source_id')
        eid=hashlib.sha256((session+':'+turn).encode()).hexdigest()[:24]
        stamp=stamp or now(); dt.datetime.fromisoformat(stamp)
        encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        existing=self.db.execute('select payload from events where id=?',(eid,)).fetchone()
        if existing:
            if existing[0]!=encoded: raise ValueError('immutable_event_conflict')
            return eid,False
        with self.db:
            self.db.execute('insert into events values(?,?,?,?,?)',(eid,session,turn,stamp,encoded))
        return eid,True
    def events(self):
        groups=dict(self.db.execute('select id,group_id from event_groups'))
        return [dict(id=x[0],session=x[1],session_group=groups.get(x[0],hashlib.sha256(x[1].encode()).hexdigest()[:16]),turn=x[2],stamp=x[3],payload=json.loads(x[4])) for x in self.db.execute('select * from events order by stamp,id')]

def topic_states(events, overrides=None):
    groups={}
    for event in events: groups.setdefault(event['payload']['topic'],[]).append(event)
    states={}
    for topic,items in groups.items():
        latest=dict(items[-1]['payload'])
        latest['repo']=next((e['payload']['repo'] for e in reversed(items) if e['payload']['repo']),'')
        latest['business']=any(e['payload']['business'] for e in items)
        sessions=len({e['session_group'] for e in items})
        score=(2 if sessions>=2 else 0)+(1 if any(e['payload']['todo'] for e in items) else 0)+(1 if any(e['payload']['decisions'] for e in items) else 0)+(2 if latest['business'] else 0)+(1 if len({s for e in items for s in e['payload']['links']})>=3 else 0)
        stage='project' if latest['repo'] else ('candidate' if score>=4 else ('topic' if sessions>=2 or latest['todo'] or latest['decisions'] else 'session'))
        stage=(overrides or {}).get(topic,stage)
        outstanding=[]
        for event in items:
            outstanding=list(dict.fromkeys(outstanding+event['payload']['todo']))
            outstanding=[x for x in outstanding if x not in event['payload']['completed_todo']]
        latest=dict(latest,todo=outstanding,links=list(dict.fromkeys(x for e in items for x in e['payload']['links']))[-16:])
        states[topic]={'stage':stage,'score':score,'events':items,'latest':latest,'sessions':sessions}
    return states

def bullet(values): return '\n'.join('- '+v.replace('\n',' ') for v in values) or '- 확인된 기록 없음'

def _render(ledger, root, events=None):
    root=Path(root).resolve(); events=ledger.events() if events is None else events; overrides=dict(ledger.db.execute('select name,stage from topics'))
    states=topic_states(events,overrides); days={}
    atomic(root/'audit/topic-stages.json',json.dumps(overrides,sort_keys=True)+'\n')
    for e in events:
        day=dt.datetime.fromisoformat(e['stamp']).astimezone(KST).date().isoformat()
        days.setdefault(day,[]).append(e)
    for day,items in days.items():
        # One compact file per day keeps commits below the file limit.
        public=[{'id':e['id'],'stamp':e['stamp'],'source':'codex-refined','session_group':e['session_group'],'memory':e['payload']} for e in items]
        atomic(root/'events'/f'{day}.json',json.dumps(public,ensure_ascii=False,indent=2)+'\n')
        atomic(root/'daily'/f'{day}.md','# '+day+'\n\n'+'\n\n'.join('## '+e['payload']['topic']+'\n'+bullet(e['payload']['status']) for e in items)+'\n')
    for topic,st in states.items():
        p=st['latest']; es=st['events']; decisions=list(dict.fromkeys(s for e in es for s in e['payload']['decisions']))[-24:]
        failures=list(dict.fromkeys(s for e in es for s in e['payload']['failed_approaches']))[-12:]
        context=list(dict.fromkeys(next((e['payload']['context'] for e in es if e['payload']['context']),[])+p['context']))
        body=f"# {topic}\n\nStage: {st['stage']} · signals: {st['score']} · sessions: {st['sessions']}\n\nUpdated: {es[-1]['stamp']}\n\n"
        for title,values in [('CONTEXT',context),('STATUS',p['status']),('DECISIONS',decisions),('TODO',p['todo']),('FAILED APPROACHES',failures),('LINKS',p['links'])]: body+='## '+title+'\n'+bullet(values)+'\n\n'
        body+='## INDEX\n'+bullet([f"[{e['stamp'][:10]}](../daily/{e['stamp'][:10]}.md) · {e['id']}" for e in es[-10:]])+'\n'
        atomic(root/'memory'/f'{topic}.md',body)
    index='# AI Workspace index\n\nRead the matching memory file: CONTEXT → STATUS → DECISIONS → TODO. These are dated observations; missing evidence means unknown. Historical chats are not required.\n\n'
    for stage in ('project','candidate','topic','session','archive'):
        index+='## '+stage+'\n'+bullet([f"[{t}](memory/{t}.md)" for t,s in sorted(states.items()) if s['stage']==stage])+'\n\n'
    atomic(root/'INDEX.md',index)
    return states

def generated_files(root):
    root=Path(root)
    names=['INDEX.md','audit/topic-stages.json']
    for folder in ('events','daily','memory'):
        parent=root/folder
        if parent.is_symlink():raise ValueError('symlink_blocked')
        if parent.exists():
            for p in parent.rglob('*'):
                if p.is_symlink():raise ValueError('symlink_blocked')
                if p.is_file():names.append(str(p.relative_to(root)))
    result={}
    for name in names:
        p=root/name
        if p.is_symlink():raise ValueError('symlink_blocked')
        if p.is_file():result[name]=p.read_bytes()
    return result

def projection(ledger, events=None):
    with tempfile.TemporaryDirectory(prefix='workspace-projection-') as tmp:
        _render(ledger,tmp,events)
        return generated_files(tmp)

def remember_generated(ledger,root):
    values={k:hashlib.sha256(v).hexdigest() for k,v in generated_files(root).items()}
    ledger.set('render_manifest',json.dumps(values,sort_keys=True))

def protect_generated(ledger,root):
    previous=ledger.get('render_manifest')
    if previous is None:return
    expected=json.loads(previous)
    actual={k:hashlib.sha256(v).hexdigest() for k,v in generated_files(root).items()}
    if actual!=expected:raise ValueError('generated_manual_edit')

def render(ledger,root):
    root=Path(root).resolve()
    protect_generated(ledger,root)
    before=generated_files(root)
    output=projection(ledger)
    for name,data in output.items():
        p=root/name
        existing=p.read_bytes() if p.is_file() else None
        if existing!=before.get(name):raise ValueError('generated_concurrent_edit')
        if existing!=data:atomic(p,data.decode())
    if generated_files(root)!=output:raise ValueError('generated_concurrent_edit')
    remember_generated(ledger,root)
    return topic_states(ledger.events(),dict(ledger.db.execute('select name,stage from topics')))

def query(ledger, text):
    events=ledger.events(); states=topic_states(events,dict(ledger.db.execute('select name,stage from topics')))
    if '후보' in text or 'candidate' in text.lower():
        names=[t for t,s in states.items() if s['stage']=='candidate']; return '프로젝트 후보\n'+bullet(names)
    if '결정' in text:
        cutoff=dt.datetime.now(KST)-dt.timedelta(days=7)
        return '최근 7일 결정사항\n'+bullet([s for e in events if dt.datetime.fromisoformat(e['stamp'])>=cutoff for s in e['payload']['decisions']][-16:])
    if '오늘' in text or text=='brief':
        today=dt.datetime.now(KST).date()
        recent=[e for e in events if dt.datetime.fromisoformat(e['stamp']).astimezone(KST).date()==today]
        topics=list(dict.fromkeys(e['payload']['topic'] for e in recent))
        return '오늘의 AI Workspace\n'+bullet([t+': '+ ' / '.join(states[t]['latest']['status']) for t in topics][-12:])
    matches=[t for t in states if t.replace('-','').lower() in text.replace(' ','').replace('-','').lower()]
    if len(matches)!=1:return '작업 이름을 지정해 주세요. 조회 가능: '+', '.join(sorted(states))
    t=matches[0];s=states[t]
    return t+' · '+s['stage']+'\n'+bullet(s['latest']['status'])+'\n다음 작업\n'+bullet(s['latest']['todo'])


def read_refined(root):
    root=Path(root); events={}
    for path in sorted((root/'events').glob('*.json')):
        if path.is_symlink() or path.parent.is_symlink():raise ValueError('symlink_blocked')
        if path.stat().st_size>2_000_000:raise ValueError('oversize_file')
        data=json.loads(path.read_text())
        if not isinstance(data,list):raise ValueError('invalid_event_file')
        for event in data:
            if not isinstance(event,dict) or set(event)-{'id','stamp','source','session_group','memory'}:raise ValueError('invalid_event')
            validate(event['memory']);stamp=dt.datetime.fromisoformat(event['stamp'])
            if stamp.tzinfo is None:raise ValueError('timezone_required')
            if path.stem!=stamp.astimezone(KST).date().isoformat():raise ValueError('event_day_mismatch')
            if not re.fullmatch('[a-f0-9]{24}',event['id']):raise ValueError('invalid_event_id')
            group=event.get('session_group',event['id'])
            if not re.fullmatch('[a-f0-9]{16,24}',group):raise ValueError('invalid_group')
            normalized=dict(id=event['id'],stamp=event['stamp'],session_group=group,memory=event['memory'])
            if event['id'] in events and events[event['id']]!=normalized:raise ValueError('immutable_event_conflict')
            events[event['id']]=normalized
    stages_path=root/'audit/topic-stages.json'
    if stages_path.is_symlink():raise ValueError('symlink_blocked')
    stages=json.loads(stages_path.read_text()) if stages_path.exists() else {}
    if not isinstance(stages,dict) or any(not SLUG.fullmatch(k) or v not in {'topic','candidate','project','archive'} for k,v in stages.items()):raise ValueError('invalid_stage_state')
    return events,stages

def import_refined(ledger,root,*,stages_mode='merge'):
    """Union immutable events; never replace a populated ledger or import raw sessions."""
    incoming,remote_stages=read_refined(root)
    current={e['id']:e for e in ledger.events()};rows=[];groups=[]
    for eid,e in incoming.items():
        if eid in current:
            old=current[eid]
            if (old['payload'],old['stamp'],old['session_group'])!=(e['memory'],e['stamp'],e['session_group']):raise ValueError('immutable_event_conflict')
        else:
            rows.append((eid,e['session_group'],eid,e['stamp'],json.dumps(e['memory'],ensure_ascii=False,sort_keys=True)))
            groups.append((eid,e['session_group']))
    local=dict(ledger.db.execute('select name,stage from topics'))
    base=json.loads(ledger.get('remote_stages','{}'));merged=dict(local)
    for topic in set(base)|set(local)|set(remote_stages):
        b=base.get(topic);l=local.get(topic);r=remote_stages.get(topic)
        if stages_mode=='ignore':value=l
        elif stages_mode=='restore':value=r
        elif l==r or r==b:value=l
        elif l==b:value=r
        else:raise ValueError('stage_conflict')
        if value is None:merged.pop(topic,None)
        else:merged[topic]=value
    with ledger.db:
        ledger.db.executemany('insert into events values(?,?,?,?,?)',rows)
        ledger.db.executemany('insert into event_groups values(?,?)',groups)
        ledger.db.execute('delete from topics')
        ledger.db.executemany('insert into topics values(?,?)',merged.items())
        ledger.db.execute('insert or replace into meta values(?,?)',('remote_stages',json.dumps(base if stages_mode=='ignore' else remote_stages,sort_keys=True)))
    return len(rows)

def restore(ledger,root):
    if ledger.events():raise ValueError('restore_requires_empty_ledger')
    return import_refined(ledger,root,stages_mode='restore')

def import_inbox(ledger,root):
    """Human/ChatGPT edits enter as new immutable refined JSON records."""
    folder=Path(root)/'inbox'
    if folder.is_symlink():raise ValueError('symlink_blocked')
    rows=[];groups=[]
    existing={e['id']:e for e in ledger.events()}
    for path in sorted(folder.glob('*.json')):
        if path.is_symlink() or path.stat().st_size>64_000:raise ValueError('invalid_inbox_file')
        if not re.fullmatch('[a-f0-9]{24}',path.stem):raise ValueError('invalid_inbox_id')
        data=json.loads(path.read_text())
        if not isinstance(data,dict) or set(data)!={'stamp','memory'}:raise ValueError('invalid_inbox_schema')
        validate(data['memory']);stamp=dt.datetime.fromisoformat(data['stamp'])
        if stamp.tzinfo is None:raise ValueError('timezone_required')
        session='inbox'+path.stem;eid=hashlib.sha256((session+':entry').encode()).hexdigest()[:24]
        if eid in existing:
            if (existing[eid]['payload'],existing[eid]['stamp'])!=(data['memory'],data['stamp']):raise ValueError('immutable_inbox_conflict')
            continue
        rows.append((eid,session,'entry',data['stamp'],json.dumps(data['memory'],ensure_ascii=False,sort_keys=True)))
        groups.append((eid,hashlib.sha256(session.encode()).hexdigest()[:16]))
    with ledger.db:
        ledger.db.executemany('insert into events values(?,?,?,?,?)',rows)
        ledger.db.executemany('insert into event_groups values(?,?)',groups)
    return len(rows)
