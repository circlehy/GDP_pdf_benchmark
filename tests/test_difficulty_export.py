from __future__ import annotations

import json
from pathlib import Path

from pdf_sft.config import load_config
from pdf_sft.io import write_json_atomic, write_jsonl_atomic
from pdf_sft.schemas import (
    DifficultyAssessment,
    DifficultyRecord,
    GeneratedCandidate,
    IndependentReconstruction,
    InputProfile,
    ParsedDocument,
    ParsedPage,
    TargetInputPackage,
    TokenAccounting,
)
from pdf_sft.stages.difficulty_gate import structural_difficulty_score
from pdf_sft.stages.export import run_export
from pdf_sft.stages.verify import verify_candidate_static


def test_export_keeps_audit_data_out_of_training_prompt(
    valid_candidate: GeneratedCandidate,
    tmp_path: Path,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml")).model_copy(deep=True)
    config.paths.input_packages = tmp_path / "packages"
    config.paths.hard = tmp_path / "hard.jsonl"
    config.paths.exports = tmp_path / "exports"
    valid_candidate.input_profile = InputProfile.text_only
    valid_candidate.task.supported_input_profiles = [InputProfile.text_only]
    valid_candidate.document_view_id = "sha256:test:full"
    parsed = ParsedDocument(
        document_id="sha256:test",
        parser="test",
        parser_version="1",
        dpi=150,
        page_count=2,
        pages=[
            ParsedPage(
                page_number=number,
                width_points=612,
                height_points=792,
                image_path=tmp_path / f"page_{number}.png",
                extracted_text=f"page {number} evidence",
                extracted_text_chars=15,
                native_text=f"page {number} evidence",
                native_text_chars=15,
                needs_ocr=False,
                blocks=[],
            )
            for number in (1, 2)
        ],
    )
    record = verify_candidate_static(valid_candidate, parsed, config).model_copy(
        update={
            "independent_reconstruction": IndependentReconstruction(
                reconstructed_answer="A substantive but incorrect solver answer.",
                input_complete=True,
                cited_pages=[1, 2],
                uncertainties=[],
                missing_information=[],
            ),
            "independent_verifier_status": "passed",
            "human_review_status": "approved",
            "final_validation_status": "passed",
            "eligible_for_difficulty": True,
        }
    )
    score, label = structural_difficulty_score(record)
    assert 0 <= score <= 1
    assert label in {"hard", "medium", "reject"}
    difficulty = DifficultyRecord(
        validated=record,
        assessment=DifficultyAssessment(
            sample_id=valid_candidate.sample_id,
            structural_score=0.8,
            predicted_label="hard",
            mode="predicted",
            solver_model="test-solver",
            difficulty_verified=False,
            admitted_as_hard=True,
        ),
    )
    write_jsonl_atomic(config.paths.hard, [difficulty])
    package = TargetInputPackage(
        package_id="input-test",
        document_view_id=valid_candidate.document_view_id,
        document_id=valid_candidate.document_id,
        profile=InputProfile.text_only,
        page_numbers=[1, 2],
        document_text="[Page 1]\nbase value 100\n[Page 2]\nexception 10",
        token_accounting=TokenAccounting(
            tokenizer_or_estimator="test",
            document_text_tokens=20,
            page_image_tokens=0,
            question_reserve_tokens=0,
            system_prompt_reserve_tokens=0,
            answer_and_safety_reserve_tokens=10,
            estimated_input_tokens=20,
            context_window_tokens=524288,
            input_utilization=20 / 524288,
            fits_context=True,
        ),
    )
    write_json_atomic(config.paths.input_packages / "text_only" / "test.json", package)

    strict = run_export(config)
    assert strict["training_records"] == 0
    assert strict["rejected_records"] == 1

    pilot_root = tmp_path / "pilot_export"
    pilot = run_export(config, output_root=pilot_root, allow_predicted_difficulty=True)
    assert pilot["training_records"] == 1
    assert not pilot["release_ready"]
    split_path = next(
        path
        for path in (
            pilot_root / "train.jsonl",
            pilot_root / "validation.jsonl",
            pilot_root / "internal_holdout.jsonl",
        )
        if path.read_text(encoding="utf-8").strip()
    )
    training = json.loads(split_path.read_text(encoding="utf-8"))
    user_text = training["messages"][0]["content"][-1]["text"]
    assert valid_candidate.task.prompt in user_text
    assert "base value 100" in user_text
    assert "evidence_graph" not in user_text
    assert "rubric" not in user_text.lower()
    sidecar = json.loads((pilot_root / "sidecar.jsonl").read_text(encoding="utf-8"))
    assert sidecar["task_audit"]["evidence_graph"]["nodes"]
    assert sidecar["task_audit"]["rubric"]
