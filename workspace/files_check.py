"""Offline smoke check of the installed filesystem MCP in an isolated subprocess."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import tempfile


async def check(root: Path) -> dict:
    from mcp import Client, StdioServerParameters

    server = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'workspace.bridge', '--state', str(root / 'state'),
              '--read-only', '--filesystem'],
        cwd=str(root),
    )
    async with Client(server) as client:
        names = sorted(tool.name for tool in (await client.list_tools()).tools)
        expected = {'local_file_create', 'local_file_write', 'local_file_edit',
                    'local_directory_create', 'local_file_copy', 'local_file_move',
                    'local_file_delete', 'local_file_restore', 'local_file_stat',
                    'local_file_read', 'local_file_search', 'local_file_history',
                    'local_file_diff', 'workspace_health', 'workspace_recall',
                    'search_local', 'read_local_artifact'}
        if set(names) != expected:
            raise RuntimeError('Unexpected MCP tool inventory')

        async def call(name, **arguments):
            result = await client.call_tool(name, arguments)
            data = result.structured_content
            if data is None:
                data = json.loads(result.content[0].text)
            if result.is_error:
                raise RuntimeError(f'{name}: protocol error')
            return data

        def require(condition, label):
            if not condition:
                raise RuntimeError(label)

        path = str(root / 'sample.txt')
        created = await call('local_file_create', path=path, content='first')
        require(created.get('verified'), 'Create verification failed')
        version = created['after']['version']
        edited = await call('local_file_edit', path=path, old_text='first',
                            new_text='second', expected_version=version)
        require(edited.get('verified'), 'Edit verification failed')
        read = await call('local_file_read', path=path)
        require(read.get('content') == 'second' and Path(path).read_text() == 'second',
                'Actual file reread failed')
        stale = await call('local_file_write', path=path, content='stale', expected_version=version)
        require(stale.get('ok') is False and Path(path).read_text() == 'second',
                'Stale version was not rejected')
        removed = await call('local_file_delete', path=path, expected_version=read['version'])
        require(removed.get('verified') and not Path(path).exists(), 'Delete verification failed')
        restored = await call('local_file_restore', operation_id=removed['operation_id'],
                              expected_version='missing')
        require(restored.get('verified') and Path(path).read_text() == 'second',
                'Restore verification failed')
        return dict(ok=True, tools=len(names), checks=['create', 'edit', 'read',
                    'stale-version rejection', 'recoverable delete', 'restore'],
                    scope='temporary files only; ChatGPT/tunnel not tested')


def main():
    with tempfile.TemporaryDirectory(prefix='ai-workspace-files-check-') as temporary:
        result = asyncio.run(check(Path(temporary).resolve()))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
