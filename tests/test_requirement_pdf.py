import base64
from io import BytesIO
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from app.backend.requirement_pdf import preview_pdf, _SLOTS, _run_parser


def pdf_source(text='Confirm each request within thirty seconds.', blank_page=False, encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 12 Tf 30 700 Td ({text}) Tj ET'.encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    if blank_page:
        writer.add_blank_page(width=600, height=800)
    if encrypted:
        writer.encrypt('test-only-password')
    output = BytesIO()
    writer.write(output)
    return base64.b64encode(output.getvalue()).decode()


class RequirementPdfTests(unittest.TestCase):
    def test_real_isolated_worker_extracts_text_with_page_trace_and_missing_page_warning(self):
        result = preview_pdf(pdf_source(blank_page=True))
        self.assertIn('[Page 1]\nConfirm each request within thirty seconds.', result['content'])
        self.assertTrue(any('pages 2' in warning for warning in result['warnings']))

    def test_encrypted_empty_and_invalid_pdf_are_rejected(self):
        for source in [pdf_source(encrypted=True), pdf_source(text=''), 'not-base64!', base64.b64encode(b'%PDF-not-a-document').decode()]:
            with self.assertRaises(ValueError):
                preview_pdf(source)

    def test_timeout_releases_slot_and_never_returns_partial_text(self):
        with patch('app.backend.requirement_pdf._run_parser', side_effect=subprocess.TimeoutExpired('parser', 10)):
            with self.assertRaisesRegex(ValueError, 'too long'):
                preview_pdf(pdf_source())
        self.assertIn('Confirm each request', preview_pdf(pdf_source())['content'])

    def test_busy_parser_limit_does_not_start_another_worker(self):
        _SLOTS.acquire()
        _SLOTS.acquire()
        try:
            with patch('app.backend.requirement_pdf._run_parser') as run:
                with self.assertRaisesRegex(ValueError, 'busy'):
                    preview_pdf(pdf_source())
                run.assert_not_called()
        finally:
            _SLOTS.release()
            _SLOTS.release()

    def test_page_limit_and_oversized_input(self):
        writer = PdfWriter()
        for _ in range(51):
            writer.add_blank_page(width=600, height=800)
        output = BytesIO()
        writer.write(output)
        with self.assertRaisesRegex(ValueError, '50 pages'):
            preview_pdf(base64.b64encode(output.getvalue()).decode())
        with self.assertRaisesRegex(ValueError, '400 KB'):
            preview_pdf(base64.b64encode(b'%PDF-' + b'x' * 400000).decode())

    def test_resource_supervisor_terminates_and_reaps_worker(self):
        process = MagicMock()
        process.pid = 12345
        process.poll.return_value = None
        with patch('app.backend.requirement_pdf.subprocess.Popen', return_value=process), patch('app.backend.requirement_pdf.psutil.Process') as tracked:
            tracked.return_value.memory_info.return_value.rss = 300 * 1024 * 1024
            with self.assertRaisesRegex(ValueError, 'memory limit'):
                _run_parser(b'%PDF-test')
        process.kill.assert_called_once()
        process.communicate.assert_called_once()

    def test_wall_timeout_terminates_and_reaps_worker(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch('app.backend.requirement_pdf.subprocess.Popen', return_value=process), patch('app.backend.requirement_pdf.time.monotonic', side_effect=[0, 11]):
            with self.assertRaises(subprocess.TimeoutExpired):
                _run_parser(b'%PDF-test')
        process.kill.assert_called_once()
        process.communicate.assert_called_once()
