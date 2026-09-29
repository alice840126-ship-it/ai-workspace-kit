"""Local-only document index/search/read; never publish source documents."""
import argparse
import fcntl
import json
from pathlib import Path
from .artifacts import ArtifactIndex


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,default=Path.home()/'.local/share/ai-workspace-kit')
    commands=parser.add_subparsers(dest='command',required=True)
    index=commands.add_parser('index');index.add_argument('--budget',type=float,default=10)
    search=commands.add_parser('search');search.add_argument('query');search.add_argument('--limit',type=int,default=5)
    read=commands.add_parser('read');read.add_argument('artifact_id');read.add_argument('--offset',type=int,default=0);read.add_argument('--limit',type=int,default=12000)
    args=parser.parse_args()
    try:
        # Same lock as scheduler and stdio bridge, no parallel extraction jobs.
        if args.state.is_symlink():raise ValueError('unsafe_state')
        args.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        lock_path=args.state/'lock'
        if lock_path.is_symlink():raise ValueError('unsafe_lock')
        with lock_path.open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            engine=ArtifactIndex(args.state)
            try:
                if args.command=='index':result=engine.index(budget=args.budget)
                elif args.command=='search':result=engine.search(args.query,limit=args.limit)
                else:result=engine.read(args.artifact_id,offset=args.offset,limit=args.limit)
            finally:engine.close()
    except BlockingIOError:result={'ok':False,'code':'workspace_busy','retryable':True}
    except Exception:result={'ok':False,'code':'artifact_request_rejected','retryable':False}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
