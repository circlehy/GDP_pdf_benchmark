from __future__ import annotations

from pathlib import Path

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from pdf_sft.config import DocumentViewOverrideConfig, load_config
from pdf_sft.schemas import (
    DocumentRecord,
    InputProfile,
    LicenseRecord,
    ParsedDocument,
    ParsedPage,
)
from pdf_sft.stages.build_input import DocumentViewBudgetError, build_input_package


def _records(tmp_path: Path) -> tuple[DocumentRecord, ParsedDocument]:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    document = DocumentRecord(
        document_id="sha256:build-input-test",
        candidate_id="candidate_build_input_test",
        source_id="test",
        source_url="https://example.test/source.pdf",
        title="Build input test",
        publisher="Test",
        content_sha256="build-input-test",
        size_bytes=pdf_path.stat().st_size,
        pdf_path=pdf_path,
        license=LicenseRecord(
            status="approved",
            license_id="test-only",
            evidence_url="https://example.test/license",
            review_notes="Synthetic unit-test record.",
        ),
    )
    pages = [
        ParsedPage(
            page_number=number,
            width_points=612,
            height_points=792,
            image_path=tmp_path / f"page_{number:04d}.png",
            extracted_text=f"LiteParse page {number} value {number * 10}",
            extracted_text_chars=25,
            native_text=f"native page {number}",
            native_text_chars=13,
            needs_ocr=False,
            blocks=[],
        )
        for number in (1, 2)
    ]
    parsed = ParsedDocument(
        document_id=document.document_id,
        parser="liteparse",
        parser_version="2.5.0",
        renderer="pymupdf",
        renderer_version="test",
        ocr_enabled=True,
        ocr_language="eng",
        dpi=150,
        page_count=2,
        pages=pages,
    )
    return document, parsed


def test_text_only_package_contains_complete_page_marked_text(tmp_path: Path) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    document, parsed = _records(tmp_path)

    view, package = build_input_package(document, parsed, config, InputProfile.text_only)

    assert view.scope.value == "full_pdf"
    assert view.included_page_numbers == [1, 2]
    assert package.page_image_paths == []
    assert package.page_image_dpi is None
    assert "[Page 1]" in package.document_text
    assert "LiteParse page 2 value 20" in package.document_text
    assert package.token_accounting.fits_context


def test_configured_tokenizer_replaces_character_estimate(tmp_path: Path) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    tokenizer_root = tmp_path / "tokenizer"
    tokenizer_root.mkdir()
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.save(str(tokenizer_root / "tokenizer.json"))
    config.context_budget.text_tokenizer_path = tokenizer_root
    document, parsed = _records(tmp_path)

    _, package = build_input_package(document, parsed, config, InputProfile.text_only)

    assert package.token_accounting.text_tokens_exact
    assert package.token_accounting.image_tokens_exact
    assert package.token_accounting.tokenizer_or_estimator.startswith("hf-fast:tokenizer")


def test_explicit_bounded_view_is_frozen_before_generation(tmp_path: Path) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    document, parsed = _records(tmp_path)
    config.document_view.overrides[document.document_id] = DocumentViewOverrideConfig(
        included_page_ranges=["2"],
        reason="Synthetic test of a semantically reviewed bounded view.",
    )

    view, package = build_input_package(document, parsed, config, InputProfile.text_only)

    assert view.scope.value == "bounded"
    assert view.frozen
    assert package.page_numbers == [2]
    assert "LiteParse page 1" not in package.document_text


def test_package_rejects_unsafe_context_instead_of_tail_truncating(tmp_path: Path) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    document, parsed = _records(tmp_path)
    config.context_budget.model_context_tokens = 100
    config.context_budget.minimum_output_and_safety_reserve_tokens = 50

    with pytest.raises(DocumentViewBudgetError, match="will not silently truncate"):
        build_input_package(document, parsed, config, InputProfile.text_only)
