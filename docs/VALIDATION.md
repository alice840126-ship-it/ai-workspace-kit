# Validation record — 2026-09-29

## Cross-client guidance, publication status, and search quality update

- 118 local unit/integration tests passed on macOS. Added checks cover publication receipt wording, changed local event count, local-only status (no network), recall audit metadata, and partial-match source re-read.
- `ai-workspace status` and MCP health/recall expose the **last successful** GitHub verification receipt, not a live remote freshness claim. The optional `--audit-calls` records `workspace_recall` tool usage without query or result text.
- On a three-document synthetic fixture, `ExampleCo 견적서 교육 횟수` returned the correct quotation as a `partial_terms` candidate; fresh `read` confirmed “교육 3회”. `ExampleCo 교육` ranked the correct quotation before a different customer's education document. A nonsense unique query returned no result. This is a small regression fixture, not an operational relevance benchmark.
- Added copyable client guidance and a smoke-check sequence that requires actual tool calls. No new public-package ChatGPT, Aside, or voice invocation was performed in this update.
- No semantic model or bulk embedding was installed. The measured lexical gap was addressed without model calls; the threshold and evidence needed before adding a local semantic option are in [SEARCH-QUALITY.md](SEARCH-QUALITY.md).
- `git diff --check` and a local `gitleaks dir` scan passed before publication.
- Published commit `5ef73b2` was cloned from GitHub into a new temporary checkout and virtual environment. Editable installation, `pip check`, the synthetic demo, and `ai-workspace status` all passed there. The demo reported zero network/model calls. This does not verify a new user's private GitHub binding or client-specific MCP registration.

This record describes the public distribution, using synthetic data only.

- Fresh project virtual environment; editable package installation and `pip check` passed.
- Independent clean non-editable install in a temporary virtual environment passed doctor/demo from outside the checkout.
- Documented initial binding/sync and second-device clone/bind/restore passed against a real local bare Git remote with only GitHub visibility mocked.
- macOS, Python 3.14.5, MCP SDK 2.2.0.
- 114 unit/integration tests passed, including the inherited engine suite and portable setup regressions.
- `python -m workspace.demo` passed: duplicate checkpoint suppression, Warm promotion, Markdown,
  local search, fresh source read, and missing-source handling.
- In-process MCP protocol tests verify read-only tool exposure and source read behavior.
- Private repository binding rejects public repositories and unexpected origins in mocked GitHub tests.
- Local bare-Git tests exercise receive/merge preservation, divergent history, private-publication scope,
  immutable event conflicts, and generated Markdown protection. These are not a live multi-account test.
- Tests reject a Git-contained state directory, nested state/memory, symlinks, existing user files,
  secret-bearing documents and unapproved roots. Source files remain unchanged during normal reads.
- Local `gitleaks dir` scan passed before publication; full committed-history scan is also required before push.
- The source repository does not contain personal memory, native DBs, credentials, original customer
  documents, or the private deployment's Git history.

## Fresh public-clone reproduction check — 2026-09-29

The published GitHub `main` at `99b69a2` was cloned into a separate temporary directory;
the maintainer's working checkout, private memory, and local service configuration were not used.

- The README's editable install completed in a new virtual environment; `pip check`, `doctor`,
  and `python -m workspace.demo` passed without an API key or model call.
- All 114 tests passed from that public clone.
- A second, non-editable installation ran `doctor` and the demo outside the checkout.
- In fresh private test directories, `init` → example `checkpoint` → `recall` succeeded.
  A copied synthetic quotation was indexed, searched, and freshly read by artifact ID;
  the read content contained the documented VAT-inclusive amount and education count.
- The installed `ai-workspace-mcp` executable was launched as a real stdio subprocess in
  read-only mode. An MCP client saw only the four read-only tools, then successfully called
  `workspace_recall`, `search_local`, and `read_local_artifact`.
- The complete Git history at that revision was scanned with `gitleaks git`; no leak was found.

This verifies the public package's local reproducibility. It does not verify a new user's
private GitHub account, Codex/Aside registration, ChatGPT connector or tunnel, or voice tools.
Those require client-specific setup and an actual call on the user's account.

## Evidence boundaries

The private predecessor had actual ChatGPT text search/read calls for local documents. That establishes
implementation lineage, not a fresh connection test for this public package or another user's account.
This release's client setup remains account-dependent. No new public-package ChatGPT/Aside connection,
voice invocation, reboot service installation or real external-SSD unplug was performed during packaging.
Simulated unavailable-source/volume tests are separate from physically unplugging a disk.

Automated hosted CI is not enabled in this initial publication: the publishing OAuth credential lacks workflow scope. The equivalent workflow is provided at `docs/ci.example.yml` for maintainers to copy to `.github/workflows/ci.yml` with an authorized credential. No hosted CI or Linux success is claimed.
Native Windows, OCR, semantic retrieval, simultaneous-write conflict auto-resolution and automatic
whole-chat capture are not promised. Existing private deployment was not replaced by this package.
