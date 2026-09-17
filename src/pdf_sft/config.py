"""Configuration loading with inheritance and local secret injection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path, seen: set[Path] | None = None) -> dict[str, Any]:
    path = path.resolve()
    seen = seen or set()
    if path in seen:
        raise ValueError(f"Circular config inheritance involving {path}")
    seen.add(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    parent = payload.pop("extends", None)
    if parent is None:
        return payload
    parent_path = Path(parent)
    if not parent_path.is_absolute():
        cwd_candidate = (Path.cwd() / parent_path).resolve()
        parent_path = cwd_candidate if cwd_candidate.exists() else (path.parent / parent_path)
    return _deep_merge(_load_yaml(parent_path, seen), payload)


def load_env_file(path: Path, *, override: bool = False) -> None:
    """Load a small KEY=VALUE file without ever logging secret values."""

    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid secrets line {line_number} in {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or not key.replace("_", "").isalnum():
            raise ValueError(f"Invalid environment key on line {line_number} in {path}")
        if override or key not in os.environ:
            os.environ[key] = value


class PathConfig(BaseModel):
    discovery: Path
    documents: Path
    raw_pdfs: Path
    parsed: Path
    document_views: Path
    input_packages: Path
    generated: Path
    verified: Path
    repaired: Path
    finalized: Path
    rejected: Path
    hard: Path
    exports: Path
    logs: Path


class SecurityConfig(BaseModel):
    forbidden_input_roots: list[Path] = Field(default_factory=lambda: [Path("benchmarks")])
    forbidden_source_substrings: list[str] = Field(default_factory=list)
    allowed_download_schemes: list[str] = Field(default_factory=lambda: ["https"])
    max_pdf_bytes: int = 200 * 1024 * 1024


class ParseConfig(BaseModel):
    text_extractor: Literal["liteparse"] = "liteparse"
    text_extractor_version: str = "2.5.0"
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    tessdata_path: Path | None = None
    num_workers: int = Field(default=4, ge=1)
    dpi: int = Field(default=150, ge=72, le=400)
    image_format: str = "png"
    native_text_min_chars_per_page: int = Field(default=40, ge=0)


class TargetInputConfig(BaseModel):
    profile: Literal["text_only", "multimodal"] = "multimodal"
    page_image_dpi: int = Field(default=150, ge=72, le=400)
    minimum_page_image_dpi: int = Field(default=72, ge=72, le=400)
    page_image_packing: Literal["single_page"] = "single_page"
    include_all_pages: bool = True
    evidence_graph_in_prompt: bool = False

    @model_validator(mode="after")
    def minimum_dpi_not_above_default(self) -> TargetInputConfig:
        if self.minimum_page_image_dpi > self.page_image_dpi:
            raise ValueError("minimum_page_image_dpi cannot exceed page_image_dpi")
        return self


class ContextBudgetConfig(BaseModel):
    model_context_tokens: int = Field(default=524_288, ge=1)
    target_input_utilization: float = Field(default=0.80, gt=0, lt=1)
    preferred_input_utilization_min: float = Field(default=0.70, gt=0, lt=1)
    preferred_input_utilization_max: float = Field(default=0.85, gt=0, lt=1)
    maximum_input_utilization: float = Field(default=0.90, gt=0, le=1)
    minimum_output_and_safety_reserve_tokens: int = Field(default=32_768, ge=1)
    question_reserve_tokens: int = Field(default=4_096, ge=0)
    system_prompt_reserve_tokens: int = Field(default=2_048, ge=0)
    text_tokenizer_path: Path | None = None
    provisional_chars_per_token: float = Field(default=3.5, gt=0)
    provisional_image_tokens_per_megapixel: int = Field(default=1_200, ge=0)

    @model_validator(mode="after")
    def utilization_limits_are_ordered(self) -> ContextBudgetConfig:
        values = (
            self.preferred_input_utilization_min,
            self.target_input_utilization,
            self.preferred_input_utilization_max,
            self.maximum_input_utilization,
        )
        if list(values) != sorted(values):
            raise ValueError("context utilization limits must be monotonically increasing")
        if self.minimum_output_and_safety_reserve_tokens >= self.model_context_tokens:
            raise ValueError("context reserve must be smaller than the model context")
        return self


class DocumentViewOverrideConfig(BaseModel):
    included_page_ranges: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class DocumentViewConfig(BaseModel):
    overrides: dict[str, DocumentViewOverrideConfig] = Field(default_factory=dict)


class GenerationConfig(BaseModel):
    candidates_per_document: int = Field(default=3, ge=1, le=20)
    max_structure_repair_attempts: int = Field(default=1, ge=0, le=2)
    primary_evidence_type_weights: dict[str, float]

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> GenerationConfig:
        if abs(sum(self.primary_evidence_type_weights.values()) - 1.0) > 1e-6:
            raise ValueError("primary_evidence_type_weights must sum to 1.0")
        return self


class DifficultyConfig(BaseModel):
    minimum_evidence_nodes: int = Field(default=2, ge=2)
    minimum_dependent_operations: int = Field(default=2, ge=2)
    require_non_lookup_operation: bool = True
    require_controlling_evidence: bool = True
    require_tier_2_axis: bool = True
    require_tier_3_axis: bool = True


class ModelConfig(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    base_url_env: str | None = None
    api_key_env: str
    reasoning_effort: str | None = None
    context_window_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int = Field(default=8000, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)

    @model_validator(mode="after")
    def has_unambiguous_base_url(self) -> ModelConfig:
        if self.base_url is not None and self.base_url_env is not None:
            raise ValueError("Set only one of base_url or base_url_env")
        return self

    def estimated_request_fits(self, estimated_input_tokens: int) -> bool:
        return self.context_window_tokens is None or (
            estimated_input_tokens + self.max_output_tokens <= self.context_window_tokens
        )


class ModelsConfig(BaseModel):
    generator: ModelConfig
    verifier: ModelConfig
    verifier_long_context: ModelConfig | None = None
    judge: ModelConfig


class VerificationConfig(BaseModel):
    max_reconstruction_attempts: int = Field(default=2, ge=1, le=3)
    minimum_reconstructed_answer_chars: int = Field(default=256, ge=1)
    require_labeled_subquestion_coverage: bool = True
    audit_image_scope: Literal["full_document", "evidence_pages"] = "evidence_pages"
    audit_include_complete_document_text: bool = True
    audit_include_evidence_crops: bool = True
    audit_crop_padding_ratio: float = Field(default=0.10, ge=0, le=1)
    audit_crop_min_side_pixels: int = Field(default=256, ge=32)
    audit_bbox_min_page_token_coverage: float = Field(default=0.45, ge=0, le=1)
    audit_bbox_min_relative_token_coverage: float = Field(default=0.50, ge=0, le=1)
    audit_bbox_repair_max_blocks: int = Field(default=6, ge=1, le=20)
    audit_bbox_repair_min_token_coverage: float = Field(default=0.60, ge=0, le=1)
    audit_bbox_repair_min_improvement: float = Field(default=0.20, ge=0, le=1)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    run_id: str
    project_root: Path = Path(".")
    source_manifest: Path
    secrets_file: Path | None = None
    paths: PathConfig
    security: SecurityConfig
    parse: ParseConfig
    target_input: TargetInputConfig
    context_budget: ContextBudgetConfig
    document_view: DocumentViewConfig = Field(default_factory=DocumentViewConfig)
    generation: GenerationConfig
    difficulty: DifficultyConfig
    models: ModelsConfig
    verification: VerificationConfig = Field(default_factory=VerificationConfig)

    def resolve_paths(self, cwd: Path | None = None) -> AppConfig:
        cwd = (cwd or Path.cwd()).resolve()
        root = self.project_root
        if not root.is_absolute():
            root = (cwd / root).resolve()
        self.project_root = root
        for name in type(self.paths).model_fields:
            value = getattr(self.paths, name)
            if not value.is_absolute():
                setattr(self.paths, name, (root / value).resolve())
        if not self.source_manifest.is_absolute():
            self.source_manifest = (root / self.source_manifest).resolve()
        if self.secrets_file is not None and not self.secrets_file.is_absolute():
            self.secrets_file = (root / self.secrets_file).resolve()
        if self.parse.tessdata_path is not None and not self.parse.tessdata_path.is_absolute():
            self.parse.tessdata_path = (root / self.parse.tessdata_path).resolve()
        if (
            self.context_budget.text_tokenizer_path is not None
            and not self.context_budget.text_tokenizer_path.is_absolute()
        ):
            self.context_budget.text_tokenizer_path = (
                root / self.context_budget.text_tokenizer_path
            ).resolve()
        self.security.forbidden_input_roots = [
            path if path.is_absolute() else (root / path).resolve()
            for path in self.security.forbidden_input_roots
        ]
        return self


def load_config(path: Path) -> AppConfig:
    payload = _load_yaml(path)
    config = AppConfig.model_validate(payload).resolve_paths()
    if config.secrets_file is not None:
        load_env_file(config.secrets_file)
    return config
