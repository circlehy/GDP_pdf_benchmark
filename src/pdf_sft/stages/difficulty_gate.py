"""Difficulty admission after all correctness and human-review gates pass."""

from __future__ import annotations

import json
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_json_atomic, write_jsonl_atomic
from pdf_sft.llm import StructuredModelClient
from pdf_sft.schemas import (
    CONTROLLING_ROLES,
    DifficultyAssessment,
    DifficultyJudgment,
    DifficultyRecord,
    ValidatedCandidate,
)


def structural_difficulty_score(record: ValidatedCandidate) -> tuple[float, str]:
    candidate = record.candidate
    graph = candidate.task.evidence_graph
    evidence_score = min(len(graph.nodes), 6) / 6
    operation_score = min(len(graph.operations), 6) / 6
    page_score = min(len({node.page for node in graph.nodes}), 4) / 4
    controlling_score = min(sum(node.role in CONTROLLING_ROLES for node in graph.nodes), 2) / 2
    tier_score = (
        min(
            record.structural_gate.features.get("tier_2_axis_count", 0)
            + record.structural_gate.features.get("tier_3_axis_count", 0),
            4,
        )
        / 4
    )
    visual_score = 1.0 if candidate.task.requires_visual_evidence else 0.0
    score = (
        0.20 * evidence_score
        + 0.20 * operation_score
        + 0.20 * page_score
        + 0.15 * controlling_score
        + 0.15 * tier_score
        + 0.10 * visual_score
    )
    score = round(score, 4)
    label = "hard" if score >= 0.65 else "medium" if score >= 0.45 else "reject"
    return score, label


def _judge_prompt(template: str, record: ValidatedCandidate) -> str:
    candidate = record.candidate
    payload = {
        "prompt": candidate.task.prompt,
        "gold_answer": candidate.task.gold_answer,
        "rubric": [criterion.model_dump(mode="json") for criterion in candidate.rubric],
    }
    solver_answer = (
        record.independent_reconstruction.reconstructed_answer
        if record.independent_reconstruction is not None
        else ""
    )
    return template.format(
        task_payload=json.dumps(payload, ensure_ascii=False, indent=2),
        solver_answer=solver_answer,
    )


def run_difficulty_gate(
    config: AppConfig,
    prompt_path: Path,
    *,
    mode: str = "predicted",
    input_path: Path | None = None,
    output_path: Path | None = None,
    limit: int | None = None,
) -> list[DifficultyRecord]:
    """Score only final-passed samples; never reinterpret broken inputs as difficulty."""

    if mode not in {"predicted", "judged"}:
        raise ValueError(f"Unsupported difficulty mode {mode!r}")
    input_path = (input_path or config.paths.finalized).resolve()
    output_path = (output_path or config.paths.hard).resolve()
    template = prompt_path.read_text(encoding="utf-8")
    client = StructuredModelClient(config.models.judge) if mode == "judged" else None
    results: list[DifficultyRecord] = []
    processed = 0
    for payload in read_jsonl(input_path):
        record = ValidatedCandidate.model_validate(payload)
        if not record.eligible_for_difficulty or record.final_validation_status != "passed":
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        score, predicted_label = structural_difficulty_score(record)
        judgment = None
        verified = False
        admitted = predicted_label == "hard"
        if mode == "judged":
            if record.independent_reconstruction is None:
                admitted = False
            else:
                try:
                    assert client is not None
                    judgment = client.generate(
                        prompt=_judge_prompt(template, record),
                        output_type=DifficultyJudgment,
                    )
                    log_root = (
                        config.paths.logs
                        / "api"
                        / config.run_id
                        / "difficulty"
                        / record.candidate.sample_id
                    )
                    write_json_atomic(log_root / "judge.json", client.last_call_metadata)
                    write_json_atomic(log_root / "judge.output.json", judgment)
                    verified = True
                    admitted = (
                        predicted_label == "hard"
                        and not judgment.solver_answer_correct
                        and judgment.failure_class == "genuine_reasoning_failure"
                    )
                except Exception as exc:
                    log_root = (
                        config.paths.logs
                        / "api"
                        / config.run_id
                        / "difficulty"
                        / record.candidate.sample_id
                    )
                    write_json_atomic(
                        log_root / "service_error.json",
                        {
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                            "counts_as_difficulty": False,
                        },
                    )
                    admitted = False
        assessment = DifficultyAssessment(
            sample_id=record.candidate.sample_id,
            structural_score=score,
            predicted_label=predicted_label,
            mode=mode,
            solver_model=record.independent_verifier_model,
            judge_model=config.models.judge.model if mode == "judged" else None,
            judgment=judgment,
            difficulty_verified=verified,
            admitted_as_hard=admitted,
        )
        results.append(DifficultyRecord(validated=record, assessment=assessment))
    write_jsonl_atomic(output_path, results)
    return results
