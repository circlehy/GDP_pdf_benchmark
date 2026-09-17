from __future__ import annotations

from pathlib import Path

import pymupdf

from pdf_sft.config import load_config
from pdf_sft.schemas import DocumentRecord, LicenseRecord
from pdf_sft.stages.parse import parse_document


def test_parse_document_renders_page_and_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Smoke test technical value: 42")
        pdf.save(pdf_path)

    config = load_config(Path("configs/runs/smoke_test.yaml"))
    config.paths.parsed = tmp_path / "parsed"
    config.security.forbidden_input_roots = [tmp_path / "benchmarks"]
    record = DocumentRecord(
        document_id="sha256:parse-test",
        candidate_id="candidate_parse_test",
        source_id="test",
        source_url="https://example.test/sample.pdf",
        title="Parser smoke test",
        publisher="Test",
        content_sha256="parse-test",
        size_bytes=pdf_path.stat().st_size,
        pdf_path=pdf_path,
        license=LicenseRecord(
            status="approved",
            license_id="test-only",
            evidence_url="https://example.test/license",
            review_notes="Synthetic unit-test PDF created locally.",
        ),
    )

    parsed = parse_document(record, config)

    assert parsed.page_count == 1
    assert "technical value: 42" in parsed.pages[0].native_text
    assert parsed.pages[0].image_path.exists()
    assert (tmp_path / "parsed" / "parse-test" / "document.json").exists()
