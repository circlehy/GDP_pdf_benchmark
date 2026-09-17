from __future__ import annotations

from copy import deepcopy

from pdf_sft.config import DifficultyConfig
from pdf_sft.difficulty import structural_gate
from pdf_sft.schemas import GeneratedCandidate


def test_valid_multistep_candidate_passes(valid_candidate: GeneratedCandidate) -> None:
    result = structural_gate(valid_candidate, DifficultyConfig())
    assert result.passed
    assert result.reasons == []
    assert result.features["evidence_node_count"] == 2
    assert result.features["non_lookup_operation_count"] == 1


def test_lookup_only_candidate_fails(valid_candidate: GeneratedCandidate) -> None:
    payload = valid_candidate.model_dump(mode="json")
    payload["task"]["evidence_graph"]["operations"] = [
        {"op": "lookup", "inputs": ["e1", "e2"], "output": "final"},
        {"op": "lookup", "inputs": ["final"], "output": "final_2"},
    ]
    payload["task"]["evidence_graph"]["final_output"] = "final_2"
    candidate = GeneratedCandidate.model_validate(payload)
    result = structural_gate(candidate, DifficultyConfig())
    assert not result.passed
    assert "lookup_only" in result.reasons


def test_disconnected_key_evidence_fails(valid_candidate: GeneratedCandidate) -> None:
    payload = deepcopy(valid_candidate.model_dump(mode="json"))
    payload["task"]["evidence_graph"]["operations"] = [
        {"op": "lookup", "inputs": ["e1"], "output": "v1"},
        {"op": "calculate", "inputs": ["v1"], "output": "final"},
    ]
    candidate = GeneratedCandidate.model_validate(payload)
    result = structural_gate(candidate, DifficultyConfig())
    assert not result.passed
    assert "key_evidence_not_connected_to_final_output" in result.reasons
