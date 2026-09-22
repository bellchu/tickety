import base64
from email.message import EmailMessage
import unittest

from app.backend.requirement_email import preview_email


def preview(message):
    return preview_email(base64.b64encode(message.as_bytes()).decode())


class RequirementEmailTests(unittest.TestCase):
    def test_decodes_mime_headers_and_body_without_duplicate_html_or_attachment(self):
        email = EmailMessage()
        email['Subject'] = '供应商流程 review'
        email['From'] = 'Operations <ops@example.test>'
        email['To'] = 'Reviewer <reviewer@example.test>'
        email.set_content('供应商 must receive confirmation within 30 seconds.', cte='base64')
        email.add_alternative('<p>Duplicate alternative should not be added.</p>', subtype='html')
        email.add_attachment(b'PRIVATE ATTACHMENT CONTENT', maintype='text', subtype='plain', filename='notes.txt')
        result = preview(email)
        self.assertEqual(result['title'], '供应商流程 review')
        self.assertIn('供应商 must receive confirmation', result['content'])
        self.assertIn('From: Operations', result['content'])
        self.assertNotIn('Duplicate alternative', result['content'])
        self.assertNotIn('PRIVATE ATTACHMENT', result['content'])
        self.assertTrue(any('Attachments' in warning for warning in result['warnings']))

    def test_html_is_text_only_and_does_not_include_scripts_or_remote_resources(self):
        email = EmailMessage()
        email.set_content('<html><head><style>hidden css</style></head><body><p>Confirm receipt &amp; retain reference.</p><script>hidden script</script><img src="https://example.test/tracker"><p>Review every exception.</p></body></html>', subtype='html')
        result = preview(email)
        self.assertIn('Confirm receipt & retain reference.\nReview every exception.', result['content'])
        self.assertNotIn('hidden', result['content'])
        self.assertNotIn('https://', result['content'])
        self.assertTrue(result['warnings'])

    def test_quoted_printable_charset_and_attached_messages(self):
        email = EmailMessage()
        email.set_content('Réviser chaque demande sous trente secondes.', charset='iso-8859-1', cte='quoted-printable')
        attached = EmailMessage()
        attached.set_content('An attached message is separate evidence.')
        email.add_attachment(attached)
        result = preview(email)
        self.assertIn('Réviser chaque demande', result['content'])
        self.assertNotIn('separate evidence', result['content'])

    def test_rejects_size_encoding_and_empty_body_without_partial_evidence(self):
        for value in ['not-base64!', base64.b64encode(b'x' * 400001).decode(), base64.b64encode(b'Subject: No body\r\n\r\n').decode()]:
            with self.assertRaises(ValueError):
                preview_email(value)
        email = EmailMessage()
        email.set_content('x' * 100001)
        with self.assertRaises(ValueError):
            preview(email)

    def test_nesting_is_bounded(self):
        email = EmailMessage()
        email.set_content('This is a readable body.')
        for _ in range(14):
            parent = EmailMessage()
            parent.make_mixed()
            parent.attach(email)
            email = parent
        with self.assertRaisesRegex(ValueError, 'complex'):
            preview(email)
