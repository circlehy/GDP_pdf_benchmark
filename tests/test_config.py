from __future__ import annotations

import os
from pathlib import Path

from pdf_sft.config import load_config, load_env_file


def test_smoke_config_loads() -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    assert config.run_id == "smoke_test_v0"
    assert config.generation.primary_evidence_type_weights == {
        "visual_spatial": 0.40,
        "structured_layout": 0.45,
        "text_reasoning": 0.15,
    }
    assert config.security.forbidden_input_roots[0] == config.project_root / "benchmarks"


def test_env_file_does_not_override_existing_value(tmp_path: Path, monkeypatch) -> None:
    key = "PDF_SFT_TEST_SECRET"
    monkeypatch.setenv(key, "from-environment")
    secrets = tmp_path / "secrets.env"
    secrets.write_text(f"{key}=from-file\n", encoding="utf-8")
    load_env_file(secrets)
    assert os.environ[key] == "from-environment"
