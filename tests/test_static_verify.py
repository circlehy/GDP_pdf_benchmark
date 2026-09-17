from __future__ import annotations

from pathlib import Path

import pymupdf

from pdf_sft.config import load_config
from pdf_sft.schemas import (
    BoundingBox,
    Claim,
    GeneratedCandidate,
    IndependentReconstruction,
    InputProfile,
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
)
from pdf_sft.stages.verify import (
    _audit_prompt,
    _blind_prompt,
    audit_image_package,
    evidence_bbox_alignment,
    evidence_bbox_repair_suggestions,
    model_family,
    reconstruction_output_errors,
    verifier_is_independent,
    verify_candidate_static,
)


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
    valid_candidate.rubric[0].supported_by.append("c2")
    result = verify_candidate_static(valid_candidate, parsed_document(2), config)
    check = next(item for item in result.checks if item.check == "claims_resolve_to_evidence")
    assert check.passed


def test_rubric_requires_primary_intent_and_direct_claim_coverage(
    valid_candidate: GeneratedCandidate,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    valid_candidate.rubric[0].criterion_type = "dodged_bullet"
    result = verify_candidate_static(valid_candidate, parsed_document(2), config)
    assert not next(item for item in result.checks if item.check == "has_primary_intent").passed

    valid_candidate.rubric[0].criterion_type = "primary_intent"
    valid_candidate.rubric[0].supported_by = ["e1"]
    result = verify_candidate_static(valid_candidate, parsed_document(2), config)
    assert not next(
        item for item in result.checks if item.check == "rubric_covers_all_gold_claims"
    ).passed


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


def test_audit_prompt_exposes_proposed_evidence_as_untrusted_sidecar(
    valid_candidate: GeneratedCandidate,
) -> None:
    reconstruction = IndependentReconstruction(
        reconstructed_answer="The independently reconstructed answer is 90.",
        input_complete=True,
        cited_pages=[1, 2],
        uncertainties=[],
        missing_information=[],
    )
    template = (
        "Full={full_page_numbers}; Focus={audit_image_page_numbers}; "
        "Candidate={candidate_json}; Reconstruction={reconstruction_json}"
    )
    manifest = [
        {"attachment_index": 1, "kind": "full_page", "page_number": 1},
        {
            "attachment_index": 2,
            "kind": "evidence_crop",
            "page_number": 1,
            "node_ids": ["e1"],
        },
    ]
    template += "; Manifest={audit_image_manifest}"
    prompt = _audit_prompt(template, valid_candidate, reconstruction, [1, 2, 3], [1, 2], manifest)
    assert "Full=[1, 2, 3]" in prompt
    assert "Focus=[1, 2]" in prompt
    assert valid_candidate.task.gold_answer in prompt
    assert '"evidence_graph"' in prompt
    assert '"e1"' in prompt and '"e2"' in prompt
    assert '"evidence_crop"' in prompt


def test_audit_image_package_focuses_multimodal_but_never_leaks_images_to_text_only(
    valid_candidate: GeneratedCandidate, tmp_path: Path
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    parsed = parsed_document(3)
    full_images: list[Path] = []
    for page in parsed.pages:
        image_path = tmp_path / f"page_{page.page_number}.png"
        document = pymupdf.open()
        image_page = document.new_page(width=612, height=792)
        image_page.insert_text((72, 72), f"Synthetic page {page.page_number}")
        image_page.get_pixmap(alpha=False).save(image_path)
        document.close()
        page.image_path = image_path
        full_images.append(image_path)

    audit_pages, attachments, alignments = audit_image_package(
        valid_candidate,
        parsed,
        [1, 2, 3],
        full_images,
        config,
        tmp_path / "focused_crops",
    )
    assert audit_pages == [1, 2]
    assert {item["status"] for item in alignments} == {"not_checkable_no_excerpt"}
    assert [attachment.kind for attachment in attachments] == [
        "full_page",
        "full_page",
        "evidence_crop",
        "evidence_crop",
    ]
    assert [attachment.path for attachment in attachments[:2]] == full_images[:2]
    assert all(attachment.path.exists() for attachment in attachments)
    assert all(
        (attachment.pixel_width or 0) >= 250 and (attachment.pixel_height or 0) >= 250
        for attachment in attachments[2:]
    )

    config.verification.audit_image_scope = "full_document"
    full_pages, full_attachments, full_alignments = audit_image_package(
        valid_candidate,
        parsed,
        [1, 2, 3],
        full_images,
        config,
        tmp_path / "full_crops",
    )
    assert full_pages == [1, 2, 3]
    assert [attachment.path for attachment in full_attachments[:3]] == full_images
    assert full_alignments == alignments

    valid_candidate.input_profile = InputProfile.text_only
    assert audit_image_package(
        valid_candidate,
        parsed,
        [1, 2, 3],
        full_images,
        config,
        tmp_path / "text_only_crops",
    ) == (
        [],
        [],
        alignments,
    )


def test_evidence_bbox_alignment_distinguishes_correct_and_incorrect_regions(
    valid_candidate: GeneratedCandidate,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    excerpt = "compressor pressure ratio reaches 42 at the design point"
    valid_candidate.task.evidence_graph.nodes[0].excerpt = excerpt
    valid_candidate.task.evidence_graph.nodes[0].bbox = BoundingBox(
        x0=0.05, y0=0.05, x1=0.45, y1=0.20
    )
    page = ParsedPage(
        page_number=1,
        width_points=612,
        height_points=792,
        image_path=Path("/tmp/page_1.png"),
        extracted_text=f"Introduction. {excerpt}. Conclusions.",
        extracted_text_chars=80,
        native_text=excerpt,
        native_text_chars=len(excerpt),
        needs_ocr=False,
        blocks=[
            ParsedBlock(
                block_id="wrong-region",
                kind="text",
                bbox=BoundingBox(x0=0.05, y0=0.05, x1=0.45, y1=0.20),
                text="unrelated introductory paragraph",
                reading_order=0,
            ),
            ParsedBlock(
                block_id="right-region",
                kind="text",
                bbox=BoundingBox(x0=0.50, y0=0.50, x1=0.95, y1=0.70),
                text=excerpt,
                reading_order=1,
            ),
        ],
    )
    parsed = ParsedDocument(
        document_id="sha256:test",
        parser="test",
        parser_version="1",
        dpi=144,
        page_count=2,
        pages=[page, parsed_document(2).pages[1]],
    )

    result = evidence_bbox_alignment(valid_candidate, parsed, config)
    assert result[0]["status"] == "misaligned"
    assert result[0]["intersecting_block_ids"] == ["wrong-region"]
    suggestions = evidence_bbox_repair_suggestions(valid_candidate, parsed, config, result)
    assert len(suggestions) == 1
    assert suggestions[0].node_id == "e1"
    assert suggestions[0].confidence == "high"
    assert suggestions[0].matched_block_ids == ["right-region"]
    assert suggestions[0].suggested_bbox == BoundingBox(x0=0.50, y0=0.50, x1=0.95, y1=0.70)
    assert valid_candidate.task.evidence_graph.nodes[0].bbox == BoundingBox(
        x0=0.05, y0=0.05, x1=0.45, y1=0.20
    )

    valid_candidate.task.evidence_graph.nodes[0].bbox = BoundingBox(
        x0=0.50, y0=0.50, x1=0.95, y1=0.70
    )
    result = evidence_bbox_alignment(valid_candidate, parsed, config)
    assert result[0]["status"] == "aligned"
    assert result[0]["intersecting_block_ids"] == ["right-region"]


def test_model_family_normalizes_local_model_aliases() -> None:
    assert model_family("Qwen3.8-27B") == "qwen"
    assert model_family("org/Qwen3.8-72B") == "qwen"
    assert model_family("zai-org/GLM-5.3-Flash") == "glm"


def test_verifier_must_use_a_different_model_family() -> None:
    assert verifier_is_independent("Qwen3.8-27B", "zai-org/GLM-5.3-Flash")
    assert verifier_is_independent("zai-org/GLM-5.3-Flash", "Qwen3.8-27B")
    assert not verifier_is_independent("Qwen3.8-27B", "org/Qwen3.8-72B")


def test_reconstruction_gate_rejects_short_answer_and_missing_labels(
    valid_candidate: GeneratedCandidate,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    valid_candidate.task.prompt = (
        "Determine (a) the first value, (b) the second, and (c) the decision."
    )
    reconstruction = IndependentReconstruction(
        reconstructed_answer="The requested values are in the document.",
        input_complete=True,
        cited_pages=[1],
        uncertainties=[],
        missing_information=[],
    )
    errors = reconstruction_output_errors(
        valid_candidate,
        reconstruction,
        {"finish_reason": "stop"},
        config,
    )
    assert any("characters" in error for error in errors)
    assert any("a, b, c" in error for error in errors)


def test_reconstruction_gate_accepts_substantive_labeled_answer(
    valid_candidate: GeneratedCandidate,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    valid_candidate.task.prompt = (
        "Determine (a) the first value, (b) the second, and (c) the decision."
    )
    reconstruction = IndependentReconstruction(
        reconstructed_answer=(
            "(a) The first value is 10 based on page 1. "
            "(b) The second value is 20 after applying the stated exception on page 2. "
            "(c) The decision is to reject the proposal because the combined result exceeds "
            "the controlling threshold. " * 2
        ),
        input_complete=True,
        cited_pages=[1, 2],
        uncertainties=[],
        missing_information=[],
    )
    assert not reconstruction_output_errors(
        valid_candidate,
        reconstruction,
        {"finish_reason": "stop"},
        config,
    )
