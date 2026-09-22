"""Exercise the actual backend COPY manifest without requiring a container daemon."""
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
                destination = runtime / arguments[-1]
                for source_name in arguments[:-1]:
                    source = root / source_name
                    self.assertNotEqual(source.resolve(), root, "Backend must not copy the entire repository")
                    if source.is_dir():
                        shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                    else:
                        destination.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination / source.name)
            self.assertFalse((runtime / "app/frontend-next").exists())
            self.assertFalse((runtime / "tests").exists())
            self.assertFalse((runtime / "deploy").exists())
            environment = {**os.environ, "APP_MODE": "demo", "LOGIN_REQUIRED": "true",
                           "DATABASE_URL": f"sqlite:///{runtime / 'runtime.db'}",
                           "TICKETY_PROCESS_ROLE": "api", "TICKETY_SCHEDULER_ENABLED": "false"}
            environment.pop("PYTHONPATH", None)
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
