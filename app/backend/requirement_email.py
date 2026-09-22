"""Bounded MIME-to-text preview; never follows links or reads attachments."""
import base64
import binascii
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser


class _ReadableHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head", "template"}:
            self.hidden += 1
        if not self.hidden and tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head", "template"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"td", "th"}:
            self.parts.append("\t")
        if not self.hidden and tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def preview_email(encoded: str) -> dict:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("The email could not be decoded. Choose an EML file.") from exc
    if not raw or len(raw) > 400000:
        raise ValueError("Choose an EML file smaller than 400 KB.")
    warnings = []
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        parts = 0

        def body(part, depth=0):
            nonlocal parts
            parts += 1
            if depth > 12 or parts > 100:
                raise ValueError("The email structure is too complex. Paste its relevant text instead.")
            if part.get_content_disposition() == "attachment" or part.get_filename() or part.get_content_type() == "message/rfc822":
                warnings.append("Attachments and attached messages were excluded. Add their relevant contents separately.")
                return "", ""
            if part.is_multipart():
                children = list(part.iter_parts())
                if part.get_content_subtype() == "related":
                    root = part.get_param("start")
                    children = [next((child for child in children if root and child.get("Content-ID") == root), children[0])] if children else []
                values = [body(child, depth + 1) for child in children]
                if part.get_content_subtype() == "alternative":
                    return next((value for value in values if value[0] and value[1] == "plain"), next((value for value in values if value[0]), ("", "")))
                return "\n\n".join(value[0] for value in values if value[0]), "html" if any(value[1] == "html" for value in values) else "plain"
            if part.get_content_type() not in {"text/plain", "text/html"}:
                return "", ""
            text = part.get_content(errors="strict")
            if part.get_content_type() == "text/html":
                parser = _ReadableHTML()
                parser.feed(text)
                parser.close()
                text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
                return text.strip(), "html"
            return text.strip(), "plain"

        text, kind = body(message)
        if not text or len(text) < 10:
            raise ValueError("No readable email body was found. Paste the relevant message text instead.")
        if kind == "html" or message.get_content_type() == "text/html":
            warnings.append("HTML formatting was converted to text. Check lists, tables and quoted replies before saving.")
        headers = []
        for key in ("Subject", "From", "To", "Cc", "Date"):
            value = str(message.get(key, "")).strip()
            if value:
                headers.append(f"{key}: {value}")
        content = "\n".join(headers) + "\n\n" + text
        if len(content) > 100000 or "\x00" in content:
            raise ValueError("The extracted email exceeds the 100,000-character source limit or contains NUL characters.")
        if any(part.defects for part in message.walk()):
            warnings.append("The email has formatting defects. Check the extracted text against the original before saving.")
        return {"title": str(message.get("Subject", "Imported email"))[:200], "content": content.strip(), "warnings": list(dict.fromkeys(warnings))}
    except (UnicodeError, LookupError, RecursionError) as exc:
        raise ValueError("The email encoding or structure could not be read. Paste its relevant text instead.") from exc
