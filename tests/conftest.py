from __future__ import annotations

import pytest

from pdf_sft.schemas import GeneratedCandidate


@pytest.fixture
def valid_candidate() -> GeneratedCandidate:
    return GeneratedCandidate.model_validate(
        {
            "sample_id": "pdfsft_test",
            "document_id": "sha256:test",
            "generator_model": "test-generator",
            "generator_prompt_version": "test-v0",
            "task": {
                "prompt": "Determine the adjusted value after applying the controlling exception.",
                "domain": "engineering",
                "primary_evidence_type": "structured_layout",
                "capability_tags": ["cross_page", "calculation"],
                "capability_axes": ["standard_table_parsing", "cross_referencing"],
                "gold_answer": "The adjusted value is 90 after the 10-unit exception.",
                "claims": [
                    {
                        "claim_id": "c1",
                        "text": "The adjusted value is 90.",
                        "supported_by": ["e1", "e2"],
                    }
                ],
                "derivations": [
                    {"result_claim": "c1", "expression": "100 - 10", "inputs": ["e1", "e2"]}
                ],
                "evidence_graph": {
                    "nodes": [
                        {
                            "id": "e1",
                            "page": 1,
                            "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.3},
                            "role": "base_value",
                        },
                        {
                            "id": "e2",
                            "page": 2,
                            "bbox": {"x0": 0.2, "y0": 0.2, "x1": 0.8, "y1": 0.4},
                            "role": "exception",
                        },
                    ],
                    "operations": [
                        {"op": "lookup", "inputs": ["e1"], "output": "v1"},
                        {"op": "exclude", "inputs": ["v1", "e2"], "output": "final"},
                    ],
                    "final_output": "final",
                },
            },
            "rubric": [
                {
                    "criterion_id": "r1",
                    "criterion": "States the adjusted value as 90.",
                    "criterion_type": "primary_intent",
                    "severity": "certain_dealbreaker",
                    "implicitness": "explicit",
                    "subjectiveness": "objective",
                    "failure_mode": "binary",
                    "supported_by": ["c1"],
                },
                {
                    "criterion_id": "r2",
                    "criterion": "Does not ignore the exception on page 2.",
                    "criterion_type": "dodged_bullet",
                    "severity": "certain_dealbreaker",
                    "implicitness": "implicit",
                    "subjectiveness": "objective",
                    "failure_mode": "binary",
                    "supported_by": ["e2"],
                },
            ],
        }
    )
