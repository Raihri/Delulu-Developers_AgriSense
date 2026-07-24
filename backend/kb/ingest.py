from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


WHITESPACE = re.compile(r"\s+")
LEGACY_MARKERS = ("Avwg", "K…wl", "cÖhyw³", "g„wËKv", "Drcv`b")


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        if not self._ignored_depth and tag in {"p", "div", "section", "article", "br", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def clean_html(html: str) -> str:
    parser = _ArticleTextParser()
    parser.feed(html)
    lines = [
        WHITESPACE.sub(" ", line).strip()
        for line in "".join(parser.parts).splitlines()
    ]
    return "\n".join(line for line in lines if line)


def looks_like_legacy_bengali(text: str, *, expected_bengali: bool = False) -> bool:
    if any(marker in text for marker in LEGACY_MARKERS):
        return True
    if not expected_bengali:
        return False
    bengali = sum("\u0980" <= char <= "\u09ff" for char in text)
    latin = sum(char.isascii() and char.isalpha() for char in text)
    return len(text) > 200 and bengali < 10 and latin > 100


def extract_pdf_pages(
    path: str | Path, *, expected_language: str = "en"
) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Install the ingestion dependencies: pip install -e '.[ingest]'") from exc
    records: list[dict[str, Any]] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            warning = None
            if not text.strip():
                warning = "image_only_page_requires_ocr"
            elif looks_like_legacy_bengali(
                text, expected_bengali=expected_language == "bn"
            ):
                warning = "legacy_bengali_encoding_detected_use_ocr_or_reviewed_converter"
            records.append(
                {
                    "source_path": str(path),
                    "source_locator": f"PDF page {page_number}",
                    "text": text,
                    "extraction_warning": warning,
                    "curation_status": "needs_human_review",
                }
            )
    return records


def extract_pdf_tables(path: str | Path, page_number: int) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("Install the ingestion dependencies: pip install -e '.[ingest]'") from exc
    with pdfplumber.open(path) as pdf:
        tables = pdf.pages[page_number - 1].extract_tables()
    return [
        {
            "source_path": str(path),
            "source_locator": f"PDF page {page_number}, extracted table {index}",
            "rows": table,
            "curation_status": "needs_human_spot_check",
        }
        for index, table in enumerate(tables, start=1)
    ]


def ocr_pdf_page(path: str | Path, page_number: int, *, language: str = "ben+eng") -> str:
    renderer = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not renderer or not tesseract:
        raise RuntimeError(
            "OCR requires both pdftoppm and tesseract with the requested language data."
        )
    with tempfile.TemporaryDirectory(prefix="agrisense-ocr-") as directory:
        prefix = Path(directory) / "page"
        subprocess.run(
            [
                renderer,
                "-f",
                str(page_number),
                "-singlefile",
                "-png",
                "-r",
                "300",
                str(path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
        result = subprocess.run(
            [tesseract, str(prefix) + ".png", "stdout", "-l", language],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout


def promote_reviewed(record: dict[str, Any], *, human_reviewed: bool) -> dict[str, Any]:
    if not human_reviewed:
        raise ValueError("Human review is required before a normalized record is curated")
    if not record.get("source_locator"):
        raise ValueError("A source locator is required")
    promoted = dict(record)
    promoted["curation_status"] = "human_reviewed"
    return promoted


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect an HTML or PDF source for curation")
    parser.add_argument("path", type=Path)
    parser.add_argument("--kind", choices=["html", "pdf"], required=True)
    parser.add_argument("--page", type=int)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--expected-language", choices=["en", "bn"], default="en")
    args = parser.parse_args()
    if args.kind == "html":
        result: Any = {
            "source_path": str(args.path),
            "text": clean_html(args.path.read_text(encoding="utf-8")),
            "curation_status": "needs_human_review",
        }
    elif args.ocr:
        if not args.page:
            parser.error("--ocr requires --page")
        result = {
            "source_path": str(args.path),
            "source_locator": f"PDF page {args.page}",
            "text": ocr_pdf_page(args.path, args.page),
            "curation_status": "needs_human_review",
        }
    else:
        result = extract_pdf_pages(
            args.path, expected_language=args.expected_language
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
