"""Apply explicitly accepted bbox repair decisions to a new validated-record artifact."""

from __future__ import annotations

import json
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_jsonl_atomic
from pdf_sft.schemas import (
    AppliedBBoxRepair,
    BoundingBox,
    DocumentView,
    EvidenceBBoxRepairSuggestion,
    ParsedDocument,
    ValidatedCandidate,
    ValidationCheck,
)
from pdf_sft.stages.verify import verify_candidate_static


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_with_replacement(
    checks: list[ValidationCheck], replacement: ValidationCheck
) -> list[ValidationCheck]:
    return [check for check in checks if check.check != replacement.check] + [replacement]


def run_apply_bbox_repairs(
    config: AppConfig,
    review_pack_root: Path,
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> list[ValidatedCandidate]:
    """Apply accepted decisions without overwriting the original verified JSONL."""

    input_path = (input_path or config.paths.verified).resolve()
    output_path = (output_path or config.paths.repaired).resolve()
    if input_path == output_path:
        raise ValueError("BBox repairs must write a new artifact, not overwrite verified input")

    parsed_by_id: dict[str, ParsedDocument] = {}
    for directory in config.paths.parsed.iterdir():
        document_path = directory / "document.json"
        if document_path.exists():
            parsed = ParsedDocument.model_validate_json(document_path.read_text(encoding="utf-8"))
            parsed_by_id[parsed.document_id] = parsed
    views_by_id: dict[str, DocumentView] = {}
    if config.paths.document_views.exists():
        for path in config.paths.document_views.glob("*.json"):
            view = DocumentView.model_validate_json(path.read_text(encoding="utf-8"))
            views_by_id[view.document_id] = view

    output_records: list[ValidatedCandidate] = []
    for payload in read_jsonl(input_path):
        record = ValidatedCandidate.model_validate(payload)
        candidate = record.candidate.model_copy(deep=True)
        artifact_root = review_pack_root / "artifacts" / candidate.sample_id
        suggestions_path = artifact_root / "bbox_repair_suggestions.json"
        decisions_path = artifact_root / "bbox_repair_decisions.json"
        bbox_check = next(
            (
                check
                for check in record.checks
                if check.check == "independent_evidence_bbox_alignment"
            ),
            None,
        )
        if not suggestions_path.exists():
            repair_check = ValidationCheck(
                check="bbox_repair_decisions_resolved",
                passed=bbox_check is None or bbox_check.passed,
                details=(
                    None
                    if bbox_check is None or bbox_check.passed
                    else "Evidence bbox failed but no repair suggestion artifact was found"
                ),
            )
            output_records.append(
                record.model_copy(
                    update={
                        "checks": _check_with_replacement(record.checks, repair_check),
                        "eligible_for_difficulty": False,
                    }
                )
            )
            continue

        suggestion_payload = _load_json(suggestions_path)
        if suggestion_payload.get("sample_id") != candidate.sample_id:
            raise ValueError(f"Suggestion artifact sample mismatch at {suggestions_path}")
        if suggestion_payload.get("document_id") != candidate.document_id:
            raise ValueError(f"Suggestion artifact document mismatch at {suggestions_path}")
        suggestions = [
            EvidenceBBoxRepairSuggestion.model_validate(item)
            for item in suggestion_payload.get("suggestions", [])
        ]
        if not suggestions:
            repair_check = ValidationCheck(
                check="bbox_repair_decisions_resolved", passed=True, details=None
            )
            output_records.append(
                record.model_copy(
                    update={
                        "checks": _check_with_replacement(record.checks, repair_check),
                        "eligible_for_difficulty": False,
                    }
                )
            )
            continue
        if not decisions_path.exists():
            raise ValueError(f"Missing bbox repair decisions for {candidate.sample_id}")

        decision_payload = _load_json(decisions_path)
        if decision_payload.get("sample_id") != candidate.sample_id:
            raise ValueError(f"Decision artifact sample mismatch at {decisions_path}")
        decisions = {item.get("node_id"): item for item in decision_payload.get("decisions", [])}
        node_by_id = {node.id: node for node in candidate.task.evidence_graph.nodes}
        applied: list[AppliedBBoxRepair] = []
        unresolved: list[str] = []
        for suggestion in suggestions:
            decision = decisions.get(suggestion.node_id)
            if decision is None:
                unresolved.append(f"{suggestion.node_id}:missing_decision")
                continue
            status = decision.get("decision")
            if status not in {"pending", "accepted", "rejected"}:
                raise ValueError(
                    f"Invalid decision {status!r} for {candidate.sample_id}/{suggestion.node_id}"
                )
            if status != "accepted":
                unresolved.append(f"{suggestion.node_id}:{status}")
                continue
            reviewer = str(decision.get("reviewer") or "").strip()
            if not reviewer:
                raise ValueError(
                    f"Accepted repair {candidate.sample_id}/{suggestion.node_id} needs a reviewer"
                )
            accepted_payload = decision.get("accepted_bbox")
            accepted_bbox = (
                BoundingBox.model_validate(accepted_payload)
                if accepted_payload is not None
                else suggestion.suggested_bbox
            )
            if accepted_bbox is None:
                raise ValueError(
                    f"Accepted repair {candidate.sample_id}/{suggestion.node_id} needs a manual bbox"
                )
            node = node_by_id.get(suggestion.node_id)
            if node is None:
                raise ValueError(f"Unknown evidence node {suggestion.node_id} in repair decision")
            if node.bbox != suggestion.original_bbox:
                raise ValueError(
                    f"Stale bbox suggestion for {candidate.sample_id}/{suggestion.node_id}"
                )
            original_bbox = node.bbox
            node.bbox = accepted_bbox
            applied.append(
                AppliedBBoxRepair(
                    node_id=node.id,
                    page_number=node.page,
                    original_bbox=original_bbox,
                    accepted_bbox=accepted_bbox,
                    suggestion_confidence=suggestion.confidence,
                    matched_block_ids=suggestion.matched_block_ids,
                    reviewer=reviewer,
                    notes=decision.get("notes"),
                    decision_artifact=decisions_path.resolve(),
                )
            )

        repair_check = ValidationCheck(
            check="bbox_repair_decisions_resolved",
            passed=not unresolved,
            details=None if not unresolved else f"Unresolved repairs: {', '.join(unresolved)}",
        )
        if applied:
            parsed = parsed_by_id.get(candidate.document_id)
            if parsed is None:
                raise ValueError(f"Missing parsed document for {candidate.document_id}")
            repaired = verify_candidate_static(
                candidate, parsed, config, views_by_id.get(candidate.document_id)
            )
            repaired = repaired.model_copy(
                update={
                    "checks": _check_with_replacement(repaired.checks, repair_check),
                    "bbox_repairs": [*record.bbox_repairs, *applied],
                    "eligible_for_difficulty": False,
                }
            )
        else:
            repaired = record.model_copy(
                update={
                    "checks": _check_with_replacement(record.checks, repair_check),
                    "eligible_for_difficulty": False,
                }
            )
        output_records.append(repaired)

    write_jsonl_atomic(output_path, output_records)
    return output_records
