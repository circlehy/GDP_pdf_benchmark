#!/usr/bin/env python3
# ruff: noqa: E402, I001
"""Run LiteParse 2.5.0's pre-OCR complexity router on GDP.pdf."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/tmp/liteparse_deps")
from liteparse import LiteParse


ROWS_PATH = Path("/tmp/gdp_rows.json")
PDF_ROOT = Path("/tmp/gdp_pdfs")
OUTPUT_PATH = Path("/tmp/gdp_liteparse_complexity.json")


def inspect_entry(entry: dict) -> dict:
    row = entry["row"]
    parser = LiteParse(ocr_enabled=False, quiet=True)
    pages = parser.is_complex(PDF_ROOT / row["pdf_path"])
    return {
        "row_idx": entry["row_idx"],
        "domain": row["domain"],
        "pdf_path": row["pdf_path"],
        "page_count": len(pages),
        "ocr_page_count": sum(page.needs_ocr for page in pages),
        "complex_pages": [
            {
                "page": page.page_number,
                "text_length": page.text_length,
                "text_coverage": page.text_coverage,
                "image_coverage": page.image_coverage,
                "reasons": [str(reason) for reason in page.reasons],
            }
            for page in pages
            if page.needs_ocr
        ],
    }


def main() -> None:
    entries = json.loads(ROWS_PATH.read_text())["rows"]
    records = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(inspect_entry, entry) for entry in entries]
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            print(
                f"{record['row_idx']:03d}\t{record['ocr_page_count']:04d}/"
                f"{record['page_count']:04d}",
                flush=True,
            )
    records.sort(key=lambda record: record["row_idx"])
    OUTPUT_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
