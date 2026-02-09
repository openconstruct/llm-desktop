import csv
from pathlib import Path

from docx import Document
from pypdf import PdfReader


def read_text_file(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise RuntimeError(f"Unable to read file: {exc}") from exc


def read_pdf_file(path: str | Path) -> str:
    try:
        reader = PdfReader(str(path))
        pages: list[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(f"\n--- Page {idx} ---\n{text}")
        return "\n".join(pages).strip()
    except Exception as exc:
        raise RuntimeError(f"PDF Error: {exc}") from exc


def read_docx_file(path: str | Path) -> str:
    try:
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception as exc:
        raise RuntimeError(f"DOCX Error: {exc}") from exc


def read_csv_file(path: str | Path) -> str:
    try:
        with open(path, newline="", encoding="utf-8", errors="ignore") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
        if not rows:
            return ""
        header = rows[0]
        body = rows[1:]
        max_rows = 1000
        preview_rows = body[:max_rows]
        lines: list[str] = []
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in preview_rows:
            padded = row + [""] * (len(header) - len(row))
            safe = [cell.replace("|", "\\|") for cell in padded]
            lines.append("| " + " | ".join(safe) + " |")
        if len(body) > max_rows:
            lines.append(f"\n*Note: Showing first {max_rows} of {len(body)} rows*")
        return "\n".join(lines)
    except Exception as exc:
        raise RuntimeError(f"CSV Error: {exc}") from exc

