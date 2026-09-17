"""Training/benchmark isolation and source validation."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from pdf_sft.config import SecurityConfig


class SecurityViolation(ValueError):
    pass


def ensure_training_path_allowed(path: Path, security: SecurityConfig) -> Path:
    resolved = path.resolve()
    for forbidden_root in security.forbidden_input_roots:
        if resolved == forbidden_root or resolved.is_relative_to(forbidden_root):
            raise SecurityViolation(f"Training pipeline cannot read benchmark path: {resolved}")
    return resolved


def validate_source_url(url: str, security: SecurityConfig) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in security.allowed_download_schemes:
        raise SecurityViolation(f"Source URL scheme is not allowed: {parsed.scheme!r}")
    normalized = url.casefold()
    for forbidden in security.forbidden_source_substrings:
        if forbidden.casefold() in normalized:
            raise SecurityViolation(f"Benchmark source is forbidden for training ingestion: {url}")
