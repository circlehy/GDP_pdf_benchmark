"""Versioned records shared by all pipeline stages."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LicenseStatus(str, Enum):
    approved = "approved"
    rejected = "rejected"
    needs_review = "needs_review"


class LicenseRecord(StrictModel):
    status: LicenseStatus
    license_id: str | None = None
    evidence_url: str | None = None
    third_party_material_status: str = "needs_review"
    review_notes: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def approved_requires_evidence(self) -> LicenseRecord:
        if self.status == LicenseStatus.approved:
            if not self.license_id or not self.evidence_url or not self.review_notes:
                raise ValueError(
                    "Approved documents require license_id, evidence_url, and review_notes"
                )
        return self


class SourceDocument(StrictModel):
    source_url: str
    title: str
    publisher: str
    license_status: LicenseStatus
    license_id: str | None = None
    license_evidence_url: str | None = None
    third_party_material_status: str = "needs_review"
    review_notes: str | None = None


class SourceManifest(StrictModel):
    schema_version: str
    source_id: str
    description: str | None = None
    documents: list[SourceDocument]


class DocumentCandidate(StrictModel):
    schema_version: str = "0.1"
    candidate_id: str
    source_id: str
    source_url: str
    title: str
    publisher: str
    discovered_at: datetime = Field(default_factory=utc_now)
    license: LicenseRecord


class DocumentRecord(StrictModel):
    schema_version: str = "0.1"
    document_id: str
    candidate_id: str
    source_id: str
    source_url: str
    title: str
    publisher: str
    retrieved_at: datetime = Field(default_factory=utc_now)
    content_sha256: str
    size_bytes: int = Field(ge=1)
    pdf_path: Path
    page_count: int | None = Field(default=None, ge=1)
    license: LicenseRecord


class BoundingBox(StrictModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def ordered(self) -> BoundingBox:
        if not (0 <= self.x0 < self.x1 <= 1 and 0 <= self.y0 < self.y1 <= 1):
            raise ValueError("Bounding boxes must be normalized and ordered within [0, 1]")
        return self


class ParsedBlock(StrictModel):
    block_id: str
    kind: str
    bbox: BoundingBox
    text: str = ""
    reading_order: int = Field(ge=0)


class ParsedPage(StrictModel):
    page_number: int = Field(ge=1)
    width_points: float = Field(gt=0)
    height_points: float = Field(gt=0)
    image_path: Path
    extracted_text: str = ""
    extracted_text_chars: int = Field(default=0, ge=0)
    native_text: str
    native_text_chars: int = Field(ge=0)
    needs_ocr: bool
    blocks: list[ParsedBlock]


class ParsedDocument(StrictModel):
    schema_version: str = "0.1"
    document_id: str
    parser: str
    parser_version: str
    renderer: str = "pymupdf"
    renderer_version: str | None = None
    ocr_enabled: bool = False
    ocr_language: str | None = None
    dpi: int
    parsed_at: datetime = Field(default_factory=utc_now)
    page_count: int = Field(ge=1)
    pages: list[ParsedPage]

    @model_validator(mode="after")
    def page_count_matches(self) -> ParsedDocument:
        if self.page_count != len(self.pages):
            raise ValueError("page_count must equal the number of parsed pages")
        return self


class InputProfile(str, Enum):
    text_only = "text_only"
    multimodal = "multimodal"


class DocumentScope(str, Enum):
    full_pdf = "full_pdf"
    bounded = "bounded"


class PageRange(StrictModel):
    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def range_is_ordered(self) -> PageRange:
        if self.end < self.start:
            raise ValueError("page range end must be greater than or equal to start")
        return self


class DocumentView(StrictModel):
    schema_version: str = "0.2"
    document_view_id: str
    document_id: str
    scope: DocumentScope
    source_page_count: int = Field(ge=1)
    included_page_ranges: list[PageRange] = Field(min_length=1)
    included_page_numbers: list[int] = Field(min_length=1)
    truncation_reason: str | None = None
    frozen: bool = True
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def pages_match_scope(self) -> DocumentView:
        if self.included_page_numbers != sorted(set(self.included_page_numbers)):
            raise ValueError("included_page_numbers must be unique and sorted")
        if any(page > self.source_page_count for page in self.included_page_numbers):
            raise ValueError("document view includes a page beyond the source document")
        from_ranges = [
            page
            for page_range in self.included_page_ranges
            for page in range(page_range.start, page_range.end + 1)
        ]
        if from_ranges != self.included_page_numbers:
            raise ValueError("included_page_ranges must exactly match included_page_numbers")
        is_full = self.included_page_numbers == list(range(1, self.source_page_count + 1))
        if self.scope == DocumentScope.full_pdf and not is_full:
            raise ValueError("full_pdf document views must contain every source page")
        if self.scope == DocumentScope.bounded and is_full:
            raise ValueError("bounded document views must omit at least one source page")
        if self.scope == DocumentScope.bounded and not self.truncation_reason:
            raise ValueError("bounded document views require a truncation reason")
        return self


class TokenAccounting(StrictModel):
    schema_version: str = "0.2"
    tokenizer_or_estimator: str
    vision_processor: str | None = None
    exact: bool = False
    text_tokens_exact: bool = False
    image_tokens_exact: bool = False
    document_text_tokens: int = Field(ge=0)
    page_image_tokens: int = Field(ge=0)
    question_reserve_tokens: int = Field(ge=0)
    system_prompt_reserve_tokens: int = Field(ge=0)
    answer_and_safety_reserve_tokens: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    context_window_tokens: int = Field(ge=1)
    input_utilization: float = Field(ge=0)
    fits_context: bool


class TargetInputPackage(StrictModel):
    schema_version: str = "0.2"
    package_id: str
    document_view_id: str
    document_id: str
    profile: InputProfile
    page_image_dpi: int | None = Field(default=None, ge=72)
    page_numbers: list[int] = Field(min_length=1)
    text_empty_page_numbers: list[int] = Field(default_factory=list)
    document_text: str = Field(min_length=1)
    page_image_paths: list[Path] = Field(default_factory=list)
    token_accounting: TokenAccounting
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def profile_payload_is_consistent(self) -> TargetInputPackage:
        if self.page_numbers != sorted(set(self.page_numbers)):
            raise ValueError("page_numbers must be unique and sorted")
        if self.text_empty_page_numbers != sorted(set(self.text_empty_page_numbers)):
            raise ValueError("text_empty_page_numbers must be unique and sorted")
        if not set(self.text_empty_page_numbers).issubset(self.page_numbers):
            raise ValueError("text_empty_page_numbers must be included in page_numbers")
        if self.profile == InputProfile.text_only and self.page_image_paths:
            raise ValueError("text_only packages cannot include page images")
        if self.profile == InputProfile.text_only and self.page_image_dpi is not None:
            raise ValueError("text_only packages cannot define a page image DPI")
        if self.profile == InputProfile.multimodal and len(self.page_image_paths) != len(
            self.page_numbers
        ):
            raise ValueError("multimodal packages require exactly one image per included page")
        if self.profile == InputProfile.multimodal and self.page_image_dpi is None:
            raise ValueError("multimodal packages require a page image DPI")
        return self


class PrimaryEvidenceType(str, Enum):
    visual_spatial = "visual_spatial"
    structured_layout = "structured_layout"
    text_reasoning = "text_reasoning"


class EvidenceRole(str, Enum):
    base_value = "base_value"
    comparison_value = "comparison_value"
    label = "label"
    legend = "legend"
    definition = "definition"
    qualifier = "qualifier"
    exception = "exception"
    exclusion = "exclusion"
    footnote = "footnote"
    threshold = "threshold"
    effective_date = "effective_date"
    superseding_rule = "superseding_rule"
    missing_required_evidence = "missing_required_evidence"


CONTROLLING_ROLES = {
    EvidenceRole.legend,
    EvidenceRole.definition,
    EvidenceRole.qualifier,
    EvidenceRole.exception,
    EvidenceRole.exclusion,
    EvidenceRole.footnote,
    EvidenceRole.effective_date,
    EvidenceRole.superseding_rule,
    EvidenceRole.missing_required_evidence,
}


class EvidenceNode(StrictModel):
    id: str
    page: int = Field(ge=1)
    bbox: BoundingBox
    role: EvidenceRole
    excerpt: str | None = None
    key: bool = True


class EvidenceBBoxRepairSuggestion(StrictModel):
    node_id: str
    page_number: int = Field(ge=1)
    alignment_status: Literal[
        "aligned",
        "misaligned",
        "missing_page",
        "not_checkable_no_excerpt",
        "not_checkable_visual_or_ocr",
    ]
    original_bbox: BoundingBox
    suggested_bbox: BoundingBox | None = None
    original_token_coverage: float | None = Field(default=None, ge=0, le=1)
    suggested_token_coverage: float | None = Field(default=None, ge=0, le=1)
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: Literal["high", "medium", "low", "none"]
    matched_block_ids: list[str] = Field(default_factory=list)
    reason: str


class EvidenceOperation(StrictModel):
    op: Literal[
        "lookup",
        "spatial_bind",
        "normalize",
        "join",
        "compare",
        "calculate",
        "filter",
        "exclude",
        "rank",
        "intersect",
        "aggregate",
        "reconcile",
        "resolve_scope",
        "supersede",
        "determine_support",
    ]
    inputs: list[str] = Field(min_length=1)
    output: str


class EvidenceGraph(StrictModel):
    nodes: list[EvidenceNode] = Field(min_length=1)
    operations: list[EvidenceOperation] = Field(min_length=1)
    final_output: str

    @model_validator(mode="after")
    def graph_is_well_formed(self) -> EvidenceGraph:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Evidence node IDs must be unique")
        available = set(node_ids)
        for operation in self.operations:
            missing = set(operation.inputs) - available
            if missing:
                raise ValueError(f"Operation {operation.op} has unknown inputs: {sorted(missing)}")
            if operation.output in available:
                raise ValueError(f"Duplicate graph output: {operation.output}")
            available.add(operation.output)
        if self.final_output not in available:
            raise ValueError("final_output must be a node or operation output")
        return self


class Claim(StrictModel):
    claim_id: str
    text: str
    supported_by: list[str] = Field(min_length=1)


class Derivation(StrictModel):
    result_claim: str
    expression: str
    inputs: list[str] = Field(min_length=1)


class TaskSpec(StrictModel):
    prompt: str = Field(min_length=20)
    domain: str
    primary_evidence_type: PrimaryEvidenceType
    capability_tags: list[str] = Field(min_length=2)
    capability_axes: list[str] = Field(min_length=2)
    supported_input_profiles: list[InputProfile] = Field(
        default_factory=lambda: [InputProfile.multimodal]
    )
    requires_visual_evidence: bool = False
    gold_answer: str = Field(min_length=1)
    claims: list[Claim] = Field(min_length=1)
    derivations: list[Derivation] = Field(default_factory=list)
    evidence_graph: EvidenceGraph

    @field_validator("capability_tags", "capability_axes")
    @classmethod
    def no_duplicate_tags(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("Capability labels must be unique")
        return values


class RubricCriterion(StrictModel):
    criterion_id: str
    criterion: str
    criterion_type: Literal["primary_intent", "supporting_detail", "dodged_bullet"]
    severity: Literal["certain_dealbreaker", "major", "minor"]
    implicitness: Literal["explicit", "implicit"]
    subjectiveness: Literal["objective", "subjective"]
    failure_mode: Literal["binary", "scalar"]
    supported_by: list[str] = Field(min_length=1)


class GeneratedCandidate(StrictModel):
    schema_version: str = "0.1"
    sample_id: str
    document_id: str
    document_view_id: str | None = None
    input_profile: InputProfile = InputProfile.multimodal
    task: TaskSpec
    rubric: list[RubricCriterion] = Field(min_length=1)
    generator_model: str
    generator_prompt_version: str
    generator_response_id: str | None = None
    generated_at: datetime = Field(default_factory=utc_now)


class GeneratedTaskDraft(StrictModel):
    task: TaskSpec
    rubric: list[RubricCriterion] = Field(min_length=1)


class GenerationBatchDraft(StrictModel):
    candidates: list[GeneratedTaskDraft] = Field(min_length=1)


class VerificationDecision(StrictModel):
    reconstructed_answer: str
    verified_claim_ids: list[str]
    disputed_claim_ids: list[str]
    missing_evidence_node_ids: list[str]
    input_complete: bool
    gold_supported: bool
    requires_human_review: bool
    failure_reasons: list[str]


class IndependentReconstruction(StrictModel):
    reconstructed_answer: str
    input_complete: bool
    cited_pages: list[int]
    uncertainties: list[str]
    missing_information: list[str]


class ValidationCheck(StrictModel):
    check: str
    passed: bool
    details: str | None = None


class AppliedBBoxRepair(StrictModel):
    node_id: str
    page_number: int = Field(ge=1)
    original_bbox: BoundingBox
    accepted_bbox: BoundingBox
    suggestion_confidence: Literal["high", "medium", "low", "none"]
    matched_block_ids: list[str] = Field(default_factory=list)
    reviewer: str = Field(min_length=1)
    notes: str | None = None
    decision_artifact: Path
    applied_at: datetime = Field(default_factory=utc_now)


class AppliedRubricOverride(StrictModel):
    criterion_id: str
    original_criterion: str
    updated_criterion: str
    original_severity: Literal["certain_dealbreaker", "major", "minor"]
    updated_severity: Literal["certain_dealbreaker", "major", "minor"]
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    decision_artifact: Path
    applied_at: datetime = Field(default_factory=utc_now)


class ValidatedCandidate(StrictModel):
    schema_version: str = "0.1"
    candidate: GeneratedCandidate
    structural_gate: StructuralGateResult
    checks: list[ValidationCheck]
    static_checks_passed: bool
    bbox_repairs: list[AppliedBBoxRepair] = Field(default_factory=list)
    rubric_overrides: list[AppliedRubricOverride] = Field(default_factory=list)
    independent_reconstruction: IndependentReconstruction | None = None
    independent_verification: VerificationDecision | None = None
    independent_verifier_model: str | None = None
    independent_verifier_status: Literal["not_run", "passed", "failed", "needs_review"] = "not_run"
    human_review_status: Literal["not_reviewed", "approved", "rejected"] = "not_reviewed"
    final_validation_status: Literal["not_run", "passed", "failed", "needs_review"] = "not_run"
    eligible_for_difficulty: bool = False


class CriterionJudgment(StrictModel):
    criterion_id: str
    passed: bool
    explanation: str


class DifficultyJudgment(StrictModel):
    solver_answer_correct: bool
    primary_intent_passed: bool
    failed_criterion_ids: list[str]
    failure_class: Literal[
        "none",
        "genuine_reasoning_failure",
        "format_or_service_failure",
        "ambiguous_or_broken_task",
    ]
    explanation: str


class DifficultyAssessment(StrictModel):
    schema_version: str = "0.1"
    sample_id: str
    structural_score: float = Field(ge=0, le=1)
    predicted_label: Literal["hard", "medium", "reject"]
    mode: Literal["predicted", "judged"]
    solver_model: str | None = None
    judge_model: str | None = None
    judgment: DifficultyJudgment | None = None
    difficulty_verified: bool = False
    admitted_as_hard: bool = False


class DifficultyRecord(StrictModel):
    validated: ValidatedCandidate
    assessment: DifficultyAssessment


class StructuralGateResult(StrictModel):
    passed: bool
    reasons: list[str]
    features: dict[str, int | bool]


class StageRunManifest(StrictModel):
    schema_version: str = "0.1"
    run_id: str
    stage: str
    status: Literal["running", "completed", "failed"]
    started_at: datetime
    completed_at: datetime | None = None
    config_path: Path
    input_paths: list[Path]
    output_paths: list[Path]
    counters: dict[str, int] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
