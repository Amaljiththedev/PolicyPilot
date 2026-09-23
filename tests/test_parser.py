from io import BytesIO
import pytest
from docx import Document as DocxDocument
from pypdf import PdfWriter

from app.api.ingestion.parser import (
    extract_text,
    UnsupportedFileType,
    EmptyDocument,
    CorruptDocument,
)


def create_sample_docx_bytes() -> bytes:
    """Helper to generate a valid .docx file in bytes with paragraphs and table."""
    doc = DocxDocument()
    doc.add_paragraph("Policy Pilot Document Parsing Test - Section 1: Overview.")
    doc.add_paragraph("This paragraph contains detailed organizational compliance guidelines for remote workers.")
    
    # Add a sample table
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Requirement ID"
    table.cell(0, 1).text = "Compliance Status"
    table.cell(1, 0).text = "REQ-101"
    table.cell(1, 1).text = "Compliant"

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def create_sample_html_bytes() -> bytes:
    """Helper to generate HTML document bytes with main content and noise tags."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Policy Document</title>
        <style>body { font-family: sans-serif; }</style>
        <script>console.log("Ignore script noise");</script>
    </head>
    <body>
        <header><nav>Navigation Link Header</nav></header>
        <main>
            <h1>Employee Attendance Policy</h1>
            <p>All employees are expected to maintain regular attendance and punctuality for work shifts.</p>
            <p>Section 2: Paid time off accrues on a monthly basis for full-time staff members.</p>
        </main>
        <footer>Privacy Policy & Footer Information</footer>
    </body>
    </html>
    """
    return html_content.strip().encode("utf-8")


def create_sample_pdf_bytes() -> bytes:
    """Helper to generate valid PDF file bytes with text content layer."""
    # Build a valid PDF with text stream
    pdf_data = (
        b"%PDF-1.4\n"
        b"1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        b"2 0 obj <</Type /Pages /Count 1 /Kids [3 0 R]>> endobj\n"
        b"3 0 obj <</Type /Page /Parent 2 0 R /Resources <</Font <</F1 4 0 R>>>> /MediaBox [0 0 612 792] /Contents 5 0 R>> endobj\n"
        b"4 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        b"5 0 obj <</Length 160>>\n"
        b"stream\n"
        b"BT /F1 12 Tf 72 712 Td (PolicyPilot PDF Ingestion Test - Section 1: Data Retention Guidelines for Enterprise Software) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000244 00000 n \n0000000315 00000 n \n"
        b"trailer <</Size 6 /Root 1 0 R>>\nstartxref\n490\n%%EOF"
    )
    return pdf_data


def test_extract_text_txt():
    content = b"PolicyPilot Text Document\n" + b"This is a plain text policy document containing usable characters. " * 3
    extracted = extract_text(content, content_type="text/plain", filename="policy.txt")

    assert isinstance(extracted, str)
    assert "PolicyPilot Text Document" in extracted
    assert len(extracted) >= 50


def test_extract_text_docx():
    docx_bytes = create_sample_docx_bytes()
    extracted = extract_text(
        docx_bytes,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="compliance.docx"
    )

    assert isinstance(extracted, str)
    assert "Policy Pilot Document Parsing Test" in extracted
    assert "remote workers" in extracted
    assert "Requirement ID | Compliance Status" in extracted or "REQ-101" in extracted


def test_extract_text_html():
    html_bytes = create_sample_html_bytes()
    extracted = extract_text(html_bytes, content_type="text/html", filename="policy.html")

    assert isinstance(extracted, str)
    assert "Employee Attendance Policy" in extracted
    assert "Paid time off accrues" in extracted
    # Noise tags like <script>, <style>, <nav>, <header>, <footer> must be stripped
    assert "console.log" not in extracted
    assert "font-family" not in extracted
    assert "Navigation Link Header" not in extracted
    assert "Privacy Policy & Footer Information" not in extracted


def test_extract_text_pdf():
    pdf_bytes = create_sample_pdf_bytes()
    extracted = extract_text(pdf_bytes, content_type="application/pdf", filename="policy.pdf")

    assert isinstance(extracted, str)
    assert "Data Retention Guidelines" in extracted


def test_extract_text_unsupported_file_type():
    with pytest.raises(UnsupportedFileType):
        extract_text(b"some content data", content_type="audio/mp3", filename="song.mp3")


def test_extract_text_empty_document():
    with pytest.raises(EmptyDocument):
        extract_text(b"", content_type="text/plain", filename="empty.txt")

    # Under MIN_USABLE_CHARS (50 chars)
    short_content = b"Short text"
    with pytest.raises(EmptyDocument):
        extract_text(short_content, content_type="text/plain", filename="short.txt")


def test_extract_text_corrupt_docx():
    corrupt_bytes = b"This is not a valid zip docx structure"
    with pytest.raises(CorruptDocument):
        extract_text(
            corrupt_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="corrupt.docx"
        )
