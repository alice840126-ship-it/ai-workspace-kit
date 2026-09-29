"""Receive GitHub refined records before producing any derived state.

No force push, rebase, raw session import, or last-writer-wins resolution.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from .core import (Ledger, atomic, generated_files, import_refined, projection,
                   protect_generated, remember_generated, restore, read_refined)

from .settings import expected_origin

def git(root,*args):
    r=subprocess.run(['git','-C',str(root),*args],capture_output=True,timeout=90)
    if r.returncode:raise RuntimeError('git_'+args[0]+'_failed')
    return r.stdout.decode().strip()

def generated(name):
    return name in {'INDEX.md','audit/topic-stages.json'} or name.split('/')[0] in {'events','daily','memory'}

def snapshot(root,ref,destination):
    records=git(root,'ls-tree','-r',ref).splitlines()
    for row in records:
        metadata,name=row.split('\t',1)
        if not generated(name):continue
        mode,kind,_=metadata.split()
        if mode not in {'100644','100755'} or kind!='blob' or '..' in Path(name).parts:raise ValueError('unsafe_generated_tree')
        data=subprocess.run(['git','-C',str(root),'show',ref+':'+name],capture_output=True,timeout=30)
        if data.returncode or len(data.stdout)>2_000_000:raise ValueError('invalid_generated_blob')
        p=Path(destination)/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data.stdout)

def verify_projection(root):
    """Even committed/manual GitHub edits to generated Markdown must not disappear."""
    with tempfile.TemporaryDirectory(prefix='workspace-verify-') as tmp:
        check=Ledger(Path(tmp)/'state')
        try:
            restore(check,root)
            actual=generated_files(root)
            if actual!=projection(check):
                # Migration: old renderer broke timestamp ties by insertion order.
                # Accept only an exact recomputation of that legacy projection.
                incoming,_=read_refined(root);rank={eid:i for i,eid in enumerate(incoming)}
                legacy=sorted(check.events(),key=lambda e:(e['stamp'],rank[e['id']]))
                if actual!=projection(check,legacy):raise ValueError('generated_manual_edit')
        finally:check.db.close()

def prepare(root,ledger,*,check_origin=True):
    root=Path(root).resolve()
    if check_origin and git(root,'remote','get-url','origin')!=expected_origin(ledger.state):raise ValueError('unexpected_remote')
    if git(root,'branch','--show-current')!='main':raise ValueError('unexpected_branch')
    if git(root,'diff','--cached','--name-only'):raise ValueError('preexisting_staged_changes')
    protect_generated(ledger,root)
    git(root,'fetch','--no-tags','origin','main')
    head=git(root,'rev-parse','HEAD');remote=git(root,'rev-parse','FETCH_HEAD')
    with tempfile.TemporaryDirectory(prefix='workspace-receive-') as tmp:
        tmp=Path(tmp);remote_tree=tmp/'remote';head_tree=tmp/'head'
        snapshot(root,remote,remote_tree);verify_projection(remote_tree)
        snapshot(root,head,head_tree);verify_projection(head_tree)
        # Without an established render manifest, accept only the existing ledger
        # projection or the checked-in, independently regenerated projection.
        protect_generated(ledger,root)
        local=generated_files(root)
        final_expected=local
        if ledger.get('render_manifest') is None and local not in (projection(ledger),generated_files(head_tree)):
            raise ValueError('generated_manual_edit')
        if remote!=head:
            ancestor=subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',head,remote],capture_output=True)
            if ancestor.returncode:
                remote_ancestor=subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',remote,head],capture_output=True)
                if remote_ancestor.returncode:raise ValueError('diverged_history')
                # A failed push may leave our verified local commit ahead.
            else:
                dirty=git(root,'ls-files','--modified','--deleted','--others','--exclude-standard').splitlines()
                if any(not generated(n) for n in dirty):raise ValueError('dirty_receive_blocked')
                # Validate union before changing the checkout. Temporary ledger
                # catches immutable/stage conflicts without partial real import.
                probe=Ledger(tmp/'probe')
                try:
                    ledger.db.backup(probe.db)
                    import_refined(probe,remote_tree)
                finally:probe.db.close()
                baseline=generated_files(head_tree)
                journal=ledger.state/'receive-journal'
                journal.mkdir(mode=0o700,exist_ok=True)
                for name,data in local.items():atomic(journal/'files'/name,data.decode())
                atomic(journal/'transaction.json',json.dumps({'head':head,'remote':remote,'status':'prepared','files':list(local)}))
                # Restore only validated generated working edits, kept in the
                # local journal and ledger. Never touch user source/doc edits.
                for name in set(local)|set(baseline):
                    p=root/name
                    actual=p.read_bytes() if p.is_file() else None
                    if actual!=local.get(name):raise ValueError('generated_concurrent_edit')
                    if name in baseline:atomic(p,baseline[name].decode())
                    elif p.exists():p.unlink()
                if git(root,'rev-parse','HEAD')!=head:raise ValueError('concurrent_checkout_change')
                git(root,'merge','--ff-only',remote)
                final_expected=generated_files(remote_tree)
                atomic(journal/'transaction.json',json.dumps({'head':head,'remote':remote,'status':'received','files':list(local)}))
        import_refined(ledger,remote_tree)
        # Local ahead commits may include events absent in both DB and remote.
        import_refined(ledger,head_tree,stages_mode='ignore')
        if generated_files(root)!=final_expected:raise ValueError('generated_concurrent_edit')
        remember_generated(ledger,root)
        ledger.set('received_remote',remote)
    return remote
