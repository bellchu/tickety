import base64
from io import BytesIO
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from app.backend.requirement_docx import preview_docx

NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def document(body, prefix=''):
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as package:
        package.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        package.writestr('word/document.xml', f'{prefix}<w:document xmlns:w="{NS}"><w:body>{body}</w:body></w:document>')
    return base64.b64encode(output.getvalue()).decode()


class RequirementDocxTests(unittest.TestCase):
    def test_preserves_body_order_unicode_table_cells_and_visible_hyperlink_text(self):
        result = preview_docx(document('<w:p><w:r><w:t>供应商 intake</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Receipt</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>30 seconds</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:hyperlink><w:r><w:t>Business policy</w:t></w:r></w:hyperlink></w:p>'))
        self.assertEqual(result['content'], '供应商 intake\n\nReceipt | 30 seconds\n\nBusiness policy')
        self.assertTrue(result['warnings'])

    def test_tracked_changes_and_drawings_are_not_silently_mixed(self):
        result = preview_docx(document('<w:p><w:r><w:t>Confirm within </w:t></w:r><w:del><w:r><w:delText>60 seconds</w:delText></w:r></w:del><w:ins><w:r><w:t>30 seconds.</w:t></w:r></w:ins><w:r><w:drawing><w:t>Image label</w:t></w:drawing></w:r></w:p>'))
        self.assertEqual(result['content'], 'Confirm within 30 seconds.')
        self.assertTrue(any('Tracked changes' in warning for warning in result['warnings']))

    def test_rejects_entities_empty_documents_and_unbounded_expansion(self):
        examples = [document('', '<!DOCTYPE document [<!ENTITY a "value">]>'), document('<w:p/>'), document('<w:p><w:r><w:t>' + 'x' * 100001 + '</w:t></w:r></w:p>'), document('<w:p><w:r><w:t>' + 'x' * 2000001 + '</w:t></w:r></w:p>')]
        for example in examples:
            with self.assertRaises(ValueError):
                preview_docx(example)

    def test_depth_and_corrupt_input_are_bounded(self):
        with self.assertRaisesRegex(ValueError, 'complex'):
            preview_docx(document('<w:sdt>' * 42 + '<w:p><w:r><w:t>Business requirement</w:t></w:r></w:p>' + '</w:sdt>' * 42))
        for value in ['invalid!', base64.b64encode(b'Not an office document').decode()]:
            with self.assertRaises(ValueError):
                preview_docx(value)

    def test_content_controls_and_paragraph_breaks(self):
        result = preview_docx(document('<w:sdt><w:sdtContent><w:p><w:r><w:t>First condition</w:t><w:br/><w:t>Second condition</w:t></w:r></w:p></w:sdtContent></w:sdt>'))
        self.assertEqual(result['content'], 'First condition\nSecond condition')
