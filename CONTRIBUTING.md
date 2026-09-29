# Contributing

Please start with a reproducible issue using synthetic data. Include OS, Python version,
installation command, safe error code and expected behavior. Do not upload real memory or documents.

Development:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m workspace.demo
```

Keep changes scoped. Add behavioral regression tests for safety or sync changes. Preserve private-repo
checks, original-read requirements, bounded extraction, idempotency and conflict preservation.
No tests may require paid model calls or write to a user's real runtime. Avoid new mandatory cloud services.
Document platform-specific behavior and do not claim client/voice success from unit tests alone.
Contributions are distributed under the repository MIT license.

## Hosted CI

`docs/ci.example.yml` is a macOS/Linux Python 3.11/3.13 workflow template. With workflow-authorized credentials, copy it to `.github/workflows/ci.yml` and inspect the first Actions run. It is not active in the initial release; local test success is reported separately.
