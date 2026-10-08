"""Compatibility import for the single canonical local-files engine.

No filesystem implementation is maintained in this adapter. Module identity is
preserved for existing callers and monkeypatch-based race regression tests.
"""
import sys
from local_files import filesystem as _implementation
sys.modules[__name__] = _implementation
