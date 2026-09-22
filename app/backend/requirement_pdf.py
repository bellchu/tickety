"""PDF text preview in a short-lived, resource-limited parser process."""
import base64
import binascii
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil
from threading import BoundedSemaphore

_SLOTS = BoundedSemaphore(2)


def preview_pdf(encoded: str) -> dict:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("The PDF could not be decoded.") from exc
    if not raw.startswith(b"%PDF-") or len(raw) > 400000:
        raise ValueError("Choose a PDF file smaller than 400 KB.")
    if not _SLOTS.acquire(blocking=False):
        raise ValueError("Document previews are busy. Try again shortly.")
    try:
        try:
            output = _run_parser(raw)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("PDF extraction took too long. Split the document or paste the relevant text.") from exc
        try:
            data = json.loads(output)
        except (ValueError, UnicodeError) as exc:
            raise ValueError("The PDF parser returned an unreadable preview.") from exc
        if "error" in data:
            raise ValueError(data["error"])
        return data
    finally:
        _SLOTS.release()


def _run_parser(raw):
    process = subprocess.Popen(
        [sys.executable, "-I", str(Path(__file__).resolve()), "--worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    payload = raw
    try:
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("PDF preview", 10)
            try:
                if psutil.Process(process.pid).memory_info().rss > 256 * 1024 * 1024:
                    raise ValueError("PDF preview exceeded its memory limit. Export a simpler copy.")
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied as exc:
                raise ValueError("The PDF parser's resource usage could not be monitored.") from exc
            try:
                output, _ = process.communicate(input=payload, timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                payload = None
        if process.returncode != 0:
            raise ValueError("The PDF could not be processed within the preview limits. Export a simpler copy or paste the relevant text.")
        return output
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def _extract(raw: bytes) -> dict:
    from io import BytesIO
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(raw), strict=True)
    if reader.is_encrypted:
        return {"error": "Encrypted PDFs are not supported. Export an unencrypted copy."}
    if len(reader.pages) > 50:
        return {"error": "Preview supports up to 50 pages. Split the document into smaller sources."}
    chunks, empty_pages = [], []
    text_length = 0
    for number, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents is not None and len(contents.get_data()) > 2000000:
            return {"error": "A PDF page is too complex for preview. Export a simpler copy."}
        text = (page.extract_text() or "").strip()
        if not text:
            empty_pages.append(number)
            continue
        chunk = f"[Page {number}]\n{text}"
        text_length += len(chunk) + 2
        if text_length > 100000 or "\x00" in text:
            return {"error": "Extracted text exceeds the 100,000-character source limit or contains NUL characters."}
        chunks.append(chunk)
    if not chunks:
        return {"error": "No text was found. This PDF may be scanned; transcribe or OCR it before importing."}
    warnings = ["Check reading order, tables and symbols against the PDF before saving. Images, annotations and attachments are not extracted; OCR is not performed."]
    if empty_pages:
        warnings.append("No text was extracted from pages " + ", ".join(map(str, empty_pages)) + ". They may contain scans or blank content; review them separately.")
    return {"title": "", "content": "\n\n".join(chunks), "warnings": warnings}


def _worker():
    import resource

    # Linux enforces a hard address-space ceiling. macOS does not implement
    # these memory rlimits; the parent monitors RSS and terminates the worker.
    # Both platforms also have a CPU limit and a parent-enforced wall timeout.
    ceiling = 256 * 1024 * 1024
    if sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        data = _extract(sys.stdin.buffer.read(400001))
    except Exception:
        data = {"error": "The PDF text could not be read reliably. Export a new PDF or paste the relevant text."}
    sys.stdout.write(json.dumps(data))


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    _worker()
