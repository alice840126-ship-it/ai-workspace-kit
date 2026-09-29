"""Quiet routine holds, stable incident identities, and confirmed recovery."""
from __future__ import annotations
import json
from pathlib import Path
import re
import shutil

TRANSIENT = {'locked','busy','uncommitted','branch_mismatch','checkout_changed_during_sync',
 'source_changed_during_read','source_changed_during_snapshot','checkout_changed_during_snapshot',
 'runtime_changed_during_plan','repository_changed_during_plan','runtime_changed_before_apply',
 'source_publish_requires_explicit_sync','generated_concurrent_edit','concurrent_checkout_change','dirty_receive_blocked','preexisting_staged_changes'}
SECURITY = {'private_repo_unverified','secret_scan_blocked','snapshot_secret_scan_blocked',
 'outgoing_secret_scan_blocked','history_secret_scan_failed','sensitive_generated_content',
 'unexpected_origin','unexpected_remote','symlink_blocked','symlink_asset','symlink_target',
 'symlink_repository','symlink_or_submodule_blocked'}
CONFLICT = {'diverged_history','generated_manual_edit','immutable_event_conflict','immutable_inbox_conflict',
 'stage_conflict','canonical_conflict_held','autosave_remote_parent_changed'}
RECOVERY_OBSERVATIONS = 3


def issue(code, prefix):
    # Neither provider output, a shell command nor a local path is user-facing.
    if code in TRANSIENT:return ('transient','')
    if code in SECURITY:return ('security:'+code,prefix+' 보안 검사 또는 저장소 권한 확인 필요')
    if code in CONFLICT:return ('conflict:'+code,prefix+' 변경 충돌 확인 필요')
    return ('failure',prefix+' 자동 갱신 오류: 상태 확인 필요')


def held_counts(ledger):
    return dict(ledger.db.execute("select coalesce(r.reason,'legacy_unclassified'),count(*) from attempts a left join attempt_reasons r on r.id=a.id where a.status='held' group by coalesce(r.reason,'legacy_unclassified')"))


def daily_hold_note(ledger):
    labels={'source_incomplete':'중단·미완료','source_sensitive':'민감정보 감지',
      'sensitive_or_invalid_flag':'민감 표시 또는 형식 검증','sensitive_or_invalid_text':'민감정보 또는 텍스트 검증',
      'unapproved_link':'허용되지 않은 링크','unknown_repository':'미등록 저장소',
      'immutable_event_conflict':'기록 내용 충돌','legacy_unclassified':'기존 기록 원인 미분류'}
    counts=held_counts(ledger)
    if not counts:return ''
    grouped={}
    for reason,count in counts.items():
        label=labels.get(reason,'기록 형식 검증');grouped[label]=grouped.get(label,0)+count
    return '정제 기록 보류: '+', '.join(f'{name} {count}건' for name,count in sorted(grouped.items()))+'. 보류 기록은 GitHub에 올리지 않았습니다.'


def observations(ledger,home=None):
    home=Path(home) if home is not None else Path.home();out={}
    out['storage:sessions']=('ok','') if (home/'.codex/sessions').exists() else ('missing','원본 세션 SSD 연결 확인 필요')
    out['storage:disk']=('ok','') if shutil.disk_usage(home).free>=10*1024**3 else ('low','내부 디스크 여유 10GiB 미만')
    receipt=home/'.codex/state/codex-config-sync-last.json'
    if receipt.exists():
        try:
            data=json.loads(receipt.read_text())
            if data.get('status')=='locked':out['config']=('transient','')
            else:out['config']=issue(data.get('code') or data.get('error'),'Codex 설정') if data.get('ok') is False else ('ok','')
        except (OSError,ValueError,TypeError,AttributeError):out['config']=('receipt','Codex 설정 동기화 영수증 확인 필요')
    receipt=home/'.codex/state/canonical-sync/projects-last.json'
    if receipt.exists():
        try:
            entries=json.loads(receipt.read_text()).get('projects',[])
            if not isinstance(entries,list):raise ValueError('invalid_receipt')
            out['projects:receipt']=('ok','')
            for i,entry in enumerate(entries):
                name=entry.get('project','')
                identity=name if isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',name) else 'entry-'+str(i)
                label=identity.rsplit('/',1)[-1] if '/' in identity else '등록 프로젝트'
                for channel,data in [('sync',entry),('autosave',entry.get('autosave',{}))]:
                    scope='project:'+identity+':'+channel
                    if data.get('status') in {'busy','uncommitted'}:out[scope]=('transient','')
                    elif data.get('ok') is False:out[scope]=issue(data.get('code'),label+' '+('자동 보관' if channel=='autosave' else '저장소 동기화'))
                    elif data.get('ok') is True:out[scope]=('ok','')
                    # Missing/incomplete receipts never prove recovery.
        except (OSError,ValueError,TypeError,AttributeError):out['projects:receipt']=('receipt','프로젝트 자동 보관 영수증 확인 필요')
    out['compaction']=('blocked','요약 호출 실패: 원인 확인 후 재개 필요') if ledger.get('compaction_blocked')=='true' else ('ok','')
    return out


def notification(ledger,current):
    """A different failure never clears another incident's deduplication key."""
    try:stored=json.loads(ledger.get('notification_incidents_v1','{}'))
    except (ValueError,TypeError):stored={}
    if not isinstance(stored,dict):stored={}
    stored={key:value for key,value in stored.items() if isinstance(value,dict)}
    messages=[]
    for scope,(code,message) in sorted(current.items()):
        if code=='transient':
            for value in stored.values():
                if value.get('scope')==scope:value['recovery']=0
            continue  # active editing is neither an incident nor proof of recovery
        if code=='ok':
            for key,value in stored.items():
                if value.get('scope')==scope and value.get('active'):
                    value['recovery']=value.get('recovery',0)+1
                    if value['recovery']>=RECOVERY_OBSERVATIONS:value['active']=False
            continue
        # Any unresolved issue in this scope interrupts its recovery sequence.
        for value in stored.values():
            if value.get('scope')==scope:value['recovery']=0
        key=scope+'|'+code;previous=stored.get(key,{})
        if not previous.get('active'):messages.append(message)
        stored[key]={'scope':scope,'active':True,'recovery':0}
    ledger.set('notification_incidents_v1',json.dumps(stored,sort_keys=True))
    return 'AI Workspace 확인 필요: '+' | '.join(dict.fromkeys(messages)) if messages else '[SILENT]'


def health_report(current):
    messages=[message for code,message in current.values() if code not in {'ok','transient'}]
    return 'AI Workspace 확인 필요: '+' | '.join(dict.fromkeys(messages)) if messages else '[SILENT]'
