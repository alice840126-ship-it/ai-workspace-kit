# AI Workspace Kit

Continue work across Codex, ChatGPT and Aside using concise, GitHub-backed work memory.
Keep large source documents on your own machine and retrieve them through a read-only local MCP bridge.

**Technical preview:** macOS verified, Linux CI template included but not executed, native Windows unsupported. This is an independent
project, not an official OpenAI, GitHub or Aside product. Voice tool invocation is unverified.

## Quick start

Python 3.11+ and Git are required. No API key or model calls are required for the synthetic demo.

```bash
git clone https://github.com/alice840126-ship-it/ai-workspace-kit.git
cd ai-workspace-kit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
ai-workspace doctor
python -m workspace.demo
ai-workspace init
```

The demo checks checkpoint deduplication, memory promotion, artifact search, fresh source reading and
missing-source handling. It uses temporary synthetic files and cleans them up afterward.

## Three separate places

1. Public code repository: this project, tests and examples.
2. Your private GitHub repository: refined context, status, decisions, tasks and links.
3. Local private state: SQLite indexes, checkpoints, approved roots and machine-specific bindings.

Default memory folder: `~/ai-workspace-memory`. State: `~/.local/share/ai-workspace-kit`.
Override with `--memory` and `--state` before the subcommand. Never place state in a Git checkout.

Agents submit structured checkpoints using `examples/checkpoint.json`; use a current timezone-aware
stamp. This does not scrape every chat or automatically capture conversations in every client.
`ai-workspace tick` promotes eligible summaries, updates Markdown, incrementally indexes approved
documents and syncs a bound private repository without model calls. No scheduler is installed automatically.

## Tools

- `workspace_recall`: recent/refined context.
- `workspace_checkpoint`: validated summaries, omitted with `--read-only`.
- `search_local`: candidates in explicitly approved folders.
- `read_local_artifact`: fresh bounded source extraction by returned ID.
- `workspace_health`: scope and availability.

Register `.venv/bin/ai-workspace-mcp --state /absolute/private-state --read-only` with a local stdio client.
ChatGPT requires a separately configured authenticated tunnel or a GitHub connector for refined memory only.
A healthy tunnel is not proof of a successful ChatGPT tool call. Your source machine must be online.

Markdown, TXT, JSON/JSONL, PDF and DOCX are supported. PDF needs Poppler's `pdftotext`; scanned PDFs
need separate OCR. Secrets/dotfiles/packages/symlinks are excluded, but filters are not perfect.
Do not register folders containing data you must not share with the connected client.

See [full Korean guide](../README.md), [operations](../OPERATIONS.md),
[client setup](CLIENTS.md), [security](../SECURITY.md), and [contributing](../CONTRIBUTING.md).
MIT licensed. Stars, synthetic bug reports and documentation improvements are welcome.
