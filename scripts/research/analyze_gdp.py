#!/usr/bin/env python3
# ruff: noqa: E402, I001
"""Extract auditable text/layout statistics from the 100 GDP.pdf documents."""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/tmp/gdp_deps")
from pypdf import PdfReader


ROWS_PATH = Path("/tmp/gdp_rows.json")
PDF_ROOT = Path("/tmp/gdp_pdfs")
OUTPUT_PATH = Path("/tmp/gdp_extracted.json")


def count_page_images(page) -> int:
    """Count image XObjects without decoding image payloads."""
    try:
        resources = page.get("/Resources") or {}
        xobjects = resources.get("/XObject") or {}
        xobjects = xobjects.get_object()
        return sum(1 for obj in xobjects.values() if obj.get_object().get("/Subtype") == "/Image")
    except Exception:
        return -1


def rubric_criteria(row: dict) -> list[dict]:
    criteria = []
    for index in range(1, 31):
        prefix = f"rubric - {index}."
        criterion = row.get(prefix + "criterion")
        if criterion:
            criteria.append(
                {
                    "index": index,
                    "criterion": criterion,
                    "type": row.get(prefix + "criterion_type"),
                    "failure_mode": row.get(prefix + "criterion_failure_mode"),
                }
            )
    return criteria


def extract_entry(entry: dict) -> dict:
    row = entry["row"]
    pdf_path = PDF_ROOT / row["pdf_path"]
    record = {
        "row_idx": entry["row_idx"],
        "task_id": row["task_id"],
        "domain": row["domain"],
        "pdf_path": row["pdf_path"],
        "prompt": row["prompt"],
        "rubric": rubric_criteria(row),
        "pages": [],
        "error": None,
    }
    try:
        reader = PdfReader(str(pdf_path), strict=False)
        for page_idx, page in enumerate(reader.pages):
            try:
                plain = page.extract_text() or ""
            except Exception:
                plain = ""
            record["pages"].append(
                {
                    "page": page_idx + 1,
                    "plain": plain,
                    "nonspace_chars": len(re.sub(r"\s+", "", plain)),
                    "images": count_page_images(page),
                }
            )
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def main() -> None:
    dataset = json.loads(ROWS_PATH.read_text())
    output = []
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(extract_entry, entry) for entry in dataset["rows"]]
        for future in as_completed(futures):
            record = future.result()
            output.append(record)
            print(
                f"{record['row_idx']:03d}\t{len(record['pages']):04d}\t"
                f"{sum(p['nonspace_chars'] for p in record['pages']):08d}\t"
                f"{record['error'] or 'ok'}",
                flush=True,
            )
    output.sort(key=lambda item: item["row_idx"])
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
