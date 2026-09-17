from __future__ import annotations

from pathlib import Path

import pytest

from pdf_sft.config import SecurityConfig
from pdf_sft.security import SecurityViolation, ensure_training_path_allowed, validate_source_url


def test_benchmark_path_is_rejected(tmp_path: Path) -> None:
    benchmark = tmp_path / "benchmarks"
    security = SecurityConfig(forbidden_input_roots=[benchmark])
    with pytest.raises(SecurityViolation, match="benchmark path"):
        ensure_training_path_allowed(benchmark / "gdp_pdf" / "source" / "data.parquet", security)


def test_training_path_is_allowed(tmp_path: Path) -> None:
    security = SecurityConfig(forbidden_input_roots=[tmp_path / "benchmarks"])
    assert (
        ensure_training_path_allowed(tmp_path / "raw_pdfs" / "sample.pdf", security)
        == (tmp_path / "raw_pdfs" / "sample.pdf").resolve()
    )


def test_gdp_source_url_is_rejected() -> None:
    security = SecurityConfig(
        forbidden_source_substrings=["huggingface.co/datasets/surgeai/GDP.pdf"]
    )
    with pytest.raises(SecurityViolation, match="Benchmark source"):
        validate_source_url(
            "https://huggingface.co/datasets/surgeai/GDP.pdf/resolve/main/data.parquet",
            security,
        )
