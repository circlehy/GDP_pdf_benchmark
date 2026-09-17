from __future__ import annotations

import os
from pathlib import Path

from pdf_sft.config import TargetInputConfig, load_config, load_env_file
from pdf_sft.stages.verify import select_verifier_model


def test_target_input_defaults_to_multimodal() -> None:
    assert TargetInputConfig().profile == "multimodal"


def test_smoke_config_loads() -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    assert config.run_id == "smoke_test_v0"
    assert config.target_input.profile == "multimodal"
    assert config.generation.primary_evidence_type_weights == {
        "visual_spatial": 0.40,
        "structured_layout": 0.45,
        "text_reasoning": 0.15,
    }
    assert config.generation.max_structure_repair_attempts == 1
    assert config.verification.audit_image_scope == "evidence_pages"
    assert config.verification.audit_include_complete_document_text
    assert config.verification.audit_include_evidence_crops
    assert config.verification.audit_crop_padding_ratio == 0.10
    assert config.verification.audit_crop_min_side_pixels == 256
    assert config.verification.audit_bbox_min_page_token_coverage == 0.45
    assert config.verification.audit_bbox_min_relative_token_coverage == 0.50
    assert config.verification.audit_bbox_repair_max_blocks == 6
    assert config.verification.audit_bbox_repair_min_token_coverage == 0.60
    assert config.verification.audit_bbox_repair_min_improvement == 0.20
    assert config.security.forbidden_input_roots[0] == config.project_root / "benchmarks"


def test_local_cross_model_configs_freeze_opposite_families() -> None:
    glm_run = load_config(Path("configs/runs/local_glm_generate_qwen_verify.yaml"))
    assert glm_run.models.generator.model == "zai-org/GLM-5.3-Flash"
    assert glm_run.models.generator.reasoning_effort == "high"
    assert glm_run.models.generator.max_output_tokens == 24576
    assert glm_run.models.generator.context_window_tokens == 1048576
    assert glm_run.models.verifier.model == "Qwen3.8-27B"
    assert glm_run.models.verifier.reasoning_effort == "xhigh"
    assert glm_run.models.verifier.context_window_tokens == 262144
    assert glm_run.models.verifier.estimated_request_fits(96827)
    assert not glm_run.models.verifier.estimated_request_fits(287184)
    assert glm_run.models.verifier_long_context is not None
    assert glm_run.models.verifier_long_context.model == "Qwen3.8-27B-512K"
    assert glm_run.models.verifier_long_context.max_output_tokens == 32768
    assert select_verifier_model(glm_run, 96827) == glm_run.models.verifier
    assert select_verifier_model(glm_run, 287184) == glm_run.models.verifier_long_context
    assert select_verifier_model(glm_run, 500000) is None

    qwen_run = load_config(Path("configs/runs/local_qwen_generate_glm_verify.yaml"))
    assert qwen_run.models.generator.model == "Qwen3.8-27B"
    assert qwen_run.models.generator.max_output_tokens == 32768
    assert qwen_run.models.verifier.model == "zai-org/GLM-5.3-Flash"
    assert qwen_run.models.verifier.max_output_tokens == 24576

    qwen512_run = load_config(Path("configs/runs/local_glm_generate_qwen512_verify.yaml"))
    assert qwen512_run.models.verifier.model == "Qwen3.8-27B-512K"
    assert qwen512_run.models.verifier.context_window_tokens == 524288
    assert qwen512_run.models.verifier_long_context is None

    initial_run = load_config(Path("configs/runs/initial_pipeline_v1.yaml"))
    assert initial_run.run_id == "initial_pipeline_v1"
    assert initial_run.generation.candidates_per_document == 1
    assert initial_run.paths.generated.name == "generated.jsonl"
    assert initial_run.context_budget.text_tokenizer_path == Path(
        "/mnt/weka/shrd/k2m/mikhail.yurochkin/ilikejson-250k-tokenizer"
    )
    assert "initial_pipeline_v1" in initial_run.paths.input_packages.parts


def test_env_file_does_not_override_existing_value(tmp_path: Path, monkeypatch) -> None:
    key = "PDF_SFT_TEST_SECRET"
    monkeypatch.setenv(key, "from-environment")
    secrets = tmp_path / "secrets.env"
    secrets.write_text(f"{key}=from-file\n", encoding="utf-8")
    load_env_file(secrets)
    assert os.environ[key] == "from-environment"
