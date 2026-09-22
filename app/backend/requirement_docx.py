"""Extract reviewable DOCX body text without executing or resolving package content."""
import base64
import binascii
import zlib
from io import BytesIO
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET


def preview_docx(encoded: str) -> dict:
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > 400000:
            raise ValueError("Choose a DOCX file smaller than 400 KB.")
        with ZipFile(BytesIO(raw)) as package:
            entries = package.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > 1000 or len(names) != len(set(names)):
                raise ValueError("The Word package contains too many or duplicate entries.")
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                raise ValueError("Choose a valid DOCX document; older DOC files are not supported.")
            if any(entry.flag_bits & 1 for entry in entries):
                raise ValueError("Encrypted documents are not supported. Export an unencrypted copy.")
            entry = package.getinfo("word/document.xml")
            if entry.file_size > 2000000:
                raise ValueError("The document body is too large. Split the source into smaller documents.")
            xml = package.read(entry).decode("utf-8-sig")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise ValueError("Document XML declarations are not supported.")
        root = ET.fromstring(xml)
        namespace = root.tag.removesuffix("}document").removeprefix("{")
        if namespace not in {"http://schemas.openxmlformats.org/wordprocessingml/2006/main", "http://purl.oclc.org/ooxml/wordprocessingml/main"}:
            raise ValueError("The Word document uses an unsupported structure.")
        tag = lambda name: f"{{{namespace}}}{name}"
        body = root.find(tag("body"))
        if body is None:
            raise ValueError("No document body was found.")
        count = 0
        stack = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            count += 1
            if depth > 40 or count > 50000:
                raise ValueError("The document structure is too complex. Export a simpler copy.")
            stack.extend((child, depth + 1) for child in node)

        skipped = {tag(name) for name in ("del", "moveFrom", "drawing", "object", "pict")}

        def paragraph(node):
            parts = []
            pending = [node]
            while pending:
                current = pending.pop()
                if current.tag in skipped:
                    continue
                if current.tag == tag("t"):
                    parts.append(current.text or "")
                elif current.tag in {tag("br"), tag("cr")}:
                    parts.append("\n")
                elif current.tag == tag("tab"):
                    parts.append("\t")
                pending.extend(reversed(list(current)))
            return "".join(parts).strip()

        def blocks(node):
            result = []
            for child in node:
                if child.tag == tag("p"):
                    result.append(paragraph(child))
                elif child.tag == tag("tbl"):
                    for row in child.findall(tag("tr")):
                        result.append(" | ".join(" / ".join(blocks(cell)) for cell in row.findall(tag("tc"))))
                elif child.tag in {tag("sdt"), tag("sdtContent"), tag("ins"), tag("moveTo")}:
                    result.extend(blocks(child))
            return [part for part in result if part.strip()]

        text = "\n\n".join(blocks(body))
        if len(text) < 10:
            raise ValueError("No usable body text was found. Scanned images need text transcription first.")
        if len(text) > 100000 or "\x00" in text:
            raise ValueError("Extracted text exceeds the 100,000-character source limit or contains NUL characters.")
        warnings = ["Review the extracted body and table rows before saving. Images, headers, footers, notes, comments and automatic list numbering are not included."]
        if any(node.tag in {tag("ins"), tag("del"), tag("moveFrom"), tag("moveTo")} for node in root.iter()):
            warnings.append("Tracked changes were found: inserted text is included and deleted text is excluded. Confirm the intended version with the document owner.")
        return {"title": "", "content": text, "warnings": warnings}
    except (binascii.Error, zlib.error, BadZipFile, KeyError, UnicodeError, ET.ParseError, NotImplementedError, RuntimeError) as exc:
        raise ValueError("The DOCX file could not be read. Export a new DOCX or paste the relevant text.") from exc
