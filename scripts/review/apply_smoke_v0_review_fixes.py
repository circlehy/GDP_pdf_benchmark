#!/usr/bin/env python3
"""Apply reviewed, idempotent corrections found by the smoke verifier."""

from __future__ import annotations

from pathlib import Path

from pdf_sft.io import read_jsonl, write_jsonl_atomic

TARGET_SAMPLE = "pdfsft_aab6dfeac21f3ab07c1d"
GENERATED_PATH = Path("data/generated/candidates.jsonl")


def apply_fix(candidate: dict) -> bool:
    if candidate["sample_id"] != TARGET_SAMPLE:
        return False
    task = candidate["task"]
    nodes = task["evidence_graph"]["nodes"]
    if any(node["id"] == "e_ground_data" for node in nodes):
        return False

    old_ending = (
        "Before applying it, assess the actual mission environment, application, and lifetime, "
        "as required by the radiation-likelihood summary (PDF pp. 64, 69)."
    )
    new_ending = (
        "Before applying it, confirm that suitable ground-based TID/TNID/DDD data exist for the "
        "actual device parameter or radiation-sensitive application (PDF p. 64), and assess the "
        "specific mission environment, application, and lifetime (PDF p. 69)."
    )
    if old_ending not in task["gold_answer"]:
        raise ValueError("Expected pre-review gold ending was not found")
    task["gold_answer"] = task["gold_answer"].replace(old_ending, new_ending)

    nodes.append(
        {
            "id": "e_ground_data",
            "page": 64,
            "bbox": {"x0": 0.105, "y0": 0.765, "x1": 0.895, "y1": 0.855},
            "role": "qualifier",
            "excerpt": (
                "The simplified transistor example can determine success for a device parameter "
                "or sensitive application if ground-based TID/TNID/DDD data exist."
            ),
            "key": True,
        }
    )

    claim = next(item for item in task["claims"] if item["claim_id"] == "c7")
    claim["text"] = (
        "The plotted result is an SFT2907A example; applying the approach requires suitable "
        "ground-based TID/TNID/DDD data for the actual device parameter or radiation-sensitive "
        "application, and an actual radiation-likelihood determination must use the specific "
        "mission environment, application, and lifetime."
    )
    claim["supported_by"] = ["e_chart", "e_ground_data", "e_mission_scope"]

    operation = next(
        item
        for item in task["evidence_graph"]["operations"]
        if item["output"] == "illustrative_result_and_mission_specific_applicability"
    )
    operation["inputs"] = ["e_chart", "e_ground_data", "e_mission_scope"]

    criterion = next(item for item in candidate["rubric"] if item["criterion_id"] == "r10")
    criterion["criterion"] = (
        "States both applicability gates: suitable ground-based TID/TNID/DDD data must exist for "
        "the actual device parameter or radiation-sensitive application, and the determination "
        "must use the specific mission environment, application, and lifetime."
    )
    citation = next(item for item in candidate["rubric"] if item["criterion_id"] == "r12")
    citation["supported_by"] = [
        "e_chart",
        "e_ground_data",
        "e_cold_spare",
        "e_mission_scope",
    ]
    candidate["generator_prompt_version"] = "generator_v0+manual_review_fix_001"
    return True


def main() -> None:
    records = list(read_jsonl(GENERATED_PATH))
    changed = sum(apply_fix(candidate) for candidate in records)
    if changed > 1:
        raise ValueError(f"Expected at most one correction, got {changed}")
    write_jsonl_atomic(GENERATED_PATH, records)
    print(f"Applied {changed} reviewed correction(s)")


if __name__ == "__main__":
    main()
