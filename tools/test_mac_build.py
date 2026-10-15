"""Offline failure contracts for the desktop-to-Mac artifact handoff."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('build_on_mac', Path(__file__).with_name('build_on_mac.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MacBuildTests(unittest.TestCase):
    def test_developer_build_commands_are_not_editor_utilities(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import strike_remap
        names = {item['name'] for item in strike_remap.list_tools()}
        self.assertNotIn('build_on_mac.py', names)
        self.assertNotIn('build_macos_companion.py', names)

    def test_shell_stdin_is_binary_to_preserve_unix_newlines(self):
        with patch.object(module.subprocess, 'run') as run:
            module.ssh_script('mac-mini', ['a'*24], module.PREPARE, 45)
        options = run.call_args.kwargs
        self.assertIsInstance(options['input'], bytes)
        self.assertNotIn(b'\r', options['input'])
        self.assertNotIn('text', options)

    def test_host_is_not_a_shell_or_ssh_option(self):
        for value in ['mac-mini', '192.168.1.192', 'mac.example.net']:
            self.assertEqual(module.valid_host(value), value)
        for value in ['-oProxyCommand=bad', 'mac;echo bad', 'mac\nwhoami', 'user@host', '', 'a/b', 'a b']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.valid_host(value)

    def test_receipt_binds_bytes_revision_and_fixed_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            data = b'synthetic artifact'
            (folder / module.ARTIFACT).write_bytes(data)
            good = {'revision': 'a'*40, 'artifact': module.ARTIFACT, 'contracts': 'passed',
                    'architecture': 'arm64', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            path = folder / 'build-receipt.json'
            path.write_text(json.dumps(good))
            self.assertEqual(module.verify_receipt(folder, 'a'*40), good)
            for field, value in [('revision', 'b'*40), ('artifact', '../elsewhere'), ('contracts', 'failed'),
                                 ('architecture', 'x86_64'), ('bytes', 0), ('sha256', '0'*64)]:
                path.write_text(json.dumps({**good, field: value}))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    module.verify_receipt(folder, 'a'*40)
            path.write_text(json.dumps(good))
            (folder / module.ARTIFACT).write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                module.verify_receipt(folder, 'a'*40)


if __name__ == '__main__':
    unittest.main()
