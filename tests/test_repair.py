from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from pdf_sft.config import load_config
from pdf_sft.io import write_json_atomic, write_jsonl_atomic
from pdf_sft.schemas import (
    BoundingBox,
    GeneratedCandidate,
    IndependentReconstruction,
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
    ValidationCheck,
    VerificationDecision,
)
from pdf_sft.stages.repair import _refresh_unmodified_bbox_result, run_apply_bbox_repairs
from pdf_sft.stages.review_pack import _bbox_review_assets
from pdf_sft.stages.verify import verify_candidate_static


def _fixture_page(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Synthetic evidence")
    page.get_pixmap(alpha=False).save(path)
    document.close()


def test_bbox_repair_requires_resolved_decision_and_writes_new_artifact(
    valid_candidate: GeneratedCandidate,
    tmp_path: Path,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml")).model_copy(deep=True)
    config.paths.parsed = tmp_path / "parsed"
    config.paths.document_views = tmp_path / "views"
    config.paths.verified = tmp_path / "verified.jsonl"
    config.paths.repaired = tmp_path / "repaired.jsonl"
    excerpt = "compressor pressure ratio reaches 42 at the design point"
    node = valid_candidate.task.evidence_graph.nodes[0]
    node.excerpt = excerpt
    node.bbox = BoundingBox(x0=0.05, y0=0.05, x1=0.45, y1=0.20)
    page_1_image = tmp_path / "page_1.png"
    page_2_image = tmp_path / "page_2.png"
    _fixture_page(page_1_image)
    _fixture_page(page_2_image)
    parsed = ParsedDocument(
        document_id="sha256:test",
        parser="test",
        parser_version="1",
        dpi=144,
        page_count=2,
        pages=[
            ParsedPage(
                page_number=1,
                width_points=612,
                height_points=792,
                image_path=page_1_image,
                extracted_text=excerpt,
                extracted_text_chars=len(excerpt),
                native_text=excerpt,
                native_text_chars=len(excerpt),
                needs_ocr=False,
                blocks=[
                    ParsedBlock(
                        block_id="wrong",
                        kind="text",
                        bbox=BoundingBox(x0=0.05, y0=0.05, x1=0.45, y1=0.20),
                        text="unrelated text",
                        reading_order=0,
                    ),
                    ParsedBlock(
                        block_id="right",
                        kind="text",
                        bbox=BoundingBox(x0=0.50, y0=0.50, x1=0.95, y1=0.70),
                        text=excerpt,
                        reading_order=1,
                    ),
                ],
            ),
            ParsedPage(
                page_number=2,
                width_points=612,
                height_points=792,
                image_path=page_2_image,
                extracted_text="exception",
                extracted_text_chars=9,
                native_text="exception",
                native_text_chars=9,
                needs_ocr=False,
                blocks=[],
            ),
        ],
    )
    parsed_path = config.paths.parsed / "test" / "document.json"
    write_json_atomic(parsed_path, parsed)
    record = verify_candidate_static(valid_candidate, parsed, config).model_copy(
        update={"independent_verifier_status": "passed"}
    )
    write_jsonl_atomic(config.paths.verified, [record])
    review_root = tmp_path / "review"
    _, _, suggestions_path = _bbox_review_assets(record, parsed, config, review_root)

    pending = run_apply_bbox_repairs(config, review_root)
    assert not pending[0].bbox_repairs
    pending_check = next(
        item for item in pending[0].checks if item.check == "bbox_repair_decisions_resolved"
    )
    assert not pending_check.passed
    assert pending[0].candidate.task.evidence_graph.nodes[0].bbox == node.bbox

    decisions_path = suggestions_path.parent / "bbox_repair_decisions.json"
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions["decisions"][0].update(
        {"decision": "accepted", "reviewer": "human-reviewer", "notes": "Crop confirmed"}
    )
    write_json_atomic(decisions_path, decisions)
    repaired = run_apply_bbox_repairs(config, review_root)

    repaired_node = repaired[0].candidate.task.evidence_graph.nodes[0]
    assert repaired_node.bbox == BoundingBox(x0=0.50, y0=0.50, x1=0.95, y1=0.70)
    assert repaired[0].independent_verifier_status == "not_run"
    assert repaired[0].bbox_repairs[0].reviewer == "human-reviewer"
    assert repaired[0].bbox_repairs[0].original_bbox == node.bbox
    assert next(
        item for item in repaired[0].checks if item.check == "bbox_repair_decisions_resolved"
    ).passed
    original_payload = next(
        iter(json.loads(line) for line in config.paths.verified.read_text().splitlines())
    )
    assert original_payload["candidate"]["task"]["evidence_graph"]["nodes"][0]["bbox"] == {
        "x0": 0.05,
        "x1": 0.45,
        "y0": 0.05,
        "y1": 0.2,
    }


def test_empty_visual_suggestions_refresh_stale_bbox_status(
    valid_candidate: GeneratedCandidate,
    tmp_path: Path,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    candidate = valid_candidate.model_copy(deep=True)
    candidate.task.requires_visual_evidence = True
    for index, node in enumerate(candidate.task.evidence_graph.nodes, 1):
        node.excerpt = f"Figure {index}-1 visual relationship"
    parsed = ParsedDocument(
        document_id=candidate.document_id,
        parser="test",
        parser_version="1",
        dpi=144,
        page_count=2,
        pages=[
            ParsedPage(
                page_number=page_number,
                width_points=612,
                height_points=792,
                image_path=tmp_path / f"page_{page_number}.png",
                extracted_text=node.excerpt or "",
                extracted_text_chars=len(node.excerpt or ""),
                native_text=node.excerpt or "",
                native_text_chars=len(node.excerpt or ""),
                needs_ocr=False,
                blocks=[],
            )
            for page_number, node in enumerate(candidate.task.evidence_graph.nodes, 1)
        ],
    )
    record = verify_candidate_static(candidate, parsed, config).model_copy(
        update={
            "checks": [
                ValidationCheck(
                    check="independent_evidence_bbox_alignment",
                    passed=False,
                    details="stale visual-text mismatch",
                ),
                ValidationCheck(check="independent_audit_output_complete", passed=True),
            ],
            "independent_reconstruction": IndependentReconstruction(
                reconstructed_answer="A complete independent answer.",
                input_complete=True,
                cited_pages=[1, 2],
                uncertainties=[],
                missing_information=[],
            ),
            "independent_verification": VerificationDecision(
                reconstructed_answer="The gold is supported.",
                verified_claim_ids=["c1"],
                disputed_claim_ids=[],
                missing_evidence_node_ids=[],
                input_complete=True,
                gold_supported=True,
                requires_human_review=False,
                failure_reasons=[],
            ),
            "independent_verifier_status": "needs_review",
        }
    )

    refreshed = _refresh_unmodified_bbox_result(
        record,
        parsed,
        config,
        ValidationCheck(check="bbox_repair_decisions_resolved", passed=True),
    )

    assert refreshed.independent_verifier_status == "passed"
    assert next(
        item for item in refreshed.checks if item.check == "independent_evidence_bbox_alignment"
    ).passed
