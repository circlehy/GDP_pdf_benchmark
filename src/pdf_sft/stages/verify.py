"""Static, non-LLM verification before independent answer reconstruction."""

from __future__ import annotations

import json
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.difficulty import structural_gate
from pdf_sft.io import read_jsonl, write_json_atomic, write_jsonl_atomic
from pdf_sft.llm import StructuredModelClient
from pdf_sft.schemas import (
    GeneratedCandidate,
    IndependentReconstruction,
    ParsedDocument,
    ValidatedCandidate,
    ValidationCheck,
    VerificationDecision,
)

VERIFIER_PROMPT_VERSION = "verifier_v0"
VERIFIER_AUDIT_PROMPT_VERSION = "verifier_audit_v0"


def _check(name: str, passed: bool, details: str | None = None) -> ValidationCheck:
    return ValidationCheck(check=name, passed=passed, details=None if passed else details)


def _claim_reference_errors(candidate: GeneratedCandidate) -> list[str]:
    """Require claim dependencies to be valid, acyclic, and grounded in PDF evidence."""
    node_ids = {node.id for node in candidate.task.evidence_graph.nodes}
    claims = {claim.claim_id: claim for claim in candidate.task.claims}
    allowed = node_ids | claims.keys()
    errors: list[str] = []

    for claim in claims.values():
        missing = sorted(set(claim.supported_by) - allowed)
        if missing:
            errors.append(f"{claim.claim_id} has unknown references {missing}")

    state: dict[str, int] = {}

    def visit(claim_id: str, path: tuple[str, ...]) -> bool:
        if state.get(claim_id) == 1:
            errors.append(f"claim dependency cycle: {' -> '.join((*path, claim_id))}")
            return False
        if state.get(claim_id) == 2:
            return True

        state[claim_id] = 1
        grounded = False
        for reference in claims[claim_id].supported_by:
            if reference in node_ids:
                grounded = True
            elif reference in claims:
                grounded = visit(reference, (*path, claim_id)) or grounded
        state[claim_id] = 2
        if not grounded:
            errors.append(f"{claim_id} does not resolve to a PDF evidence node")
        return grounded

    for claim_id in claims:
        if state.get(claim_id) != 2:
            visit(claim_id, ())
    return sorted(set(errors))


def verify_candidate_static(
    candidate: GeneratedCandidate,
    parsed_document: ParsedDocument,
    config: AppConfig,
) -> ValidatedCandidate:
    graph = candidate.task.evidence_graph
    node_ids = {node.id for node in graph.nodes}
    claim_ids = {claim.claim_id for claim in candidate.task.claims}
    rubric_refs = node_ids | claim_ids
    checks: list[ValidationCheck] = []

    invalid_pages = sorted(
        {node.page for node in graph.nodes if node.page > parsed_document.page_count}
    )
    checks.append(
        _check(
            "evidence_pages_in_range",
            not invalid_pages,
            f"Out-of-range pages: {invalid_pages}",
        )
    )

    claim_reference_errors = _claim_reference_errors(candidate)
    checks.append(
        _check(
            "claims_resolve_to_evidence",
            not claim_reference_errors,
            "; ".join(claim_reference_errors),
        )
    )

    bad_rubric = sorted(
        criterion.criterion_id
        for criterion in candidate.rubric
        if not set(criterion.supported_by).issubset(rubric_refs)
    )
    checks.append(
        _check(
            "rubric_references_exist",
            not bad_rubric,
            f"Rubric criteria with unknown references: {bad_rubric}",
        )
    )

    derivation_refs = node_ids | claim_ids
    bad_derivations = sorted(
        f"{derivation.result_claim}: {sorted(set(derivation.inputs) - derivation_refs)}"
        for derivation in candidate.task.derivations
        if derivation.result_claim not in claim_ids
        or not set(derivation.inputs).issubset(derivation_refs)
    )
    checks.append(
        _check(
            "derivation_claims_exist",
            not bad_derivations,
            f"Derivations have unknown result claims or inputs: {bad_derivations}",
        )
    )

    rubric_ids = [criterion.criterion_id for criterion in candidate.rubric]
    checks.append(
        _check(
            "rubric_ids_unique",
            len(rubric_ids) == len(set(rubric_ids)),
            "Duplicate rubric criterion IDs",
        )
    )
    checks.append(
        _check(
            "has_dodged_bullet",
            any(item.criterion_type == "dodged_bullet" for item in candidate.rubric),
            "At least one plausible Dodged Bullet is required",
        )
    )

    gate = structural_gate(candidate, config.difficulty)
    checks.append(_check("gdp_like_structural_gate", gate.passed, ", ".join(gate.reasons)))
    static_passed = all(check.passed for check in checks)
    return ValidatedCandidate(
        candidate=candidate,
        structural_gate=gate,
        checks=checks,
        static_checks_passed=static_passed,
        independent_verifier_status="not_run",
        human_review_status="not_reviewed",
        eligible_for_difficulty=False,
    )


def run_static_verify(
    config: AppConfig,
) -> tuple[list[ValidatedCandidate], list[ValidatedCandidate]]:
    accepted: list[ValidatedCandidate] = []
    rejected: list[ValidatedCandidate] = []
    previous_by_sample: dict[str, ValidatedCandidate] = {}
    if config.paths.verified.exists():
        previous_by_sample = {
            item.candidate.sample_id: item
            for item in (
                ValidatedCandidate.model_validate(payload)
                for payload in read_jsonl(config.paths.verified)
            )
        }
    parsed_by_id: dict[str, ParsedDocument] = {}
    for document_dir in config.paths.parsed.iterdir():
        document_path = document_dir / "document.json"
        if document_path.exists():
            parsed = ParsedDocument.model_validate_json(document_path.read_text(encoding="utf-8"))
            parsed_by_id[parsed.document_id] = parsed

    for payload in read_jsonl(config.paths.generated):
        candidate = GeneratedCandidate.model_validate(payload)
        parsed = parsed_by_id.get(candidate.document_id)
        if parsed is None:
            raise ValueError(f"Missing parsed document for {candidate.document_id}")
        result = verify_candidate_static(candidate, parsed, config)
        previous = previous_by_sample.get(candidate.sample_id)
        same_candidate = previous is not None and previous.candidate == candidate
        if result.static_checks_passed and same_candidate:
            downstream_checks = [
                check for check in previous.checks if check.check.startswith("independent_")
            ]
            result = result.model_copy(
                update={
                    "checks": [*result.checks, *downstream_checks],
                    "independent_reconstruction": previous.independent_reconstruction,
                    "independent_verification": previous.independent_verification,
                    "independent_verifier_status": previous.independent_verifier_status,
                    "human_review_status": previous.human_review_status,
                    "eligible_for_difficulty": previous.eligible_for_difficulty,
                }
            )
        (accepted if result.static_checks_passed else rejected).append(result)

    write_jsonl_atomic(config.paths.verified, accepted)
    write_jsonl_atomic(config.paths.rejected, rejected)
    return accepted, rejected


def _evidence_images(
    candidate: GeneratedCandidate, parsed: ParsedDocument
) -> tuple[list[int], list[Path]]:
    pages = sorted({node.page for node in candidate.task.evidence_graph.nodes})
    by_page = {page.page_number: page.image_path for page in parsed.pages}
    missing = [page for page in pages if page not in by_page or not by_page[page].exists()]
    if missing:
        raise ValueError(f"Missing rendered evidence pages for {candidate.sample_id}: {missing}")
    return pages, [by_page[page] for page in pages]


def _blind_prompt(template: str, candidate: GeneratedCandidate, pages: list[int]) -> str:
    task_payload = {
        "prompt": candidate.task.prompt,
        "document_id": candidate.document_id,
    }
    return template.format(
        page_numbers=json.dumps(pages),
        task_json=json.dumps(task_payload, ensure_ascii=False, indent=2),
    )


def _audit_prompt(
    template: str,
    candidate: GeneratedCandidate,
    reconstruction: IndependentReconstruction,
    pages: list[int],
) -> str:
    audit_payload = {
        "prompt": candidate.task.prompt,
        "gold_answer": candidate.task.gold_answer,
        "claims": [claim.model_dump(mode="json") for claim in candidate.task.claims],
        "derivations": [item.model_dump(mode="json") for item in candidate.task.derivations],
    }
    return template.format(
        page_numbers=json.dumps(pages),
        candidate_json=json.dumps(audit_payload, ensure_ascii=False, indent=2),
        reconstruction_json=reconstruction.model_dump_json(indent=2),
    )


def run_model_verify(
    config: AppConfig,
    reconstruction_prompt_path: Path,
    audit_prompt_path: Path,
    *,
    limit: int | None = None,
    overwrite: bool = False,
) -> list[ValidatedCandidate]:
    """Blindly reconstruct answers, then audit the proposed gold against the source pages."""

    reconstruction_template = reconstruction_prompt_path.read_text(encoding="utf-8")
    audit_template = audit_prompt_path.read_text(encoding="utf-8")
    client = StructuredModelClient(config.models.verifier)
    parsed_by_id: dict[str, ParsedDocument] = {}
    for document_dir in config.paths.parsed.iterdir():
        document_path = document_dir / "document.json"
        if document_path.exists():
            parsed = ParsedDocument.model_validate_json(document_path.read_text(encoding="utf-8"))
            parsed_by_id[parsed.document_id] = parsed

    records = [
        ValidatedCandidate.model_validate(payload) for payload in read_jsonl(config.paths.verified)
    ]
    processed = 0
    for index, record in enumerate(records):
        if not record.static_checks_passed:
            continue
        if not overwrite and record.independent_verifier_status != "not_run":
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        candidate = record.candidate
        parsed = parsed_by_id.get(candidate.document_id)
        if parsed is None:
            raise ValueError(f"Missing parsed document for {candidate.document_id}")
        pages, images = _evidence_images(candidate, parsed)
        log_root = config.paths.logs / "api" / config.run_id / "verify" / candidate.sample_id
        prompt_cache_key = f"{config.run_id}:verify:{candidate.sample_id}:evidence"
        reconstruction: IndependentReconstruction | None = None
        try:
            reconstruction = client.generate(
                prompt=_blind_prompt(reconstruction_template, candidate, pages),
                output_type=IndependentReconstruction,
                image_paths=images,
                prompt_cache_key=prompt_cache_key,
            )
            write_json_atomic(log_root / "reconstruct.json", client.last_call_metadata)
            write_json_atomic(log_root / "reconstruct.output.json", reconstruction)
            decision = client.generate(
                prompt=_audit_prompt(audit_template, candidate, reconstruction, pages),
                output_type=VerificationDecision,
                image_paths=images,
                prompt_cache_key=prompt_cache_key,
            )
            write_json_atomic(log_root / "audit.json", client.last_call_metadata)
            write_json_atomic(log_root / "audit.output.json", decision)
        except Exception as exc:
            if client.last_call_metadata:
                write_json_atomic(log_root / "failed_call.json", client.last_call_metadata)
            failure = {
                "sample_id": candidate.sample_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "classification": "verifier_service_error",
                "counts_as_difficulty": False,
            }
            write_json_atomic(log_root / "service_error.json", failure)
            checks = [
                check for check in record.checks if check.check != "independent_verifier_service"
            ]
            checks.append(
                ValidationCheck(
                    check="independent_verifier_service",
                    passed=False,
                    details=f"{type(exc).__name__}: {exc}",
                )
            )
            records[index] = record.model_copy(
                update={
                    "checks": checks,
                    "independent_reconstruction": reconstruction,
                    "independent_verification": None,
                    "independent_verifier_status": "needs_review",
                    "eligible_for_difficulty": False,
                }
            )
            write_jsonl_atomic(config.paths.verified, records)
            continue

        if (
            decision.requires_human_review
            or not reconstruction.input_complete
            or not decision.input_complete
        ):
            status = "needs_review"
        elif decision.gold_supported and not decision.disputed_claim_ids:
            status = "passed"
        else:
            status = "failed"
        records[index] = record.model_copy(
            update={
                "independent_reconstruction": reconstruction,
                "independent_verification": decision,
                "independent_verifier_status": status,
                "eligible_for_difficulty": status == "passed",
            }
        )
        write_jsonl_atomic(config.paths.verified, records)
    return records
