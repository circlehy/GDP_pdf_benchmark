"""Select diverse candidates before expensive independent model verification."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_json_atomic, write_jsonl_atomic
from pdf_sft.schemas import BoundingBox, ValidatedCandidate
from pdf_sft.stages.difficulty_gate import structural_difficulty_score


def _jaccard(left: set, right: set) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _bbox_iou(left: BoundingBox, right: BoundingBox) -> float:
    intersection_width = max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))
    intersection_height = max(0.0, min(left.y1, right.y1) - max(left.y0, right.y0))
    intersection = intersection_width * intersection_height
    left_area = (left.x1 - left.x0) * (left.y1 - left.y0)
    right_area = (right.x1 - right.x0) * (right.y1 - right.y0)
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _evidence_region_jaccard(
    left: ValidatedCandidate,
    right: ValidatedCandidate,
    *,
    bbox_match_iou: float,
) -> float:
    left_nodes = left.candidate.task.evidence_graph.nodes
    right_nodes = right.candidate.task.evidence_graph.nodes
    unmatched_right = set(range(len(right_nodes)))
    matches = 0
    for left_node in left_nodes:
        best_index = None
        best_iou = 0.0
        for index in unmatched_right:
            right_node = right_nodes[index]
            if left_node.page != right_node.page:
                continue
            overlap = _bbox_iou(left_node.bbox, right_node.bbox)
            if overlap > best_iou:
                best_iou = overlap
                best_index = index
        if best_index is not None and best_iou >= bbox_match_iou:
            matches += 1
            unmatched_right.remove(best_index)
    union = len(left_nodes) + len(right_nodes) - matches
    return matches / union if union else 1.0


def _prompt_tokens(record: ValidatedCandidate) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", record.candidate.task.prompt.lower()))


def candidate_similarity(
    left: ValidatedCandidate,
    right: ValidatedCandidate,
    config: AppConfig,
) -> dict[str, float]:
    left_graph = left.candidate.task.evidence_graph
    right_graph = right.candidate.task.evidence_graph
    page_jaccard = _jaccard(
        {node.page for node in left_graph.nodes},
        {node.page for node in right_graph.nodes},
    )
    operation_jaccard = _jaccard(
        {operation.op for operation in left_graph.operations},
        {operation.op for operation in right_graph.operations},
    )
    return {
        "evidence_page_jaccard": round(page_jaccard, 4),
        "evidence_region_jaccard": round(
            _evidence_region_jaccard(
                left,
                right,
                bbox_match_iou=config.deduplication.bbox_match_iou,
            ),
            4,
        ),
        "operation_jaccard": round(operation_jaccard, 4),
        "prompt_token_jaccard": round(_jaccard(_prompt_tokens(left), _prompt_tokens(right)), 4),
    }


def duplicate_reasons(metrics: dict[str, float], config: AppConfig) -> list[str]:
    policy = config.deduplication
    reasons: list[str] = []
    if metrics["evidence_region_jaccard"] >= policy.max_evidence_region_jaccard:
        reasons.append("evidence_region_overlap")
    if metrics["prompt_token_jaccard"] >= policy.max_prompt_token_jaccard:
        reasons.append("prompt_rephrase")
    if (
        metrics["evidence_page_jaccard"] >= policy.max_evidence_page_jaccard
        and metrics["operation_jaccard"] >= policy.max_page_operation_jaccard
    ):
        reasons.append("same_pages_and_reasoning_path")
    return reasons


def run_deduplicate(
    config: AppConfig,
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> tuple[list[ValidatedCandidate], dict]:
    input_path = (input_path or config.paths.verified).resolve()
    output_path = (output_path or config.paths.deduplicated).resolve()
    by_document: dict[str, list[ValidatedCandidate]] = defaultdict(list)
    for payload in read_jsonl(input_path):
        record = ValidatedCandidate.model_validate(payload)
        if record.static_checks_passed:
            by_document[record.candidate.document_id].append(record)

    selected: list[ValidatedCandidate] = []
    rejected: list[dict] = []
    for document_id, candidates in sorted(by_document.items()):
        remaining = sorted(
            candidates,
            key=lambda record: (
                -structural_difficulty_score(record)[0],
                record.candidate.sample_id,
            ),
        )
        selected_for_document: list[ValidatedCandidate] = []
        selected_types: set[str] = set()
        while (
            remaining and len(selected_for_document) < config.deduplication.max_tasks_per_document
        ):
            remaining.sort(
                key=lambda record: (
                    record.candidate.task.primary_evidence_type.value in selected_types,
                    -structural_difficulty_score(record)[0],
                    record.candidate.sample_id,
                )
            )
            candidate = remaining.pop(0)
            duplicate = None
            for retained in selected_for_document:
                metrics = candidate_similarity(candidate, retained, config)
                reasons = duplicate_reasons(metrics, config)
                if reasons:
                    duplicate = {
                        "sample_id": candidate.candidate.sample_id,
                        "document_id": document_id,
                        "status": "rejected_duplicate",
                        "matched_sample_id": retained.candidate.sample_id,
                        "reasons": reasons,
                        "metrics": metrics,
                    }
                    break
            if duplicate is not None:
                rejected.append(duplicate)
                continue
            selected_for_document.append(candidate)
            selected_types.add(candidate.candidate.task.primary_evidence_type.value)

        for candidate in remaining:
            rejected.append(
                {
                    "sample_id": candidate.candidate.sample_id,
                    "document_id": document_id,
                    "status": "rejected_document_cap",
                    "reasons": ["max_tasks_per_document"],
                }
            )
        selected.extend(selected_for_document)

    write_jsonl_atomic(output_path, selected)
    report = {
        "schema_version": "0.1",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "selected": len(selected),
        "rejected": len(rejected),
        "max_tasks_per_document": config.deduplication.max_tasks_per_document,
        "selected_sample_ids": [record.candidate.sample_id for record in selected],
        "selected_candidates": [
            {
                "sample_id": record.candidate.sample_id,
                "document_id": record.candidate.document_id,
                "primary_evidence_type": record.candidate.task.primary_evidence_type.value,
                "structural_score": structural_difficulty_score(record)[0],
                "predicted_label": structural_difficulty_score(record)[1],
            }
            for record in selected
        ],
        "rejections": rejected,
    }
    write_json_atomic(output_path.with_suffix(".report.json"), report)
    return selected, report
