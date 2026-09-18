"""Static, non-LLM verification before independent answer reconstruction."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from pdf_sft.config import AppConfig, ModelConfig
from pdf_sft.difficulty import structural_gate
from pdf_sft.io import read_jsonl, write_json_atomic, write_jsonl_atomic
from pdf_sft.llm import StructuredModelClient
from pdf_sft.schemas import (
    BoundingBox,
    DocumentView,
    EvidenceBBoxRepairSuggestion,
    EvidenceNode,
    GeneratedCandidate,
    IndependentReconstruction,
    ParsedDocument,
    ValidatedCandidate,
    ValidationCheck,
    VerificationDecision,
)
from pdf_sft.stages.build_input import load_input_packages

VERIFIER_PROMPT_VERSION = "verifier_v0"
VERIFIER_AUDIT_PROMPT_VERSION = "verifier_audit_v0"


@dataclass(frozen=True)
class AuditImageAttachment:
    path: Path
    kind: str
    page_number: int
    node_ids: tuple[str, ...] = ()
    source_bbox: dict[str, float] | None = None
    crop_bbox: dict[str, float] | None = None
    pixel_width: int | None = None
    pixel_height: int | None = None
    bbox_alignment: dict | None = None

    def prompt_entry(self, index: int) -> dict:
        return {
            "attachment_index": index,
            "kind": self.kind,
            "page_number": self.page_number,
            "node_ids": list(self.node_ids),
            "source_bbox": self.source_bbox,
            "crop_bbox": self.crop_bbox,
            "pixel_width": self.pixel_width,
            "pixel_height": self.pixel_height,
            "bbox_alignment": self.bbox_alignment,
        }

    def log_entry(self, index: int) -> dict:
        return {**self.prompt_entry(index), "artifact_path": str(self.path)}


def model_family(model: str) -> str:
    """Return a stable family label for cross-model independence checks."""

    normalized = model.strip().lower()
    if "qwen" in normalized:
        return "qwen"
    if "glm" in normalized or normalized.startswith("zai-org/"):
        return "glm"
    if "deepseek" in normalized:
        return "deepseek"
    if "kimi" in normalized or "moonshot" in normalized:
        return "kimi"
    return normalized


def verifier_is_independent(generator_model: str, verifier_model: str) -> bool:
    return model_family(generator_model) != model_family(verifier_model)


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
    document_view: DocumentView | None = None,
) -> ValidatedCandidate:
    graph = candidate.task.evidence_graph
    node_ids = {node.id for node in graph.nodes}
    claim_ids = {claim.claim_id for claim in candidate.task.claims}
    rubric_refs = node_ids | claim_ids
    checks: list[ValidationCheck] = []

    checks.append(
        _check(
            "generation_profile_supported",
            candidate.input_profile in candidate.task.supported_input_profiles,
            f"Task does not support generation profile {candidate.input_profile.value}",
        )
    )
    checks.append(
        _check(
            "text_only_visibility",
            not (
                candidate.input_profile.value == "text_only"
                and candidate.task.requires_visual_evidence
            ),
            "A text_only task cannot depend on decisive visual evidence",
        )
    )
    text_empty_pages = {
        page.page_number for page in parsed_document.pages if not page.extracted_text.strip()
    }
    invisible_text_evidence = sorted(
        {
            node.page
            for node in graph.nodes
            if candidate.input_profile.value == "text_only" and node.page in text_empty_pages
        }
    )
    checks.append(
        _check(
            "text_only_evidence_has_extracted_text",
            not invisible_text_evidence,
            f"Text-only evidence points to pages with no extracted text: {invisible_text_evidence}",
        )
    )

    if document_view is not None:
        checks.append(
            _check(
                "document_view_id_matches",
                candidate.document_view_id == document_view.document_view_id,
                "Candidate document_view_id does not match the frozen view",
            )
        )
        out_of_view_pages = sorted(
            {
                node.page
                for node in graph.nodes
                if node.page not in document_view.included_page_numbers
            }
        )
        checks.append(
            _check(
                "evidence_pages_in_document_view",
                not out_of_view_pages,
                f"Evidence pages outside the frozen view: {out_of_view_pages}",
            )
        )

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
    checks.append(
        _check(
            "has_primary_intent",
            any(item.criterion_type == "primary_intent" for item in candidate.rubric),
            "At least one primary-intent rubric criterion is required",
        )
    )
    rubric_claim_references = {
        reference
        for criterion in candidate.rubric
        for reference in criterion.supported_by
        if reference in claim_ids
    }
    uncovered_claims = sorted(claim_ids - rubric_claim_references)
    checks.append(
        _check(
            "rubric_covers_all_gold_claims",
            not uncovered_claims,
            f"Gold claims missing direct rubric coverage: {uncovered_claims}",
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
    views_by_id: dict[str, DocumentView] = {}
    if config.paths.document_views.exists():
        for path in config.paths.document_views.glob("*.json"):
            view = DocumentView.model_validate_json(path.read_text(encoding="utf-8"))
            views_by_id[view.document_id] = view
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
        result = verify_candidate_static(
            candidate, parsed, config, views_by_id.get(candidate.document_id)
        )
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
                    "independent_verifier_model": previous.independent_verifier_model,
                    "independent_verifier_status": previous.independent_verifier_status,
                    "human_review_status": previous.human_review_status,
                    # Independent model agreement is necessary but not sufficient.
                    # A later final-validation stage must also confirm calculations,
                    # evidence locations, and required human review before enabling
                    # difficulty scoring.
                    "eligible_for_difficulty": False,
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
    full_pages: list[int],
    audit_image_pages: list[int],
    audit_image_manifest: list[dict],
) -> str:
    audit_payload = {
        "prompt": candidate.task.prompt,
        "gold_answer": candidate.task.gold_answer,
        "evidence_graph": candidate.task.evidence_graph.model_dump(mode="json"),
        "claims": [claim.model_dump(mode="json") for claim in candidate.task.claims],
        "derivations": [item.model_dump(mode="json") for item in candidate.task.derivations],
    }
    return template.format(
        full_page_numbers=json.dumps(full_pages),
        audit_image_page_numbers=json.dumps(audit_image_pages),
        audit_image_manifest=json.dumps(audit_image_manifest, ensure_ascii=False, indent=2),
        candidate_json=json.dumps(audit_payload, ensure_ascii=False, indent=2),
        reconstruction_json=reconstruction.model_dump_json(indent=2),
    )


def _normalized_bbox(node: EvidenceNode) -> dict[str, float]:
    return {
        "x0": node.bbox.x0,
        "y0": node.bbox.y0,
        "x1": node.bbox.x1,
        "y1": node.bbox.y1,
    }


_ALIGNMENT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "between",
    "by",
    "can",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "which",
    "with",
}


def _alignment_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _ALIGNMENT_STOPWORDS and (len(token) >= 2 or token.isdigit())
    }


def _token_coverage(excerpt: str, visible_text: str) -> float:
    expected = _alignment_tokens(excerpt)
    if not expected:
        return 0.0
    return len(expected & _alignment_tokens(visible_text)) / len(expected)


def _bboxes_intersect(first: dict[str, float], second: dict[str, float]) -> bool:
    return not (
        first["x1"] <= second["x0"]
        or first["x0"] >= second["x1"]
        or first["y1"] <= second["y0"]
        or first["y0"] >= second["y1"]
    )


def evidence_bbox_alignment(
    candidate: GeneratedCandidate,
    parsed: ParsedDocument,
    config: AppConfig,
) -> list[dict]:
    """Compare evidence excerpts with page text and text blocks intersecting each bbox."""

    pages_by_number = {page.page_number: page for page in parsed.pages}
    results: list[dict] = []
    for node in candidate.task.evidence_graph.nodes:
        page = pages_by_number.get(node.page)
        if page is None:
            results.append(
                {
                    "node_id": node.id,
                    "page_number": node.page,
                    "status": "missing_page",
                    "page_token_coverage": 0.0,
                    "bbox_token_coverage": 0.0,
                    "intersecting_block_ids": [],
                }
            )
            continue
        if not node.excerpt:
            results.append(
                {
                    "node_id": node.id,
                    "page_number": node.page,
                    "status": "not_checkable_no_excerpt",
                    "page_token_coverage": None,
                    "bbox_token_coverage": None,
                    "intersecting_block_ids": [],
                }
            )
            continue

        source_bbox = _normalized_bbox(node)
        intersecting_blocks = [
            block
            for block in page.blocks
            if _bboxes_intersect(source_bbox, block.bbox.model_dump(mode="json"))
        ]
        bbox_text = "\n".join(block.text for block in intersecting_blocks if block.text)
        page_coverage = _token_coverage(node.excerpt, page.extracted_text)
        bbox_coverage = _token_coverage(node.excerpt, bbox_text)
        visual_figure_node = candidate.task.requires_visual_evidence and bool(
            re.match(r"\s*(?:figure|fig\.)\s*\d", node.excerpt, flags=re.IGNORECASE)
        )
        page_is_text_match = page_coverage >= config.verification.audit_bbox_min_page_token_coverage
        bbox_is_relative_match = (
            bbox_coverage
            >= page_coverage * config.verification.audit_bbox_min_relative_token_coverage
        )
        if visual_figure_node:
            status = "not_checkable_visual_or_ocr"
        elif page_is_text_match and bbox_is_relative_match:
            status = "aligned"
        elif page_is_text_match:
            status = "misaligned"
        else:
            status = "not_checkable_visual_or_ocr"
        results.append(
            {
                "node_id": node.id,
                "page_number": node.page,
                "status": status,
                "page_token_coverage": round(page_coverage, 4),
                "bbox_token_coverage": round(bbox_coverage, 4),
                "intersecting_block_ids": [block.block_id for block in intersecting_blocks],
            }
        )
    return results


def evidence_bbox_repair_suggestions(
    candidate: GeneratedCandidate,
    parsed: ParsedDocument,
    config: AppConfig,
    alignments: list[dict] | None = None,
) -> list[EvidenceBBoxRepairSuggestion]:
    """Suggest replacement bboxes from LiteParse blocks without mutating the candidate."""

    alignment_by_node = {
        item["node_id"]: item
        for item in (alignments or evidence_bbox_alignment(candidate, parsed, config))
    }
    pages_by_number = {page.page_number: page for page in parsed.pages}
    suggestions: list[EvidenceBBoxRepairSuggestion] = []
    for node in candidate.task.evidence_graph.nodes:
        alignment = alignment_by_node[node.id]
        if alignment["status"] not in {"misaligned", "missing_page"}:
            continue
        original_coverage = alignment["bbox_token_coverage"]
        page = pages_by_number.get(node.page)
        if page is None or not node.excerpt:
            suggestions.append(
                EvidenceBBoxRepairSuggestion(
                    node_id=node.id,
                    page_number=node.page,
                    alignment_status=alignment["status"],
                    original_bbox=node.bbox,
                    original_token_coverage=original_coverage,
                    confidence="none",
                    reason="No page or excerpt is available for deterministic block matching.",
                )
            )
            continue

        blocks = sorted(
            (block for block in page.blocks if block.text.strip()),
            key=lambda block: block.reading_order,
        )
        expected_tokens = _alignment_tokens(node.excerpt)
        best: tuple[float, float, list] | None = None
        max_blocks = config.verification.audit_bbox_repair_max_blocks
        for start in range(len(blocks)):
            for end in range(start + 1, min(len(blocks), start + max_blocks) + 1):
                window = blocks[start:end]
                visible_tokens = _alignment_tokens("\n".join(block.text for block in window))
                overlap = len(expected_tokens & visible_tokens)
                coverage = overlap / len(expected_tokens) if expected_tokens else 0.0
                precision = overlap / len(visible_tokens) if visible_tokens else 0.0
                score = max(0.0, 0.85 * coverage + 0.15 * precision - 0.005 * (len(window) - 1))
                if best is None or (score, coverage, -len(window)) > (
                    best[0],
                    best[1],
                    -len(best[2]),
                ):
                    best = (score, coverage, window)

        if best is None:
            suggestions.append(
                EvidenceBBoxRepairSuggestion(
                    node_id=node.id,
                    page_number=node.page,
                    alignment_status=alignment["status"],
                    original_bbox=node.bbox,
                    original_token_coverage=original_coverage,
                    confidence="none",
                    reason="No non-empty LiteParse blocks are available on the evidence page.",
                )
            )
            continue

        score, coverage, window = best
        improvement = coverage - float(original_coverage or 0.0)
        qualifies = (
            coverage >= config.verification.audit_bbox_repair_min_token_coverage
            and improvement >= config.verification.audit_bbox_repair_min_improvement
        )
        if not qualifies:
            suggestions.append(
                EvidenceBBoxRepairSuggestion(
                    node_id=node.id,
                    page_number=node.page,
                    alignment_status=alignment["status"],
                    original_bbox=node.bbox,
                    original_token_coverage=original_coverage,
                    suggested_token_coverage=round(coverage, 4),
                    score=round(score, 4),
                    confidence="none",
                    matched_block_ids=[block.block_id for block in window],
                    reason=(
                        "Best block window does not meet the configured coverage and improvement "
                        "thresholds; no replacement bbox is proposed."
                    ),
                )
            )
            continue

        suggested_bbox = BoundingBox(
            x0=min(block.bbox.x0 for block in window),
            y0=min(block.bbox.y0 for block in window),
            x1=max(block.bbox.x1 for block in window),
            y1=max(block.bbox.y1 for block in window),
        )
        if coverage >= 0.80 and improvement >= 0.40:
            confidence = "high"
        elif coverage >= 0.65 and improvement >= 0.25:
            confidence = "medium"
        else:
            confidence = "low"
        suggestions.append(
            EvidenceBBoxRepairSuggestion(
                node_id=node.id,
                page_number=node.page,
                alignment_status=alignment["status"],
                original_bbox=node.bbox,
                suggested_bbox=suggested_bbox,
                original_token_coverage=original_coverage,
                suggested_token_coverage=round(coverage, 4),
                score=round(score, 4),
                confidence=confidence,
                matched_block_ids=[block.block_id for block in window],
                reason=(
                    "Suggested bbox is the union of the highest-scoring contiguous LiteParse "
                    "block window. Human acceptance is required before mutation."
                ),
            )
        )
    return suggestions


def _expanded_crop_bbox(
    node: EvidenceNode,
    pixel_width: int,
    pixel_height: int,
    config: AppConfig,
) -> dict[str, float]:
    bbox = node.bbox
    padding = config.verification.audit_crop_padding_ratio
    minimum = config.verification.audit_crop_min_side_pixels
    width = max((bbox.x1 - bbox.x0) * (1 + 2 * padding), minimum / pixel_width)
    height = max((bbox.y1 - bbox.y0) * (1 + 2 * padding), minimum / pixel_height)

    def centered_bounds(center: float, size: float) -> tuple[float, float]:
        size = min(1.0, size)
        low = min(max(0.0, center - size / 2), 1.0 - size)
        return low, low + size

    x0, x1 = centered_bounds((bbox.x0 + bbox.x1) / 2, width)
    y0, y1 = centered_bounds((bbox.y0 + bbox.y1) / 2, height)
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def render_evidence_crop(
    node: EvidenceNode,
    source_path: Path,
    crop_root: Path,
    config: AppConfig,
    index: int,
    alignment: dict,
) -> AuditImageAttachment:
    source_pixmap = pymupdf.Pixmap(str(source_path))
    crop_bbox = _expanded_crop_bbox(node, source_pixmap.width, source_pixmap.height, config)
    digest_payload = {
        "source": str(source_path.resolve()),
        "source_bbox": _normalized_bbox(node),
        "crop_bbox": crop_bbox,
        "source_pixels": [source_pixmap.width, source_pixmap.height],
    }
    digest = hashlib.sha256(json.dumps(digest_payload, sort_keys=True).encode("utf-8")).hexdigest()[
        :12
    ]
    safe_node_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", node.id)
    crop_root.mkdir(parents=True, exist_ok=True)
    output_path = crop_root / (f"{index:03d}_{safe_node_id}_page_{node.page:04d}_{digest}.png")

    with pymupdf.open(str(source_path)) as image_document:
        image_page = image_document[0]
        page_rect = image_page.rect
        clip = pymupdf.Rect(
            crop_bbox["x0"] * page_rect.width,
            crop_bbox["y0"] * page_rect.height,
            crop_bbox["x1"] * page_rect.width,
            crop_bbox["y1"] * page_rect.height,
        )
        matrix = pymupdf.Matrix(
            source_pixmap.width / page_rect.width,
            source_pixmap.height / page_rect.height,
        )
        crop_pixmap = image_page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
        crop_pixmap.save(output_path)

    return AuditImageAttachment(
        path=output_path.resolve(),
        kind="evidence_crop",
        page_number=node.page,
        node_ids=(node.id,),
        source_bbox=_normalized_bbox(node),
        crop_bbox=crop_bbox,
        pixel_width=crop_pixmap.width,
        pixel_height=crop_pixmap.height,
        bbox_alignment=alignment,
    )


def audit_image_package(
    candidate: GeneratedCandidate,
    parsed: ParsedDocument,
    full_pages: list[int],
    full_images: list[Path],
    config: AppConfig,
    crop_root: Path,
) -> tuple[list[int], list[AuditImageAttachment], list[dict]]:
    """Select correctness-audit images without changing the blind reconstruction input."""

    alignments = evidence_bbox_alignment(candidate, parsed, config)
    if candidate.input_profile.value == "text_only":
        return [], [], alignments
    if config.verification.audit_image_scope == "full_document":
        audit_pages, audit_page_images = full_pages, full_images
    else:
        audit_pages, audit_page_images = _evidence_images(candidate, parsed)

    nodes_by_page: dict[int, list[str]] = {}
    for node in candidate.task.evidence_graph.nodes:
        nodes_by_page.setdefault(node.page, []).append(node.id)
    attachments = [
        AuditImageAttachment(
            path=image_path,
            kind="full_page",
            page_number=page_number,
            node_ids=tuple(nodes_by_page.get(page_number, [])),
        )
        for page_number, image_path in zip(audit_pages, audit_page_images, strict=True)
    ]
    alignment_by_node = {item["node_id"]: item for item in alignments}

    if config.verification.audit_include_evidence_crops:
        parsed_images = {page.page_number: page.image_path for page in parsed.pages}
        for index, node in enumerate(candidate.task.evidence_graph.nodes, 1):
            source_path = parsed_images.get(node.page)
            if source_path is None or not source_path.exists():
                raise ValueError(
                    f"Missing crop source page {node.page} for evidence node {node.id}"
                )
            attachments.append(
                render_evidence_crop(
                    node,
                    source_path,
                    crop_root,
                    config,
                    index,
                    alignment_by_node[node.id],
                )
            )
    return audit_pages, attachments, alignments


def select_verifier_model(config: AppConfig, estimated_input_tokens: int) -> ModelConfig | None:
    """Route to the smallest configured verifier whose full request budget fits."""

    candidates = [config.models.verifier, config.models.verifier_long_context]
    for model in candidates:
        if model is not None and model.estimated_request_fits(estimated_input_tokens):
            return model
    return None


def reconstruction_output_errors(
    candidate: GeneratedCandidate,
    reconstruction: IndependentReconstruction,
    metadata: dict,
    config: AppConfig,
) -> list[str]:
    """Detect transport-complete but substantively incomplete blind reconstructions."""

    errors: list[str] = []
    finish_reason = metadata.get("finish_reason")
    if finish_reason not in (None, "stop"):
        errors.append(f"finish_reason={finish_reason}")

    answer = reconstruction.reconstructed_answer.strip()
    minimum = config.verification.minimum_reconstructed_answer_chars
    if len(answer) < minimum:
        errors.append(f"reconstructed_answer has {len(answer)} characters; minimum is {minimum}")

    if config.verification.require_labeled_subquestion_coverage:
        labels = sorted(set(re.findall(r"\(([a-z])\)", candidate.task.prompt, flags=re.IGNORECASE)))
        if len(labels) >= 2:
            normalized_answer = answer.lower()
            missing = [label for label in labels if f"({label.lower()})" not in normalized_answer]
            if missing:
                errors.append(f"missing labeled subquestions: {', '.join(missing)}")
    return errors


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
    clients: dict[str, StructuredModelClient] = {}
    packages_by_profile = {}
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
        profile = candidate.input_profile
        if profile not in packages_by_profile:
            packages_by_profile[profile] = load_input_packages(config, profile)
        package = packages_by_profile[profile].get(candidate.document_id)
        if package is None:
            raise ValueError(f"Missing {profile.value} input package for {candidate.document_id}")
        if candidate.document_view_id != package.document_view_id:
            raise ValueError(
                f"Candidate {candidate.sample_id} does not match frozen input package view"
            )
        estimated_input_tokens = package.token_accounting.estimated_input_tokens
        verifier_config = select_verifier_model(config, estimated_input_tokens)
        selected_for_record = verifier_config or config.models.verifier
        route_check = ValidationCheck(
            check="independent_verifier_context_budget",
            passed=verifier_config is not None,
            details=(
                f"Selected {verifier_config.model}: estimated {estimated_input_tokens} input + "
                f"{verifier_config.max_output_tokens} output <= "
                f"{verifier_config.context_window_tokens} context"
                if verifier_config is not None
                else (
                    f"No configured verifier fits estimated input {estimated_input_tokens}; "
                    f"primary={config.models.verifier.model}/"
                    f"{config.models.verifier.context_window_tokens}, "
                    f"long_context="
                    f"{getattr(config.models.verifier_long_context, 'context_window_tokens', None)}"
                )
            ),
        )
        checks = [
            check for check in record.checks if check.check != "independent_verifier_context_budget"
        ]
        checks.append(route_check)
        record = record.model_copy(update={"checks": checks})
        records[index] = record
        if verifier_config is None:
            records[index] = record.model_copy(
                update={
                    "independent_reconstruction": None,
                    "independent_verification": None,
                    "independent_verifier_model": selected_for_record.model,
                    "independent_verifier_status": "needs_review",
                    "eligible_for_difficulty": False,
                }
            )
            write_jsonl_atomic(config.paths.verified, records)
            continue

        independence_check = ValidationCheck(
            check="independent_verifier_model_family",
            passed=verifier_is_independent(candidate.generator_model, verifier_config.model),
            details=(
                None
                if verifier_is_independent(candidate.generator_model, verifier_config.model)
                else (
                    f"Generator {candidate.generator_model} and verifier "
                    f"{verifier_config.model} are both in the "
                    f"{model_family(candidate.generator_model)} family"
                )
            ),
        )
        checks = [
            check for check in record.checks if check.check != "independent_verifier_model_family"
        ]
        checks.append(independence_check)
        record = record.model_copy(update={"checks": checks})
        records[index] = record
        if not independence_check.passed:
            records[index] = record.model_copy(
                update={
                    "independent_reconstruction": None,
                    "independent_verification": None,
                    "independent_verifier_model": verifier_config.model,
                    "independent_verifier_status": "needs_review",
                    "eligible_for_difficulty": False,
                }
            )
            write_jsonl_atomic(config.paths.verified, records)
            continue
        client = clients.get(verifier_config.model)
        if client is None:
            client = StructuredModelClient(verifier_config)
            clients[verifier_config.model] = client
        pages = package.page_numbers
        images = package.page_image_paths
        log_root = config.paths.logs / "api" / config.run_id / "verify" / candidate.sample_id
        audit_pages, audit_attachments, bbox_alignments = audit_image_package(
            candidate,
            parsed,
            pages,
            images,
            config,
            log_root / "audit_crops",
        )
        bbox_repair_suggestions = evidence_bbox_repair_suggestions(
            candidate, parsed, config, bbox_alignments
        )
        invalid_bbox_ids = [
            item["node_id"]
            for item in bbox_alignments
            if item["status"] in {"misaligned", "missing_page"}
        ]
        bbox_check = ValidationCheck(
            check="independent_evidence_bbox_alignment",
            passed=not invalid_bbox_ids,
            details=(
                None
                if not invalid_bbox_ids
                else f"Misaligned or missing evidence bboxes: {', '.join(invalid_bbox_ids)}"
            ),
        )
        checks = [
            check for check in record.checks if check.check != "independent_evidence_bbox_alignment"
        ]
        checks.append(bbox_check)
        record = record.model_copy(update={"checks": checks})
        records[index] = record
        audit_images = [attachment.path for attachment in audit_attachments]
        audit_prompt_manifest = [
            attachment.prompt_entry(index) for index, attachment in enumerate(audit_attachments, 1)
        ]
        prompt_cache_key = f"{config.run_id}:verify:{candidate.sample_id}:evidence"
        reconstruction: IndependentReconstruction | None = None
        try:
            reconstruction_prompt = (
                _blind_prompt(reconstruction_template, candidate, pages)
                + "\n\nCOMPLETE LITEPARSE DOCUMENT TEXT\n\n"
                + package.document_text
            )
            output_errors: list[str] = []
            for attempt in range(1, config.verification.max_reconstruction_attempts + 1):
                try:
                    reconstruction = client.generate(
                        prompt=reconstruction_prompt,
                        output_type=IndependentReconstruction,
                        image_paths=images,
                        prompt_cache_key=prompt_cache_key,
                    )
                except Exception:
                    if client.last_call_metadata:
                        write_json_atomic(
                            log_root / f"reconstruct.attempt_{attempt}.json",
                            client.last_call_metadata,
                        )
                    if attempt < config.verification.max_reconstruction_attempts:
                        continue
                    raise
                write_json_atomic(
                    log_root / f"reconstruct.attempt_{attempt}.json", client.last_call_metadata
                )
                write_json_atomic(
                    log_root / f"reconstruct.attempt_{attempt}.output.json", reconstruction
                )
                output_errors = reconstruction_output_errors(
                    candidate, reconstruction, client.last_call_metadata, config
                )
                if not output_errors:
                    write_json_atomic(log_root / "reconstruct.json", client.last_call_metadata)
                    write_json_atomic(log_root / "reconstruct.output.json", reconstruction)
                    break
                write_json_atomic(
                    log_root / f"reconstruct.attempt_{attempt}.invalid.json",
                    {"errors": output_errors, "counts_as_difficulty": False},
                )

            assert reconstruction is not None
            checks = [
                check
                for check in record.checks
                if check.check != "independent_reconstruction_output_complete"
            ]
            checks.append(
                ValidationCheck(
                    check="independent_reconstruction_output_complete",
                    passed=not output_errors,
                    details=None if not output_errors else "; ".join(output_errors),
                )
            )
            record = record.model_copy(update={"checks": checks})
            records[index] = record
            if output_errors:
                records[index] = record.model_copy(
                    update={
                        "independent_reconstruction": reconstruction,
                        "independent_verification": None,
                        "independent_verifier_model": verifier_config.model,
                        "independent_verifier_status": "needs_review",
                        "eligible_for_difficulty": False,
                    }
                )
                write_jsonl_atomic(config.paths.verified, records)
                continue

            decision = client.generate(
                prompt=(
                    _audit_prompt(
                        audit_template,
                        candidate,
                        reconstruction,
                        pages,
                        audit_pages,
                        audit_prompt_manifest,
                    )
                    + (
                        "\n\nCOMPLETE LITEPARSE DOCUMENT TEXT\n\n" + package.document_text
                        if config.verification.audit_include_complete_document_text
                        else ""
                    )
                ),
                output_type=VerificationDecision,
                image_paths=audit_images,
                prompt_cache_key=(
                    f"{config.run_id}:verify:{candidate.sample_id}:audit:"
                    f"{config.verification.audit_image_scope}:"
                    f"{','.join(map(str, audit_pages))}:"
                    f"crops={config.verification.audit_include_evidence_crops}"
                ),
            )
            audit_metadata = {
                **client.last_call_metadata,
                "audit_scope": config.verification.audit_image_scope,
                "complete_document_text_included": (
                    config.verification.audit_include_complete_document_text
                ),
                "full_document_page_count": len(pages),
                "attached_audit_page_numbers": audit_pages,
                "audit_full_page_image_dpi": (
                    parsed.dpi
                    if config.verification.audit_image_scope == "evidence_pages"
                    else package.page_image_dpi
                ),
                "audit_crop_source_dpi": (
                    parsed.dpi if config.verification.audit_include_evidence_crops else None
                ),
                "attached_audit_images": [
                    attachment.log_entry(index)
                    for index, attachment in enumerate(audit_attachments, 1)
                ],
                "evidence_bbox_alignment": bbox_alignments,
                "evidence_bbox_repair_suggestions": [
                    suggestion.model_dump(mode="json") for suggestion in bbox_repair_suggestions
                ],
                "evidence_node_ids": [node.id for node in candidate.task.evidence_graph.nodes],
            }
            write_json_atomic(log_root / "audit.json", audit_metadata)
            write_json_atomic(log_root / "audit.output.json", decision)
            audit_finish_reason = audit_metadata.get("finish_reason")
            audit_complete = audit_finish_reason in (None, "stop")
            checks = [
                check
                for check in record.checks
                if check.check != "independent_audit_output_complete"
            ]
            checks.append(
                ValidationCheck(
                    check="independent_audit_output_complete",
                    passed=audit_complete,
                    details=(None if audit_complete else f"finish_reason={audit_finish_reason}"),
                )
            )
            record = record.model_copy(update={"checks": checks})
            records[index] = record
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
                    "independent_verifier_model": verifier_config.model,
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
            or not audit_complete
            or not bbox_check.passed
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
                "independent_verifier_model": verifier_config.model,
                "independent_verifier_status": status,
                "eligible_for_difficulty": False,
            }
        )
        write_jsonl_atomic(config.paths.verified, records)
    return records
