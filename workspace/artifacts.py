"""Read-only, explicit-root artifact search. Derived data never belongs in Git."""
from __future__ import annotations
import contextlib
import hashlib
import io
import json
import os
import plistlib
import sys
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from .core import CREDENTIAL, QUOTED_CREDENTIAL
from .history import redact, searchable, terms

MAX_BYTES = 32 * 1024 * 1024
MAX_TEXT = 2 * 1024 * 1024
EXTENSIONS = {'.md', '.txt', '.json', '.jsonl', '.pdf', '.docx'}
DENY = {'node_modules', 'venv', 'venvs', '__pycache__', 'cache', 'caches', 'library',
        'system', 'applications', 'sessions', 'archived_sessions', 'codexstorage',
        'vendor', 'deps', 'site-packages', 'logs', 'credentials', 'secrets', 'config', 'settings', 'dist', 'build'}
BAD_NAME = re.compile(r'(?i)(?:^\.|credential|secret|password|token|api[_-]?key|ssh[_-]?key|^id_(?:rsa|ed25519)|^settings\.|^config\.|^auth\.|^rollout-)')
# Credential findings reject the entire file. Personal information and embedded
# local links use the existing excerpt redactor, while the authorized path is metadata.
SECRET = re.compile(CREDENTIAL + '|' + QUOTED_CREDENTIAL + r'|sk-[a-zA-Z0-9_-]{12,}|gh[pousr]_[a-zA-Z0-9]{12,}|github_pat_\w+|-----BEGIN .*PRIVATE KEY|(?:password|passwd|api[_ -]?key|secret)\s*[:=]\s*\S+', re.I)


def _blocked(name):
    return name.lower() in DENY or bool(BAD_NAME.search(name))


def _root_ancestors_allowed(path):
    """Permit an explicitly registered iCloud Obsidian vault or subfolder, not Library."""
    denied = [(i, part) for i, part in enumerate(path.parts) if part.lower() in DENY]
    if not denied:
        return True
    prefix = Path.home() / 'Library/Mobile Documents/iCloud~md~obsidian/Documents'
    try:
        relative = path.relative_to(prefix)
    except ValueError:
        return False
    library_index = len(Path.home().parts)
    return (len(relative.parts) >= 1
            and denied == [(library_index, 'Library')]
            and not any(_blocked(part) for part in relative.parts))


def _plain_path(path):
    return path.is_absolute() and '..' not in path.parts and not any(p.is_symlink() for p in (path, *path.parents))


def _fingerprint(st):
    return f'{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}'


class ArtifactIndex:
    def __init__(self, state):
        self._volumes = {}
        self.state = Path(state).absolute()
        if not _plain_path(self.state) or any((p / '.git').exists() for p in (self.state, *self.state.parents)):
            raise ValueError('artifact_state_not_private')
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state.chmod(0o700)
        self.path = self.state / 'artifacts.sqlite'
        if self.path.is_symlink():
            raise ValueError('artifact_db_symlink')
        self.db = sqlite3.connect(self.path, timeout=10)
        self.path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          create table if not exists artifacts(id text primary key,path text unique,root text,
            label text,fingerprint text,mtime real,text text,checked real);
          create virtual table if not exists artifact_fts using fts5(id UNINDEXED, words);
          create table if not exists directories(root text,path text primary key,cursor text,checked real);
          create table if not exists errors(path text primary key,status text,stamp real);
          create table if not exists artifact_meta(key text primary key,value text);
        ''')
        version=self.db.execute("select value from artifact_meta where key='policy_version'").fetchone()
        if not version or version[0]!='2':
            # Derived data only: never serve text accepted by an older extractor policy.
            for table in ('artifacts','artifact_fts','errors','directories'):
                self.db.execute('delete from '+table)
            self.db.execute("insert or replace into artifact_meta values('policy_version','2')")
        self.db.commit()

    def close(self):
        self.db.close()

    def roots(self):
        path = self.state / 'artifact-roots.json'
        if not path.exists():
            return []
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError('invalid_artifact_roots')
        try:
            value = json.loads(path.read_text())
            roots = value['roots']
            if not isinstance(roots, list) or len(roots) > 32:
                raise ValueError()
            for root in roots:
                p = Path(root['path'])
                if not p.is_absolute() or '..' in p.parts or len(p.parts) < 4 or _blocked(p.name) or not _root_ancestors_allowed(p):
                    raise ValueError()
                if not isinstance(root['label'], str) or not root['label'] or SECRET.search(root['label']):
                    raise ValueError()
                if not all(isinstance(root[k], int) for k in ('device', 'inode')):
                    raise ValueError()
            return roots
        except (ValueError, KeyError, TypeError):
            raise ValueError('invalid_artifact_roots') from None

    def _availability(self, root):
        p = Path(root['path'])
        if not _plain_path(p):
            return 'root_not_allowed'
        try:
            s = p.stat()
            if not stat.S_ISDIR(s.st_mode):
                return 'root_unavailable'
            if s.st_ino != root['inode']:
                return 'root_identity_changed'
            if str(p).startswith('/Volumes/') and sys.platform == 'darwin':
                if not root.get('volume_uuid'):
                    return 'volume_identity_required'
                cache_key = (str(p), s.st_dev, s.st_ino)
                cached = self._volumes.get(cache_key)
                if cached and time.monotonic() - cached[0] < 5:
                    volume = cached[1]
                else:
                    try:
                        result = subprocess.run(['/usr/sbin/diskutil', 'info', '-plist', str(Path(*p.parts[:3]))], capture_output=True, timeout=5)
                        volume = plistlib.loads(result.stdout).get('VolumeUUID') if result.returncode == 0 else None
                    except Exception:
                        volume = None
                    self._volumes[cache_key] = (time.monotonic(), volume)
                if not volume or volume != root['volume_uuid']:
                    return 'volume_identity_changed'
            elif sys.platform != 'darwin' and s.st_dev != root['device']:
                return 'root_identity_changed'
            return 'available'
        except OSError:
            return 'external_ssd_disconnected' if str(p).startswith('/Volumes/') else 'root_unavailable'

    def _root(self, path):
        for root in self.roots():
            try:
                relative = path.relative_to(root['path'])
            except ValueError:
                continue
            if relative.parts and not any(_blocked(x) for x in relative.parts) and path.suffix.lower() in EXTENSIONS:
                return root
        return None

    def _source(self, path, root):
        """Open every component without following symlinks, including root ancestors."""
        if self._availability(root) != 'available':
            raise ValueError(self._availability(root))
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            current = Path('/')
            for part in path.parts[1:-1]:
                current = current / part
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
                if str(current) == root['path'] and os.fstat(fd).st_ino != root['inode']:
                    raise ValueError('root_identity_changed')
            source = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        finally:
            os.close(fd)
        return os.fdopen(source, 'rb')

    def _extract(self, path, root):
        with self._source(path, root) as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_BYTES:
                raise ValueError('unsupported_or_oversize_source')
            raw = f.read(MAX_BYTES + 1)
            if _fingerprint(st) != _fingerprint(os.fstat(f.fileno())):
                raise ValueError('source_changed')
        if self._availability(root) != 'available' or not _plain_path(path) or _fingerprint(path.stat()) != _fingerprint(st):
            raise ValueError('source_changed')
        suffix = path.suffix.lower()
        if suffix == '.pdf':
            executable = shutil.which('pdftotext')
            if not executable:
                raise ValueError('pdf_extractor_unavailable')
            # A private temporary output file bounds process output in memory.
            with tempfile.TemporaryFile() as output:
                proc = subprocess.run([executable, '-layout', '-', '-'], input=raw,
                                      stdout=output, stderr=subprocess.DEVNULL, timeout=20)
                if proc.returncode or output.tell() > MAX_TEXT:
                    raise ValueError('pdf_extraction_failed_or_oversize')
                output.seek(0)
                text = output.read().decode('utf-8', errors='replace')
        elif suffix == '.docx':
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info = archive.getinfo('word/document.xml')
                if info.file_size > MAX_TEXT or info.compress_size == 0 or info.file_size / info.compress_size > 200:
                    raise ValueError('docx_oversize')
                xml = archive.read(info)
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                    raise ValueError('docx_entity_blocked')
                tree = ET.fromstring(xml)
                text = '\n'.join(''.join(p.itertext()) for p in tree.iter() if p.tag.endswith('}p'))
        else:
            if len(raw) > MAX_TEXT or b'\x00' in raw:
                raise ValueError('text_oversize_or_binary')
            text = raw.decode('utf-8-sig')
            # Inspect decoded JSON keys/values; escapes must not hide credentials.
            if suffix == '.json':
                text = json.dumps(json.loads(text),ensure_ascii=False,indent=2)
            elif suffix == '.jsonl':
                text = '\n'.join(json.dumps(json.loads(line),ensure_ascii=False) for line in text.splitlines() if line.strip())
        if len(text) > MAX_TEXT:
            raise ValueError('text_oversize')
        if SECRET.search(text) or SECRET.search(path.name):
            raise ValueError('sensitive_content_blocked')
        return redact(text), st

    def _forget(self, identity):
        self.db.execute('delete from artifact_fts where id=?', (identity,))
        self.db.execute('delete from artifacts where id=?', (identity,))

    def _index_file(self, p, root, result):
        identity = hashlib.sha256(str(p).encode()).hexdigest()[:32]
        try:
            st = p.stat()
            old = self.db.execute('select fingerprint from artifacts where id=?', (identity,)).fetchone()
            if old and old[0] == _fingerprint(st):
                self.db.execute('update artifacts set checked=? where id=?', (time.time(), identity))
                result['unchanged'] += 1
                return
            text, st = self._extract(p, root)
            self._forget(identity)
            self.db.execute('insert into artifacts values(?,?,?,?,?,?,?,?)',
                            (identity, str(p), root['path'], root['label'], _fingerprint(st), st.st_mtime, text, time.time()))
            self.db.execute('insert into artifact_fts values(?,?)', (identity, searchable(str(p.relative_to(root['path'])).replace('_',' ') + ' ' + root['label'] + ' ' + text)))
            self.db.execute('delete from errors where path=?', (str(p),))
            result['indexed'] += 1
        except Exception as exc:
            self._forget(identity)
            status = str(exc) if isinstance(exc, ValueError) and re.fullmatch('[a-z_]+', str(exc)) else 'extraction_failed'
            self.db.execute('insert or replace into errors values(?,?,?)', (str(p), status, time.time()))
            result['errors'] += 1

    def index(self, budget=10):
        deadline = time.monotonic() + max(0.05, min(float(budget), 300))
        result = {'status': 'ok', 'indexed': 0, 'unchanged': 0, 'errors': 0, 'roots': []}
        roots = self.roots()
        allowed = {r['path']: r for r in roots}
        for old in self.db.execute('select id,path from artifacts').fetchall():
            if not self._root(Path(old['path'])):
                self._forget(old['id'])
        for old in self.db.execute('select path,root from directories').fetchall():
            if old['root'] not in allowed:
                self.db.execute('delete from directories where path=?', (old['path'],))
        available = {}
        for root in roots:
            status = self._availability(root)
            result['roots'].append({'label': root['label'], 'status': status})
            if status == 'available':
                available[root['path']] = root
                self.db.execute('insert or ignore into directories values(?,?,?,?)', (root['path'],root['path'],'',0))
        # Persistent directory queue plus last entry cursor bounds discovery and
        # rotates roots fairly. Metadata is refreshed, unchanged contents are not.
        queue = list(self.db.execute('select * from directories order by checked,path'))
        seen = set()
        while queue and time.monotonic() < deadline:
            directory = queue.pop(0)
            name = directory['path']; root = available.get(directory['root'])
            if not root or name in seen:
                continue
            seen.add(name)
            p = Path(name)
            try:
                relative = p.relative_to(root['path'])
                if any(_blocked(part) for part in relative.parts) or not _plain_path(p):
                    raise ValueError('directory_not_allowed')
                with os.scandir(p) as entries:
                    names = sorted(entry.name for entry in entries)
            except (OSError, ValueError):
                self.db.execute('delete from directories where path=?', (name,))
                continue
            cursor = directory['cursor']; complete = True
            for child in names:
                if child <= cursor:
                    continue
                if time.monotonic() >= deadline:
                    complete = False
                    break
                cursor = child
                if _blocked(child):
                    continue
                candidate = p / child
                try:
                    if candidate.is_symlink():
                        continue
                    if candidate.is_dir():
                        self.db.execute('insert or ignore into directories values(?,?,?,?)', (root['path'],str(candidate),'',0))
                        row = self.db.execute('select * from directories where path=?', (str(candidate),)).fetchone()
                        queue.append(row)
                    elif self._root(candidate):
                        self._index_file(candidate, root, result)
                except OSError:
                    result['errors'] += 1
            self.db.execute('update directories set cursor=?,checked=? where path=?', ('' if complete else cursor,time.time(),name))
            self.db.commit()
            if not complete:
                result['status'] = 'budget_exhausted'
        if queue:
            result['status'] = 'budget_exhausted'
        self.db.commit()
        if not roots:
            result['status'] = 'not_configured'
        return result

    def search(self, query, limit=5):
        tokens = terms(str(query)[:1000])[:24]
        roots = self.roots()
        output = {'status': 'ok' if roots else 'not_configured', 'results': [],
                  'roots': [{'label': r['label'], 'status': self._availability(r)} for r in roots]}
        if not tokens or SECRET.search(query):
            return output
        def candidates(match):
            return self.db.execute('''select a.*,bm25(artifact_fts) score from artifact_fts
            join artifacts a on a.id=artifact_fts.id where artifact_fts match ?
            order by score,a.mtime desc limit 200''', (match,)).fetchall()
        rows = candidates(' AND '.join('"' + t + '"' for t in tokens))
        mode = 'all_terms'
        if not rows and len(tokens) > 1:
            # Natural follow-up wording often adds words absent from the file.
            # This returns candidates only; callers must still read the source.
            rows = candidates(' OR '.join('"' + t + '"' for t in tokens))
            minimum = (len(tokens) + 1) // 2
            wanted = set(tokens)
            rows = [r for r in rows if len(wanted & set(terms(r['text'] + ' ' + r['label'] + ' ' + Path(r['path']).name.replace('_',' ')))) >= minimum]
            mode = 'partial_terms'
        # Prefer filenames matching the subject; newest revision wins within that group.
        rows.sort(key=lambda r:(-len(set(tokens)&set(terms(Path(r['path']).name.replace('_',' ')))),
                                -len(set(tokens)&set(terms(r['text']))),-r['mtime'],r['score']))
        for row in rows:
            p = Path(row['path']); root = self._root(p)
            if not root:
                continue
            status = self._availability(root)
            if status == 'available':
                try:
                    if not _plain_path(p):
                        continue
                    status = 'available' if _fingerprint(p.stat()) == row['fingerprint'] else 'source_changed_reindex_required'
                except OSError:
                    status = 'source_missing'
            text = row['text'] if status == 'available' else ''
            locations = [text.lower().find(t) for t in tokens if text.lower().find(t) >= 0]
            start = max(0, min(locations, default=0) - 100)
            output['results'].append({'id': row['id'], 'filename': p.name, 'path': str(p),
                'topic': p.stem.replace('_',' ')[:100], 'collection':row['label'], 'modified_at': row['mtime'], 'snippet': text[start:start + 700],
                'score': row['score'], 'match_mode': mode, 'status': status})
            if len(output['results']) >= max(1, min(int(limit), 20)):
                break
        return output

    def read(self, artifact_id, offset=0, limit=12000):
        identity = artifact_id
        row = self.db.execute('select * from artifacts where id=?', (str(identity),)).fetchone()
        if not row:
            return {'status': 'not_found'}
        p = Path(row['path']); root = self._root(p)
        if not root:
            return {'status': 'not_allowed'}
        status = self._availability(root)
        if status != 'available':
            return {'status': status, 'id': identity, 'path': str(p)}
        try:
            text, st = self._extract(p, root)
            if _fingerprint(st) != row['fingerprint']:
                return {'status': 'source_changed_reindex_required', 'id': identity}
        except Exception as exc:
            status = str(exc) if isinstance(exc, ValueError) and re.fullmatch('[a-z_]+', str(exc)) else 'source_unavailable'
            return {'status': status, 'id': identity}
        offset = max(0, int(offset)); limit = max(1, min(int(limit), 24000))
        end = min(len(text), offset + limit)
        return {'status': 'ok', 'id': identity, 'filename': p.name, 'path': str(p),
                'topic': p.stem.replace('_',' ')[:100], 'collection':root['label'], 'modified_at': st.st_mtime, 'text': text[offset:end],
                'offset': offset, 'next_offset': end if end < len(text) else None,
                'total_characters': len(text), 'content_sha256': hashlib.sha256(text.encode()).hexdigest(), 'redacted': True}
