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
    native_text: str
    native_text_chars: int = Field(ge=0)
    needs_ocr: bool
    blocks: list[ParsedBlock]


class ParsedDocument(StrictModel):
    schema_version: str = "0.1"
    document_id: str
    parser: str
    parser_version: str
    dpi: int
    parsed_at: datetime = Field(default_factory=utc_now)
    page_count: int = Field(ge=1)
    pages: list[ParsedPage]

    @model_validator(mode="after")
    def page_count_matches(self) -> ParsedDocument:
        if self.page_count != len(self.pages):
            raise ValueError("page_count must equal the number of parsed pages")
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


class ValidatedCandidate(StrictModel):
    schema_version: str = "0.1"
    candidate: GeneratedCandidate
    structural_gate: StructuralGateResult
    checks: list[ValidationCheck]
    static_checks_passed: bool
    independent_reconstruction: IndependentReconstruction | None = None
    independent_verification: VerificationDecision | None = None
    independent_verifier_status: Literal["not_run", "passed", "failed", "needs_review"] = "not_run"
    human_review_status: Literal["not_reviewed", "approved", "rejected"] = "not_reviewed"
    eligible_for_difficulty: bool = False


class CriterionJudgment(StrictModel):
    criterion_id: str
    passed: bool
    explanation: str


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
