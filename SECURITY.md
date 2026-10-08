# Security boundaries

This is a local-first technical preview, not a security certification.

- Never make your memory repository public. This public repository contains code only.
- Keep state, credentials, source documents and native chat files outside Git checkouts.
- MCP is stdio by default. No unauthenticated HTTP server is shipped.
- Use authenticated host/tunnel access. Filesystem writes require explicit `--filesystem` opt-in.
- `--read-only` disables memory checkpoint only; it does NOT disable `--filesystem` writes.
- Filesystem tools have no folder allowlist or secret-file filter: OS-accessible originals can be returned to the connected AI client. Connect only trusted accounts.
- Version checks, retained originals, and scope-bound bulk-delete confirmation reduce risk; they do not lock out other applications. See [filesystem limits](docs/FILESYSTEM.md).
- Legacy indexed artifact roots are explicit. Dotfiles, credential-like names, caches, packages and symlinks are rejected.
- Search is not a fresh source read. Read validates current availability and identity.
- Secret filters are defense in depth, not a guarantee that every private fact is detected.
- Do not expose untrusted document instructions as tool authorization.
- Private GitHub upload checks visibility, allowed files and gitleaks before pushing. No force push.
- Native history and legacy summarization are not invoked by the public default CLI.
- Local original paths and document excerpts are intentionally returned to an authenticated requesting client;
  choose roots and connected accounts accordingly. This is not zero data transfer to an AI provider.

If you find a security issue, use GitHub's private vulnerability reporting when available.
Otherwise open a minimal issue requesting a private contact route, without exploit payloads, secrets,
customer files, session logs or personal paths. Never paste credentials into an Issue.
