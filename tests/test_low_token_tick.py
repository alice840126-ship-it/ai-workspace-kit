"""The public module and installed entrypoint must expose the same safe CLI."""
import unittest
from workspace import __main__, kit
class EntrypointTests(unittest.TestCase):
    def test_module_uses_portable_entrypoint(self):
        self.assertIs(__main__.main, kit.main)
