"""Portable public entrypoint. No background jobs, model calls or native chat access."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from .bridge import Bridge
from .core import atomic, render, restore, import_inbox, import_refined, protect_generated
from .warm import accept_checkpoint, collect_warm
from .retrieval import recall, repositories
from .reconcile import prepare
from .settings import repository, expected_origin

STATE=Path.home()/'.local/share/ai-workspace-kit'
MEMORY=Path.home()/'ai-workspace-memory'

def private_repo(name):
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',name):raise ValueError('invalid_repository_binding')
    r=subprocess.run(['gh','api','repos/'+name,'--jq','.private'],capture_output=True,text=True,timeout=30)
    if r.returncode or r.stdout.strip()!='true':raise ValueError('private_repo_unverified')

def init(root,state):
    root=Path(root).absolute();state=Path(state).absolute()
    # Index/credential state must never be underneath a Git checkout or memory tree.
    from .artifacts import _plain_path
    if not _plain_path(root) or not _plain_path(state):raise ValueError('unsafe_path')
    if root==state or root in state.parents or state in root.parents:raise ValueError('separate_state_required')
    if any((p/'.git').exists() for p in (state,*state.parents)):raise ValueError('state_inside_git')
    marker=root/'audit/repositories.json'
    if marker.exists():raise ValueError('already_initialized')
    # A new private clone with only a README and .git is also acceptable.
    if root.exists() and any(p.name not in {'.git','README.md'} for p in root.iterdir()):raise ValueError('memory_directory_not_empty')
    if state.exists() and any(state.iterdir()):raise ValueError('state_directory_not_empty')
    root.mkdir(parents=True,exist_ok=True);state.mkdir(parents=True,exist_ok=True,mode=0o700)
    atomic(marker,json.dumps({'repositories':[]}))
    atomic(root/'.gitignore','*.sqlite*\n.env*\n__pycache__/\n.local/\n')
    with Bridge(state).locked() as ledger:render(ledger,root)
    return {'ok':True,'mode':'local','publication':'not_configured'}

def bind(root,state,name):
    private_repo(name)
    if not (Path(root)/'audit/repositories.json').is_file():raise ValueError('memory_not_initialized')
    r=subprocess.run(['git','-C',str(root),'remote','get-url','origin'],capture_output=True,text=True,timeout=10)
    if r.returncode or r.stdout.strip()!='https://github.com/'+name+'.git':raise ValueError('unexpected_remote')
    path=Path(state)/'github-repository.json'
    if path.exists():raise ValueError('binding_exists')
    atomic(path,json.dumps({'repository':name}));path.chmod(0o600)
    return {'ok':True,'publication':'private_repository_bound'}

def allow_root(state,path,label):
    from .artifacts import ArtifactIndex,_plain_path
    p=Path(path).absolute()
    if not _plain_path(p) or not p.is_dir():raise ValueError('root_not_allowed')
    st=p.stat();entry=dict(path=str(p),label=label,device=st.st_dev,inode=st.st_ino)
    if str(p).startswith('/Volumes/') and sys.platform=='darwin':
        r=subprocess.run(['/usr/sbin/diskutil','info','-plist',str(Path(*p.parts[:3]))],capture_output=True,timeout=5)
        volume=plistlib.loads(r.stdout).get('VolumeUUID') if r.returncode==0 else None
        if not volume:raise ValueError('volume_identity_unavailable')
        entry['volume_uuid']=volume
    index=ArtifactIndex(state)
    try:
        roots=index.roots()
        if any(x['path']==str(p) for x in roots):raise ValueError('root_already_registered')
        # Validate candidate with the exact reader policy before replacing config.
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            probe=ArtifactIndex(Path(temp).resolve())
            try:
                atomic(probe.state/'artifact-roots.json',json.dumps({'roots':roots+[entry]}));probe.roots()
            finally:probe.close()
        cfg=Path(state)/'artifact-roots.json';atomic(cfg,json.dumps({'roots':roots+[entry]}));cfg.chmod(0o600)
    finally:index.close()
    return {'ok':True,'roots':len(roots)+1}

def doctor():
    import sqlite3
    db=sqlite3.connect(':memory:');db.execute('create virtual table f using fts5(text)');db.close()
    try:
        from mcp.server import MCPServer
        mcp=True
    except ImportError:mcp=False
    return {'ok':mcp,'python':sys.version.split()[0],'fts5':True,'mcp':mcp,
            'optional_tools':{x:bool(shutil.which(x)) for x in ('git','gh','gitleaks','pdftotext')},
            'native_history_auto_scan':False,'model_calls':False}

def run(a):
    if a.command=='doctor':return doctor()
    if a.command=='init':return init(a.memory,a.state)
    if a.command=='bind-github':
        with Bridge(a.state).locked():return bind(a.memory,a.state,a.repository)
    if a.memory==a.state or a.memory in a.state.parents or a.state in a.memory.parents:
        raise ValueError('separate_state_required')
    with Bridge(a.state).locked() as ledger:
        if a.command=='allow-root':return allow_root(a.state,a.path,a.label)
        if a.command=='recall':return recall(ledger,a.query,allow_cold=False)
        if a.command in ('checkpoint','tick','sync','restore'):
            if not (a.memory/'audit/repositories.json').is_file():raise ValueError('memory_not_initialized')
            bound=(a.state/'github-repository.json').is_file()
            if bound:prepare(a.memory,ledger)
            elif a.command=='sync':raise ValueError('github_not_bound')
            else:
                protect_generated(ledger,a.memory)
                import_refined(ledger,a.memory)
            import_inbox(ledger,a.memory)
            result={'ok':True}
            if a.command=='checkpoint':
                raw=sys.stdin.read(32001)
                if len(raw)>32000:raise ValueError('checkpoint_too_large')
                result.update(accept_checkpoint(ledger,json.loads(raw)))
            result['warm']=collect_warm(ledger,repositories(a.memory))
            render(ledger,a.memory)
            if a.command=='tick' and (a.state/'artifact-roots.json').is_file():
                from .artifacts import ArtifactIndex
                index=ArtifactIndex(a.state)
                try:result['artifacts']=index.index(budget=5)
                finally:index.close()
            if bound and a.command in ('tick','sync'):
                from .runtime import publish
                result['published_commit']=publish(a.memory,ledger,include_source=False)
            else:result['publication']='local_only'
            return result
    raise ValueError('unsupported_command')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',type=Path,default=STATE);p.add_argument('--memory',type=Path,default=MEMORY)
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('init','checkpoint','tick','sync','restore','doctor'):sub.add_parser(name)
    b=sub.add_parser('bind-github');b.add_argument('repository')
    a=sub.add_parser('allow-root');a.add_argument('path');a.add_argument('--label',required=True)
    q=sub.add_parser('recall');q.add_argument('query')
    args=p.parse_args();args.state=args.state.expanduser().absolute();args.memory=args.memory.expanduser().absolute()
    try:
        value=run(args);print(json.dumps(value,ensure_ascii=False,indent=2))
        if value.get('ok') is False:raise SystemExit(1)
    except BlockingIOError:print('{"ok":false,"code":"workspace_busy"}');raise SystemExit(1)
    except Exception as e:
        # Only fixed labels from our own code; never provider output or source text.
        label=str(e)
        import re
        if not re.fullmatch('[a-z_]{3,80}',label):label=type(e).__name__
        print(json.dumps({'ok':False,'code':label}));raise SystemExit(1)

if __name__=='__main__':main()
