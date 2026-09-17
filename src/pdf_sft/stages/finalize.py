"""Conservative final validation before difficulty scoring and export."""

from __future__ import annotations

import ast
import json
import math
import operator
import re
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_jsonl_atomic
from pdf_sft.schemas import (
    AppliedRubricOverride,
    DocumentRecord,
    DocumentScope,
    DocumentView,
    ParsedDocument,
    RubricCriterion,
    ValidatedCandidate,
    ValidationCheck,
)
from pdf_sft.stages.build_input import load_input_packages
from pdf_sft.stages.verify import evidence_bbox_alignment

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _evaluate_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        return float(
            _BINARY_OPERATORS[type(node.op)](_evaluate_node(node.left), _evaluate_node(node.right))
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return float(_UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand)))
    raise ValueError("Expression is not a supported arithmetic-only derivation")


def evaluate_simple_arithmetic(expression: str) -> float | None:
    normalized = (
        expression.strip().replace("×", "*").replace("÷", "/").replace("−", "-").replace("^", "**")
    )
    if not normalized or "=" in normalized:
        return None
    try:
        parsed = ast.parse(normalized, mode="eval")
        value = _evaluate_node(parsed)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _numbers(text: str) -> list[float]:
    values: list[float] = []
    for raw in re.findall(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?", text):
        try:
            values.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return values


def deterministic_derivation_results(record: ValidatedCandidate) -> list[dict]:
    claims = {claim.claim_id: claim.text for claim in record.candidate.task.claims}
    results: list[dict] = []
    for derivation in record.candidate.task.derivations:
        value = evaluate_simple_arithmetic(derivation.expression)
        expected_values = _numbers(claims.get(derivation.result_claim, ""))
        if value is None:
            status = "not_checkable"
        elif any(
            math.isclose(value, expected, rel_tol=0.005, abs_tol=1e-6)
            for expected in expected_values
        ):
            status = "verified"
        else:
            status = "mismatch"
        results.append(
            {
                "result_claim": derivation.result_claim,
                "expression": derivation.expression,
                "computed_value": value,
                "claim_numeric_values": expected_values,
                "status": status,
            }
        )
    return results


def _decision_for(review_pack_root: Path, sample_id: str) -> dict:
    path = review_pack_root / "artifacts" / sample_id / "sample_review_decision.json"
    if not path.exists():
        return {"decision": "pending", "checklist": {}, "artifact_path": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("sample_id") != sample_id:
        raise ValueError(f"Sample review decision mismatch at {path}")
    payload["artifact_path"] = str(path.resolve())
    return payload


def _apply_rubric_overrides(
    record: ValidatedCandidate,
    decision: dict,
    *,
    reviewer: str,
) -> ValidatedCandidate:
    raw_overrides = decision.get("rubric_overrides") or []
    if not raw_overrides:
        return record
    if decision.get("decision") != "approved" or decision.get("reviewer_type") != "human":
        raise ValueError("Rubric overrides require an approved human review decision")
    if not reviewer:
        raise ValueError("Rubric overrides require a non-empty human reviewer")

    by_id = {criterion.criterion_id: criterion for criterion in record.candidate.rubric}
    if len(by_id) != len(record.candidate.rubric):
        raise ValueError("Cannot apply rubric overrides when criterion IDs are duplicated")
    applied: list[AppliedRubricOverride] = []
    seen: set[str] = set()
    for raw in raw_overrides:
        allowed = {"criterion_id", "criterion", "severity", "reason"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unsupported rubric override fields: {sorted(unknown)}")
        criterion_id = str(raw.get("criterion_id") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        if not criterion_id or criterion_id in seen:
            raise ValueError(f"Invalid or duplicate rubric override ID: {criterion_id!r}")
        seen.add(criterion_id)
        original = by_id.get(criterion_id)
        if original is None:
            raise ValueError(f"Rubric override references unknown criterion {criterion_id!r}")
        if not reason:
            raise ValueError(f"Rubric override {criterion_id!r} requires a reason")
        update = original.model_dump()
        if "criterion" in raw:
            update["criterion"] = raw["criterion"]
        if "severity" in raw:
            update["severity"] = raw["severity"]
        revised = RubricCriterion.model_validate(update)
        if revised == original:
            raise ValueError(f"Rubric override {criterion_id!r} does not change the criterion")
        by_id[criterion_id] = revised
        applied.append(
            AppliedRubricOverride(
                criterion_id=criterion_id,
                original_criterion=original.criterion,
                updated_criterion=revised.criterion,
                original_severity=original.severity,
                updated_severity=revised.severity,
                reviewer=reviewer,
                reason=reason,
                decision_artifact=Path(decision["artifact_path"]),
            )
        )

    candidate = record.candidate.model_copy(
        update={"rubric": [by_id[criterion.criterion_id] for criterion in record.candidate.rubric]}
    )
    return record.model_copy(
        update={
            "candidate": candidate,
            "rubric_overrides": [*record.rubric_overrides, *applied],
        }
    )


def _replace_final_checks(
    record: ValidatedCandidate, final_checks: list[ValidationCheck]
) -> list[ValidationCheck]:
    return [check for check in record.checks if not check.check.startswith("final_")] + final_checks


def run_finalize(
    config: AppConfig,
    review_pack_root: Path,
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> list[ValidatedCandidate]:
    """Apply final automatic and human gates without treating unknowns as passes."""

    input_path = (input_path or config.paths.repaired).resolve()
    output_path = (output_path or config.paths.finalized).resolve()
    if input_path == output_path:
        raise ValueError("Final validation must write a new artifact")

    parsed_by_id: dict[str, ParsedDocument] = {}
    for directory in config.paths.parsed.iterdir():
        document_path = directory / "document.json"
        if document_path.exists():
            parsed = ParsedDocument.model_validate_json(document_path.read_text(encoding="utf-8"))
            parsed_by_id[parsed.document_id] = parsed
    views_by_id: dict[str, DocumentView] = {}
    for path in config.paths.document_views.glob("*.json"):
        view = DocumentView.model_validate_json(path.read_text(encoding="utf-8"))
        views_by_id[view.document_id] = view
    documents_by_id = {
        document.document_id: document
        for document in (
            DocumentRecord.model_validate(payload) for payload in read_jsonl(config.paths.documents)
        )
    }
    packages_by_profile = {}

    finalized: list[ValidatedCandidate] = []
    for payload in read_jsonl(input_path):
        record = ValidatedCandidate.model_validate(payload)
        candidate = record.candidate
        parsed = parsed_by_id[candidate.document_id]
        view = views_by_id.get(candidate.document_id)
        document = documents_by_id.get(candidate.document_id)
        decision = _decision_for(review_pack_root, candidate.sample_id)
        checklist = decision.get("checklist") or {}
        decision_status = decision.get("decision", "pending")
        if decision_status not in {"pending", "approved", "rejected"}:
            raise ValueError(
                f"Invalid sample review decision {decision_status!r} for {candidate.sample_id}"
            )
        reviewer = str(decision.get("reviewer") or "").strip()
        reviewer_type = decision.get("reviewer_type")
        record = _apply_rubric_overrides(record, decision, reviewer=reviewer)
        candidate = record.candidate
        required_review_items = [
            "question_unambiguous",
            "gold_answer_verified",
            "rubric_negative_cases_verified",
        ]
        if candidate.task.derivations:
            required_review_items.append("derivations_verified")
        if candidate.task.requires_visual_evidence:
            required_review_items.append("visual_evidence_verified")
        if view is not None and view.scope == DocumentScope.bounded:
            required_review_items.append("omitted_page_audit_verified")
        review_complete = (
            decision_status == "approved"
            and bool(reviewer)
            and reviewer_type == "human"
            and all(checklist.get(item) is True for item in required_review_items)
        )
        human_status = (
            "approved"
            if review_complete
            else "rejected"
            if decision_status == "rejected"
            else "not_reviewed"
        )

        source_passed = (
            document is not None
            and document.license.status.value == "approved"
            and not any(
                marker.lower() in document.source_url.lower()
                for marker in config.security.forbidden_source_substrings
            )
        )
        profile = candidate.input_profile
        if profile not in packages_by_profile:
            packages_by_profile[profile] = load_input_packages(config, profile)
        package = packages_by_profile[profile].get(candidate.document_id)
        input_passed = (
            package is not None
            and package.token_accounting.fits_context
            and candidate.document_view_id == package.document_view_id
        )

        alignments = evidence_bbox_alignment(candidate, parsed, config)
        bbox_bad = [
            item["node_id"]
            for item in alignments
            if item["status"] in {"misaligned", "missing_page"}
        ]
        bbox_unknown = [
            item["node_id"] for item in alignments if item["status"].startswith("not_checkable")
        ]
        bbox_passed = not bbox_bad and (
            not bbox_unknown or (review_complete and checklist.get("visual_evidence_verified"))
        )
        repair_check = next(
            (check for check in record.checks if check.check == "bbox_repair_decisions_resolved"),
            None,
        )
        repairs_passed = repair_check is None or repair_check.passed

        derivations = deterministic_derivation_results(record)
        derivation_mismatches = [
            item["result_claim"] for item in derivations if item["status"] == "mismatch"
        ]
        derivation_unknown = [
            item["result_claim"] for item in derivations if item["status"] == "not_checkable"
        ]
        derivations_passed = not derivation_mismatches and (
            not derivation_unknown or (review_complete and checklist.get("derivations_verified"))
        )

        rubric_types = {criterion.criterion_type for criterion in candidate.rubric}
        rubric_references = {
            reference for criterion in candidate.rubric for reference in criterion.supported_by
        }
        claim_ids = {claim.claim_id for claim in candidate.task.claims}
        rubric_structure_passed = {"primary_intent", "dodged_bullet"}.issubset(
            rubric_types
        ) and claim_ids.issubset(rubric_references)
        rubric_passed = (
            rubric_structure_passed
            and review_complete
            and checklist.get("rubric_negative_cases_verified")
        )
        verifier_passed = record.independent_verifier_status == "passed"
        view_passed = view is not None and (
            view.scope == DocumentScope.full_pdf
            or (review_complete and checklist.get("omitted_page_audit_verified"))
        )

        final_checks = [
            ValidationCheck(
                check="final_source_and_license",
                passed=source_passed,
                details=None if source_passed else "Source/license missing, rejected, or forbidden",
            ),
            ValidationCheck(
                check="final_input_package",
                passed=input_passed,
                details=None
                if input_passed
                else "Frozen input package missing, mismatched, or over budget",
            ),
            ValidationCheck(
                check="final_document_view_audit",
                passed=bool(view_passed),
                details=(
                    None
                    if view_passed
                    else "Bounded or missing document view lacks an approved omitted-page audit"
                ),
            ),
            ValidationCheck(
                check="final_independent_gold_verification",
                passed=verifier_passed,
                details=(
                    None
                    if verifier_passed
                    else f"independent_verifier_status={record.independent_verifier_status}"
                ),
            ),
            ValidationCheck(
                check="final_evidence_bbox_alignment",
                passed=bool(bbox_passed and repairs_passed),
                details=(
                    None
                    if bbox_passed and repairs_passed
                    else f"bad={bbox_bad}; not_checkable={bbox_unknown}; repairs_resolved={repairs_passed}"
                ),
            ),
            ValidationCheck(
                check="final_deterministic_derivations",
                passed=bool(derivations_passed),
                details=(
                    None
                    if derivations_passed
                    else f"mismatch={derivation_mismatches}; not_checkable={derivation_unknown}"
                ),
            ),
            ValidationCheck(
                check="final_rubric_unit_review",
                passed=bool(rubric_passed),
                details=(
                    None
                    if rubric_passed
                    else "Rubric structure or human negative-case review is incomplete"
                ),
            ),
            ValidationCheck(
                check="final_human_review",
                passed=review_complete,
                details=(
                    None
                    if review_complete
                    else f"decision={decision_status}; required={required_review_items}"
                ),
            ),
        ]
        all_passed = record.static_checks_passed and all(check.passed for check in final_checks)
        fatal_failure = (
            not record.static_checks_passed
            or not source_passed
            or bool(derivation_mismatches)
            or not rubric_structure_passed
            or decision_status == "rejected"
            or record.independent_verifier_status == "failed"
        )
        final_status = "passed" if all_passed else "failed" if fatal_failure else "needs_review"
        finalized.append(
            record.model_copy(
                update={
                    "checks": _replace_final_checks(record, final_checks),
                    "human_review_status": human_status,
                    "final_validation_status": final_status,
                    "eligible_for_difficulty": final_status == "passed",
                }
            )
        )

    write_jsonl_atomic(output_path, finalized)
    return finalized
