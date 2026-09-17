from __future__ import annotations

from pathlib import Path

from pdf_sft.config import load_config
from pdf_sft.io import write_json_atomic, write_jsonl_atomic
from pdf_sft.schemas import (
    BoundingBox,
    DocumentRecord,
    GeneratedCandidate,
    InputProfile,
    LicenseRecord,
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
)
from pdf_sft.stages.build_input import build_input_package
from pdf_sft.stages.finalize import evaluate_simple_arithmetic, run_finalize
from pdf_sft.stages.verify import verify_candidate_static


def test_safe_arithmetic_evaluator_rejects_non_arithmetic() -> None:
    assert evaluate_simple_arithmetic("100 - 10") == 90
    assert evaluate_simple_arithmetic("(12 + 3) * 2") == 30
    assert evaluate_simple_arithmetic("result = 90") is None
    assert evaluate_simple_arithmetic("__import__('os')") is None


def test_finalize_requires_human_checklist_before_difficulty(
    valid_candidate: GeneratedCandidate,
    tmp_path: Path,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml")).model_copy(deep=True)
    config.paths.documents = tmp_path / "documents.jsonl"
    config.paths.parsed = tmp_path / "parsed"
    config.paths.document_views = tmp_path / "views"
    config.paths.input_packages = tmp_path / "input_packages"
    config.paths.repaired = tmp_path / "repaired.jsonl"
    config.paths.finalized = tmp_path / "finalized.jsonl"
    valid_candidate.input_profile = InputProfile.text_only
    valid_candidate.task.supported_input_profiles = [InputProfile.text_only]
    valid_candidate.task.evidence_graph.nodes[0].excerpt = "base value 100"
    valid_candidate.task.evidence_graph.nodes[1].excerpt = "controlling exception 10"
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    document = DocumentRecord(
        document_id="sha256:test",
        candidate_id="candidate-test",
        source_id="test",
        source_url="https://example.test/source.pdf",
        title="Synthetic source",
        publisher="Test",
        content_sha256="test",
        size_bytes=pdf_path.stat().st_size,
        pdf_path=pdf_path,
        license=LicenseRecord(
            status="approved",
            license_id="test-license",
            evidence_url="https://example.test/license",
            review_notes="Synthetic unit test",
        ),
    )
    parsed = ParsedDocument(
        document_id=document.document_id,
        parser="liteparse",
        parser_version="2.5.0",
        dpi=150,
        page_count=2,
        pages=[
            ParsedPage(
                page_number=1,
                width_points=612,
                height_points=792,
                image_path=tmp_path / "page_1.png",
                extracted_text="base value 100",
                extracted_text_chars=14,
                native_text="base value 100",
                native_text_chars=14,
                needs_ocr=False,
                blocks=[
                    ParsedBlock(
                        block_id="p1_b1",
                        kind="text",
                        bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.5, y1=0.3),
                        text="base value 100",
                        reading_order=0,
                    )
                ],
            ),
            ParsedPage(
                page_number=2,
                width_points=612,
                height_points=792,
                image_path=tmp_path / "page_2.png",
                extracted_text="controlling exception 10",
                extracted_text_chars=24,
                native_text="controlling exception 10",
                native_text_chars=24,
                needs_ocr=False,
                blocks=[
                    ParsedBlock(
                        block_id="p2_b1",
                        kind="text",
                        bbox=BoundingBox(x0=0.2, y0=0.2, x1=0.8, y1=0.4),
                        text="controlling exception 10",
                        reading_order=0,
                    )
                ],
            ),
        ],
    )
    view, package = build_input_package(document, parsed, config, InputProfile.text_only)
    valid_candidate.document_view_id = view.document_view_id
    write_jsonl_atomic(config.paths.documents, [document])
    write_json_atomic(config.paths.parsed / "test" / "document.json", parsed)
    write_json_atomic(config.paths.document_views / "test.json", view)
    write_json_atomic(config.paths.input_packages / "text_only" / "test.json", package)
    record = verify_candidate_static(valid_candidate, parsed, config, view).model_copy(
        update={"independent_verifier_status": "passed"}
    )
    write_jsonl_atomic(config.paths.repaired, [record])
    review_root = tmp_path / "review"
    decision_path = (
        review_root / "artifacts" / valid_candidate.sample_id / "sample_review_decision.json"
    )
    pending_decision = {
        "schema_version": "0.1",
        "sample_id": valid_candidate.sample_id,
        "decision": "pending",
        "reviewer": None,
        "reviewer_type": "human",
        "checklist": {},
    }
    write_json_atomic(decision_path, pending_decision)

    pending = run_finalize(config, review_root)
    assert pending[0].final_validation_status == "needs_review"
    assert not pending[0].eligible_for_difficulty

    pending_decision.update(
        {
            "decision": "approved",
            "reviewer": "human-reviewer",
            "checklist": {
                "question_unambiguous": True,
                "gold_answer_verified": True,
                "derivations_verified": True,
                "rubric_negative_cases_verified": True,
                "visual_evidence_verified": True,
                "omitted_page_audit_verified": False,
            },
            "rubric_overrides": [
                {
                    "criterion_id": "r2",
                    "criterion": "Does not ignore the controlling exception on page 2.",
                    "severity": "major",
                    "reason": "Human negative-case review clarified scope and severity.",
                }
            ],
        }
    )
    write_json_atomic(decision_path, pending_decision)
    approved = run_finalize(config, review_root)
    assert approved[0].final_validation_status == "passed"
    assert approved[0].human_review_status == "approved"
    assert approved[0].eligible_for_difficulty
    assert approved[0].candidate.rubric[1].severity == "major"
    assert approved[0].candidate.rubric[1].criterion.startswith("Does not ignore")
    assert approved[0].rubric_overrides[0].reviewer == "human-reviewer"
    assert approved[0].rubric_overrides[0].criterion_id == "r2"
