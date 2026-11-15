"""Small builders for test inputs in each real export format."""

import io
import os
import zipfile
from datetime import datetime, timezone

from brainplug import demo


def tiny_pdf(text: str, title: str = "My thesis draft", created: str = "D:20250303100000Z") -> bytes:
    import textwrap
    lines = textwrap.wrap(text, 70) or [""]  # like a real page: lines that fit inside the margins
    stream = b"BT /F1 12 Tf 14 TL 72 720 Td " + b" T* ".join(
        b"(" + line.encode("latin-1") + b") Tj" for line in lines) + b" ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Title (" + title.encode("latin-1") + b") /CreationDate (" + created.encode("latin-1") + b") >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def tiny_docx(paragraphs: list[str], title: str = "", created: str = "2025-02-10T09:30:00Z",
              modified: str = "") -> bytes:
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    doc = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    core = ('<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="x" xmlns:dc="y" '
            f'xmlns:dcterms="z" xmlns:xsi="w">{f"<dc:title>{title}</dc:title>" if title else ""}'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
            + (f'<dcterms:modified xsi:type="dcterms:W3CDTF">{modified}</dcterms:modified>' if modified else "")
            + "</cp:coreProperties>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc)
        zf.writestr("docProps/core.xml", core)
    return buf.getvalue()



FILE_DATE = datetime(2026, 3, 17, 9, 0, tzinfo=timezone.utc)


def dated_documents(folder) -> list:
    """Word and PDF files whose own dates are placeholders, impossible or real; all saved on FILE_DATE."""
    files = {
        # what python-docx writes, as AI assistants often do: its template's date, twice
        "ai summary.docx": tiny_docx(["Exam summary for microeconomics", "Formulas and solved exercises."],
                                     created="2013-12-23T23:15:00Z", modified="2013-12-23T23:15:00Z"),
        # the same kind of file, opened and saved again in Word: now its modified date is real
        "edited summary.docx": tiny_docx(["A cheat sheet for the R exam", "Vectors, data frames and plots."],
                                         created="2013-12-23T23:15:00Z", modified="2026-05-18T10:00:00Z"),
        "impossible.docx": tiny_docx(["A note whose metadata says 1601", "It was written much later."],
                                     created="1601-01-01T00:00:00Z"),
        "real.docx": tiny_docx(["An essay written in Word", "Its own date is right."], created="2024-10-02T08:00:00Z"),
        "epoch.pdf": tiny_pdf("A report exported by a tool with a broken clock in its metadata", title="Report",
                              created="D:19700101000000Z"),
    }
    paths = []
    for name, data in files.items():
        path = folder / name
        path.write_bytes(data)
        os.utime(path, (FILE_DATE.timestamp(),) * 2)
        paths.append(path)
    return paths


def notes_folder(root, n: int = 80) -> None:
    """Write synthetic demo items as dated Markdown notes."""
    root.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(demo.generate(n)):
        (root / f"{i:03d} {item.title}.md").write_text(
            f"---\ncreated: {item.created:%Y-%m-%d}\n---\n{item.text}\n", encoding="utf-8")
