"""Deterministic GDP-like structural admission checks."""

from __future__ import annotations

from pdf_sft.config import DifficultyConfig
from pdf_sft.schemas import (
    CONTROLLING_ROLES,
    EvidenceGraph,
    GeneratedCandidate,
    StructuralGateResult,
)

TIER_2_AXES = {
    "semantic_reading_flow",
    "typographic_hierarchy",
    "standard_table_parsing",
    "chart_multimodal_interpretation",
}

TIER_3_AXES = {
    "complex_multi_page_tables",
    "cross_referencing",
    "artifact_noise",
    "unsupported_queries",
}


def _nodes_reaching_final(graph: EvidenceGraph) -> set[str]:
    producer = {operation.output: operation.inputs for operation in graph.operations}
    required: set[str] = set()
    pending = [graph.final_output]
    while pending:
        item = pending.pop()
        if item in required:
            continue
        required.add(item)
        pending.extend(producer.get(item, []))
    return {node.id for node in graph.nodes if node.id in required}


def structural_gate(
    candidate: GeneratedCandidate, config: DifficultyConfig
) -> StructuralGateResult:
    graph = candidate.task.evidence_graph
    evidence_nodes = len(graph.nodes)
    operation_count = len(graph.operations)
    non_lookup_count = sum(operation.op != "lookup" for operation in graph.operations)
    controlling_count = sum(node.role in CONTROLLING_ROLES for node in graph.nodes)
    tier_2_count = len(set(candidate.task.capability_axes) & TIER_2_AXES)
    tier_3_count = len(set(candidate.task.capability_axes) & TIER_3_AXES)
    key_node_ids = {node.id for node in graph.nodes if node.key}
    reaching_node_ids = _nodes_reaching_final(graph)
    disconnected_key_nodes = key_node_ids - reaching_node_ids

    reasons: list[str] = []
    if evidence_nodes < config.minimum_evidence_nodes:
        reasons.append("insufficient_evidence_nodes")
    if operation_count < config.minimum_dependent_operations:
        reasons.append("insufficient_dependent_operations")
    if config.require_non_lookup_operation and non_lookup_count == 0:
        reasons.append("lookup_only")
    if config.require_controlling_evidence and controlling_count == 0:
        reasons.append("missing_controlling_evidence")
    if config.require_tier_2_axis and tier_2_count == 0:
        reasons.append("missing_tier_2_axis")
    if config.require_tier_3_axis and tier_3_count == 0:
        reasons.append("missing_tier_3_axis")
    if disconnected_key_nodes:
        reasons.append("key_evidence_not_connected_to_final_output")

    return StructuralGateResult(
        passed=not reasons,
        reasons=reasons,
        features={
            "evidence_node_count": evidence_nodes,
            "dependent_operation_count": operation_count,
            "non_lookup_operation_count": non_lookup_count,
            "controlling_evidence_count": controlling_count,
            "tier_2_axis_count": tier_2_count,
            "tier_3_axis_count": tier_3_count,
            "all_key_nodes_reach_final": not disconnected_key_nodes,
        },
    )
