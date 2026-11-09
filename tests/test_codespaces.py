import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class CodespacesTests(unittest.TestCase):
    def test_start_and_resume_keep_password_and_single_server(self):
        spec = importlib.util.spec_from_file_location('codespaces_start', ROOT / '.devcontainer/start.py')
        starter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(starter)
        processes = []
        original_popen = subprocess.Popen

        def track(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as directory:
            starter.ROOT = Path(directory)
            starter.DATA = Path(directory) / 'data' / 'codespaces'
            shutil.copy(ROOT / 'cloud_app.py', starter.ROOT / 'cloud_app.py')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                starter.PORT = sock.getsockname()[1]
            try:
                with patch.object(starter.subprocess, 'Popen', side_effect=track), contextlib.redirect_stdout(io.StringIO()):
                    starter.main()
                    password_file = starter.DATA / 'app-password.txt'
                    first = password_file.read_text()
                    starter.main()
                self.assertEqual(len(processes), 1)
                self.assertTrue(starter.healthy())
                self.assertEqual(first, password_file.read_text())
                self.assertGreaterEqual(len(first), 24)
                self.assertEqual(password_file.stat().st_mode & 0o777, 0o600)
            finally:
                for process in processes:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
