"""Exercise the actual backend COPY manifest without requiring a container daemon."""
import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


class BackendRuntimeLayoutTests(unittest.TestCase):
    def test_backend_copy_manifest_supports_api_worker_migrations_and_pdf_preview(self):
        root = Path(__file__).resolve().parents[1]
        backend_stage = (root / "Dockerfile").read_text().split("FROM node:", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            for line in backend_stage.splitlines():
                if not line.startswith("COPY "):
                    continue
                arguments = [part for part in shlex.split(line)[1:] if not part.startswith("--")]
                destination_name = arguments[-1]
                destination = runtime / destination_name
                for source_name in arguments[:-1]:
                    source = root / source_name
                    self.assertNotEqual(source.resolve(), root, "Backend must not copy the entire repository")
                    if source.is_dir():
                        shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                    else:
                        # Docker copies a file to an explicitly named target
                        # as that target, not into a directory bearing its
                        # filename.  The latter masked direct script execution.
                        target = (
                            destination / source.name
                            if destination_name.endswith("/")
                            else destination
                        )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
            self.assertFalse((runtime / "app/frontend-next").exists())
            self.assertFalse((runtime / "tests").exists())
            self.assertFalse((runtime / "deploy").exists())
            environment = {**os.environ, "APP_MODE": "demo", "LOGIN_REQUIRED": "true",
                           "DATABASE_URL": f"sqlite:///{runtime / 'runtime.db'}",
                           "TICKETY_PROCESS_ROLE": "api", "TICKETY_SCHEDULER_ENABLED": "false"}
            environment.pop("PYTHONPATH", None)
            # The image executes maintenance scripts by filename.  Python then
            # starts at /app/scripts rather than /app, so the image-level path
            # contract must make the copied application package importable.
            self.assertIn("ENV PYTHONPATH=/app", backend_stage)
            script_environment = {
                **environment,
                "DATABASE_URL": f"sqlite:///{runtime / 'preflight.db'}",
                "PYTHONPATH": str(runtime),
                "TICKETY_SETTINGS_ENCRYPTION_ACTIVE_KID": "test",
                "TICKETY_SETTINGS_ENCRYPTION_KEYS_JSON": json.dumps(
                    {"test": base64.b64encode(b"x" * 32).decode("ascii")}
                ),
            }
            preflight = subprocess.run(
                [sys.executable, "scripts/verify-settings-secret-encryption.py"],
                cwd=runtime,
                env=script_environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
            self.assertIn("settings encryption preflight passed", preflight.stdout)
            reencrypt_help = subprocess.run(
                [sys.executable, "scripts/reencrypt-settings-secrets.py", "--help"],
                cwd=runtime,
                env=script_environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                reencrypt_help.returncode,
                0,
                reencrypt_help.stdout + reencrypt_help.stderr,
            )
            script = '''
import os, sys
sys.path.insert(0, os.getcwd())
from alembic import command
from alembic.config import Config
command.upgrade(Config("alembic.ini"), "head")
from app.backend.database import verify_database_schema
verify_database_schema()
from app.backend import main, worker
from fastapi.testclient import TestClient
client = TestClient(main.app)
response = client.get("/version")
assert response.status_code == 200, response.text
assert worker.run() == 2  # API role exits before starting scheduled jobs.
# The isolated PDF worker locates its script relative to the packaged module.
from app.backend.requirement_pdf import preview_pdf
import base64, io
from pypdf import PdfWriter
pdf = PdfWriter()
pdf.add_blank_page(width=100, height=100)
stream = io.BytesIO()
pdf.write(stream)
try:
    preview_pdf(base64.b64encode(stream.getvalue()).decode())
except ValueError as error:
    assert "text" in str(error).lower(), str(error)
else:
    raise AssertionError("Blank PDF should require text/OCR")
print("Runtime manifest verified")
'''
            result = subprocess.run([sys.executable, "-I", "-c", script], cwd=runtime, env=environment,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Runtime manifest verified", result.stdout)
