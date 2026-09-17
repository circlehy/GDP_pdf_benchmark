#!/usr/bin/env python3
# ruff: noqa: E402, I001
"""Parse OCR-critical GDP.pdf samples with the AA LiteParse version."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/tmp/liteparse_deps")
from liteparse import LiteParse


ROWS = json.loads(Path("/tmp/gdp_rows.json").read_text())["rows"]
PDF_ROOT = Path("/tmp/gdp_pdfs")
OUTPUT_ROOT = Path("/tmp/gdp_liteparse_selected")
SELECTED = {6, 28, 39, 49, 54, 60, 68, 80, 88, 93}


def parse_entry(entry: dict) -> tuple[int, str]:
    idx = entry["row_idx"]
    parser = LiteParse(
        ocr_enabled=True,
        ocr_language="eng",
        output_format="text",
        quiet=True,
        num_workers=4,
    )
    result = parser.parse(PDF_ROOT / entry["row"]["pdf_path"])
    return idx, result.text


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    entries = [entry for entry in ROWS if entry["row_idx"] in SELECTED]
    with ProcessPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(parse_entry, entry) for entry in entries]
        for future in as_completed(futures):
            idx, text = future.result()
            (OUTPUT_ROOT / f"{idx:03d}.txt").write_text(text)
            print(f"{idx:03d}\t{len(text):08d}", flush=True)


if __name__ == "__main__":
    main()
