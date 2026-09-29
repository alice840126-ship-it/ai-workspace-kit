# Validation record — 2026-09-29

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

## Evidence boundaries

The private predecessor had actual ChatGPT text search/read calls for local documents. That establishes
implementation lineage, not a fresh connection test for this public package or another user's account.
This release's client setup remains account-dependent. No new public-package ChatGPT/Aside connection,
voice invocation, reboot service installation or real external-SSD unplug was performed during packaging.
Simulated unavailable-source/volume tests are separate from physically unplugging a disk.

Automated hosted CI is not enabled in this initial publication: the publishing OAuth credential lacks workflow scope. The equivalent workflow is provided at `docs/ci.example.yml` for maintainers to copy to `.github/workflows/ci.yml` with an authorized credential. No hosted CI or Linux success is claimed.
Native Windows, OCR, semantic retrieval, simultaneous-write conflict auto-resolution and automatic
whole-chat capture are not promised. Existing private deployment was not replaced by this package.
