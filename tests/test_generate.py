from pathlib import Path

from pdf_sft.config import load_config
from pdf_sft.schemas import GenerationBatchDraft, InputProfile
from pdf_sft.stages.generate import (
    _document_selected,
    _hard_target_instructions,
    generation_batch_policy_errors,
    requested_type_schedule,
)


def test_requested_type_schedule_applies_run_level_weights() -> None:
    weights = {
        "visual_spatial": 0.40,
        "structured_layout": 0.45,
        "text_reasoning": 0.15,
    }
    three = requested_type_schedule(weights, 3)
    assert sorted(three) == ["structured_layout", "text_reasoning", "visual_spatial"]

    twenty = requested_type_schedule(weights, 20)
    assert twenty.count("visual_spatial") == 8
    assert twenty.count("structured_layout") == 9
    assert twenty.count("text_reasoning") == 3
    assert all(
        twenty[index : index + 4] != [task_type] * 4
        for task_type in weights
        for index in range(len(twenty) - 3)
    )


def test_hard_generation_policy_and_document_selector() -> None:
    config = load_config(Path("configs/runs/golden_v0_single_pdf_battery.yaml"))
    instructions = _hard_target_instructions(config)

    assert "at least 4 decisive evidence nodes" in instructions
    assert "at least 3 distinct pages" in instructions
    assert "at least 4 dependent operations" in instructions
    assert config.generation.batches_per_document == 2
    assert _document_selected("sha256:abc", {"abc"})
    assert _document_selected("sha256:abc", {"sha256:abc"})
    assert not _document_selected("sha256:abc", {"def"})


def test_generation_policy_catches_missing_claim_coverage_and_weak_hard_graph(
    valid_candidate,
) -> None:
    standard = load_config(Path("configs/runs/smoke_test.yaml"))
    batch = GenerationBatchDraft(
        candidates=[{"task": valid_candidate.task, "rubric": valid_candidate.rubric}]
    )
    assert (
        generation_batch_policy_errors(
            batch,
            standard,
            required_types=["structured_layout"],
            profile=InputProfile.multimodal,
        )
        == []
    )

    broken = batch.model_copy(deep=True)
    broken.candidates[0].rubric[0].supported_by = ["e1"]
    coverage_errors = generation_batch_policy_errors(
        broken,
        standard,
        required_types=["structured_layout"],
        profile=InputProfile.multimodal,
    )
    assert any("rubric misses direct claim refs" in error for error in coverage_errors)

    hard = load_config(Path("configs/runs/golden_v0_single_pdf_battery.yaml"))
    hard_errors = generation_batch_policy_errors(
        batch,
        hard,
        required_types=["structured_layout"],
        profile=InputProfile.multimodal,
    )
    assert any("evidence nodes" in error for error in hard_errors)
    assert any("operations" in error for error in hard_errors)
