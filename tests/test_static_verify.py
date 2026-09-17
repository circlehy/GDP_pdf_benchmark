from __future__ import annotations

from pathlib import Path

from pdf_sft.config import load_config
from pdf_sft.schemas import Claim, GeneratedCandidate, ParsedDocument, ParsedPage
from pdf_sft.stages.verify import _blind_prompt, verify_candidate_static


def parsed_document(page_count: int) -> ParsedDocument:
    pages = [
        ParsedPage(
            page_number=index,
            width_points=612,
            height_points=792,
            image_path=Path(f"/tmp/page_{index}.png"),
            native_text="test",
            native_text_chars=4,
            needs_ocr=False,
            blocks=[],
        )
        for index in range(1, page_count + 1)
    ]
    return ParsedDocument(
        document_id="sha256:test",
        parser="test",
        parser_version="1",
        dpi=144,
        page_count=page_count,
        pages=pages,
    )


def test_static_verification_passes_but_does_not_enable_difficulty(
    valid_candidate: GeneratedCandidate,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    result = verify_candidate_static(valid_candidate, parsed_document(2), config)
    assert result.static_checks_passed
    assert not result.eligible_for_difficulty
    assert result.independent_verifier_status == "not_run"


def test_out_of_range_evidence_page_fails(valid_candidate: GeneratedCandidate) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    result = verify_candidate_static(valid_candidate, parsed_document(1), config)
    assert not result.static_checks_passed
    assert any(
        check.check == "evidence_pages_in_range" and not check.passed for check in result.checks
    )


def test_claim_dependencies_may_resolve_through_other_claims(
    valid_candidate: GeneratedCandidate,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    valid_candidate.task.claims.append(
        Claim(claim_id="c2", text="Derived conclusion", supported_by=["c1"])
    )
    result = verify_candidate_static(valid_candidate, parsed_document(2), config)
    check = next(item for item in result.checks if item.check == "claims_resolve_to_evidence")
    assert check.passed


def test_ungrounded_claim_cycle_fails(valid_candidate: GeneratedCandidate) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    valid_candidate.task.claims = [
        Claim(claim_id="c1", text="First", supported_by=["c2"]),
        Claim(claim_id="c2", text="Second", supported_by=["c1"]),
    ]
    result = verify_candidate_static(valid_candidate, parsed_document(2), config)
    check = next(item for item in result.checks if item.check == "claims_resolve_to_evidence")
    assert not check.passed
    assert "cycle" in (check.details or "")


def test_blind_reconstruction_prompt_does_not_leak_gold(
    valid_candidate: GeneratedCandidate,
) -> None:
    template = "Pages: {page_numbers}\nTask: {task_json}"
    prompt = _blind_prompt(template, valid_candidate, [1, 2])
    assert valid_candidate.task.prompt in prompt
    assert valid_candidate.task.gold_answer not in prompt
    assert "claims" not in prompt
