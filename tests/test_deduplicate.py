from pathlib import Path

from pdf_sft.config import load_config
from pdf_sft.io import write_jsonl_atomic
from pdf_sft.schemas import PrimaryEvidenceType, StructuralGateResult, ValidatedCandidate
from pdf_sft.stages.deduplicate import run_deduplicate


def _validated(candidate) -> ValidatedCandidate:
    return ValidatedCandidate(
        candidate=candidate,
        structural_gate=StructuralGateResult(
            passed=True,
            reasons=[],
            features={
                "evidence_node_count": 2,
                "dependent_operation_count": 2,
                "distinct_page_count": 2,
                "controlling_evidence_count": 1,
                "tier_2_axis_count": 1,
                "tier_3_axis_count": 1,
            },
        ),
        checks=[],
        static_checks_passed=True,
    )


def test_deduplicate_rejects_overlapping_task_and_keeps_distinct_type(
    valid_candidate,
    tmp_path: Path,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml")).model_copy(deep=True)
    config.paths.verified = tmp_path / "verified.jsonl"
    config.paths.deduplicated = tmp_path / "deduplicated.jsonl"

    first = valid_candidate.model_copy(deep=True)
    first.sample_id = "first"
    duplicate = valid_candidate.model_copy(deep=True)
    duplicate.sample_id = "duplicate"
    duplicate.task.prompt = first.task.prompt + " Please provide the result."

    distinct = valid_candidate.model_copy(deep=True)
    distinct.sample_id = "distinct"
    distinct.task.prompt = "Compare a different visual trend across two later figures and decide."
    distinct.task.primary_evidence_type = PrimaryEvidenceType.visual_spatial
    for node in distinct.task.evidence_graph.nodes:
        node.page += 2

    write_jsonl_atomic(
        config.paths.verified,
        [_validated(first), _validated(duplicate), _validated(distinct)],
    )

    selected, report = run_deduplicate(config)

    selected_ids = {record.candidate.sample_id for record in selected}
    assert "distinct" in selected_ids
    assert len(selected_ids & {"first", "duplicate"}) == 1
    assert report["rejected"] == 1
    assert len(report["selected_candidates"]) == 2
    assert report["rejections"][0]["sample_id"] in {"first", "duplicate"}
    assert "evidence_region_overlap" in report["rejections"][0]["reasons"]
