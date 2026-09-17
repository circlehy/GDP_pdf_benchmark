"""Configuration loading with inheritance and local secret injection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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
    generated: Path
    verified: Path
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
    dpi: int = Field(default=144, ge=72, le=400)
    image_format: str = "png"
    native_text_min_chars_per_page: int = Field(default=40, ge=0)
    enable_ocr_fallback: bool = False


class GenerationConfig(BaseModel):
    candidates_per_document: int = Field(default=3, ge=1, le=20)
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
    api_key_env: str
    reasoning_effort: str | None = None
    max_output_tokens: int = Field(default=8000, ge=1)


class ModelsConfig(BaseModel):
    generator: ModelConfig
    verifier: ModelConfig
    judge: ModelConfig


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
    generation: GenerationConfig
    difficulty: DifficultyConfig
    models: ModelsConfig

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
