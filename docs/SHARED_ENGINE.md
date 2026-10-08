# Shared local-files engine

File, document and opt-in program tools come from `chatgpt-local-files`, pinned
in `requirements-local-files.txt`. This adapter maintains memory and indexed
search. There is one filesystem engine, not independently modified copies.

Install the pinned dependency into this project's owned environment:
`<owned-python> -m pip install -r requirements-local-files.txt`.
Start `workspace.bridge --read-only --filesystem` for 30 tools (4 existing
memory/search tools and 26 local tools). Add `--execution` for 31 tools.
Checkpoint read-only mode does not disable explicitly enabled filesystem writes.
Without `--filesystem`, existing memory/search behavior is unchanged.

The unrestricted path scope means OS-permitted regular files and directories,
including mounted SSDs. No privilege elevation or permission bypass is provided.
Execution is optional, not a sandbox or automatically recoverable transaction.
Read actual outputs after a program exits. Large writes support staged resume,
version checks and recoverable commit. Word, Excel, PDF and image tools have
bounded parser limits; OCR, GUI operation and Excel recalculation are not included.

Update the dependency pin only after canonical engine and adapter regression
checks. To roll back, restore the previous pin and reinstall it; retain journals.
