import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from mawkbox.__main__ import launch_gui, main
from mawkbox.signal import unpack


class Startup(unittest.TestCase):
    def test_homebrew_hint_matches_running_python(self):
        for module in ('tkinter', '_tkinter'):
            with self.subTest(module=module):
                missing = ModuleNotFoundError(name=module)
                with patch('mawkbox.__main__.import_module', side_effect=missing), \
                     patch('mawkbox.__main__.sys.platform', 'darwin'), \
                     patch('mawkbox.__main__.sys.version_info', (3, 14)):
                    with self.assertRaisesRegex(RuntimeError, 'brew install python-tk@3.14'):
                        launch_gui()

    def test_cli_shows_actionable_error_without_traceback(self):
        error = io.StringIO()
        with patch('mawkbox.__main__.import_module', side_effect=ModuleNotFoundError(name='_tkinter')), \
             patch('mawkbox.__main__.sys.platform', 'darwin'), \
             patch('mawkbox.__main__.sys.version_info', (3, 14)), \
             patch('sys.argv', ['mawkbox']), redirect_stderr(error):
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 1)
        self.assertIn('brew install python-tk@3.14', error.getvalue())
        self.assertNotIn('Traceback', error.getvalue())

    def test_unrelated_import_failure_is_preserved(self):
        missing = ModuleNotFoundError(name='unrelated_module')
        with patch('mawkbox.__main__.import_module', side_effect=missing):
            with self.assertRaises(ModuleNotFoundError) as result:
                launch_gui()
        self.assertIs(result.exception, missing)

    def test_cli_encoding_does_not_import_gui(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'message'
            with patch('mawkbox.__main__.import_module') as importer, \
                 patch('sys.argv', ['mawkbox', 'encode', 'Hello', '--plain', '-o', str(base)]), \
                 redirect_stdout(io.StringIO()):
                main()
            importer.assert_not_called()
            self.assertEqual(unpack(base.with_suffix('.mawkbox').read_bytes()), 'Hello')
            self.assertTrue(base.with_suffix('.wav').exists())
