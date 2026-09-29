"""Machine-local private repository binding, never inferred from public source."""
import json
import re
from pathlib import Path

def repository(state):
    path=Path(state)/'github-repository.json'
    if path.is_symlink(): raise ValueError('unsafe_repository_binding')
    value=json.loads(path.read_text())['repository']
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+',value):
        raise ValueError('invalid_repository_binding')
    return value

def expected_origin(state):
    return 'https://github.com/'+repository(state)+'.git'
