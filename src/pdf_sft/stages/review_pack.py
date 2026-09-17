"""Generate a readable, page-linked review pack for validated candidates."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_json_atomic
from pdf_sft.schemas import (
    EvidenceBBoxRepairSuggestion,
    ParsedDocument,
    ValidatedCandidate,
)
from pdf_sft.stages.verify import (
    evidence_bbox_alignment,
    evidence_bbox_repair_suggestions,
    render_evidence_crop,
)


def _safe_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _bbox_text(bbox) -> str:
    return f"({bbox.x0:.4f}, {bbox.y0:.4f}, {bbox.x1:.4f}, {bbox.y1:.4f})"


def _bbox_review_assets(
    record: ValidatedCandidate,
    parsed: ParsedDocument,
    config: AppConfig,
    output_root: Path,
) -> tuple[list[EvidenceBBoxRepairSuggestion], dict[str, dict[str, Path]], Path]:
    candidate = record.candidate
    alignments = evidence_bbox_alignment(candidate, parsed, config)
    suggestions = evidence_bbox_repair_suggestions(candidate, parsed, config, alignments)
    artifact_root = output_root / "artifacts" / candidate.sample_id
    suggestions_path = artifact_root / "bbox_repair_suggestions.json"
    write_json_atomic(
        suggestions_path,
        {
            "schema_version": "0.1",
            "sample_id": candidate.sample_id,
            "document_id": candidate.document_id,
            "generator": "deterministic_liteparse_block_match_v0",
            "mutation_applied": False,
            "suggestions": [item.model_dump(mode="json") for item in suggestions],
        },
    )
    decisions_path = artifact_root / "bbox_repair_decisions.json"
    if suggestions and not decisions_path.exists():
        write_json_atomic(
            decisions_path,
            {
                "schema_version": "0.1",
                "sample_id": candidate.sample_id,
                "mutation_applied": False,
                "decisions": [
                    {
                        "node_id": item.node_id,
                        "decision": "pending",
                        "accepted_bbox": None,
                        "reviewer": None,
                        "notes": None,
                    }
                    for item in suggestions
                ],
            },
        )
    sample_decision_path = artifact_root / "sample_review_decision.json"
    if not sample_decision_path.exists():
        write_json_atomic(
            sample_decision_path,
            {
                "schema_version": "0.1",
                "sample_id": candidate.sample_id,
                "decision": "pending",
                "reviewer": None,
                "reviewer_type": "human",
                "notes": None,
                "checklist": {
                    "question_unambiguous": False,
                    "gold_answer_verified": False,
                    "derivations_verified": False,
                    "rubric_negative_cases_verified": False,
                    "visual_evidence_verified": False,
                    "omitted_page_audit_verified": False,
                },
            },
        )

    nodes_by_id = {node.id: node for node in candidate.task.evidence_graph.nodes}
    pages_by_number = {page.page_number: page for page in parsed.pages}
    alignment_by_node = {item["node_id"]: item for item in alignments}
    crop_assets: dict[str, dict[str, Path]] = {}
    for index, suggestion in enumerate(suggestions, 1):
        node = nodes_by_id[suggestion.node_id]
        page = pages_by_number.get(node.page)
        if page is None or not page.image_path.exists():
            continue
        original = render_evidence_crop(
            node,
            page.image_path,
            artifact_root / "original_crops",
            config,
            index,
            alignment_by_node[node.id],
        )
        crop_assets[node.id] = {"original": original.path}
        if suggestion.suggested_bbox is not None:
            suggested_node = node.model_copy(update={"bbox": suggestion.suggested_bbox})
            suggested = render_evidence_crop(
                suggested_node,
                page.image_path,
                artifact_root / "suggested_crops",
                config,
                index,
                suggestion.model_dump(mode="json"),
            )
            crop_assets[node.id]["suggested"] = suggested.path
    return suggestions, crop_assets, suggestions_path


def _candidate_markdown(
    record: ValidatedCandidate,
    parsed: ParsedDocument,
    pdf_path: Path,
    suggestions: list[EvidenceBBoxRepairSuggestion],
    crop_assets: dict[str, dict[str, Path]],
    suggestions_path: Path,
) -> str:
    candidate = record.candidate
    task = candidate.task
    pages = {page.page_number: page for page in parsed.pages}
    evidence_by_page: dict[int, list] = defaultdict(list)
    for node in task.evidence_graph.nodes:
        evidence_by_page[node.page].append(node)

    lines = [
        f"# {candidate.sample_id}",
        "",
        f"- Domain: `{task.domain}`",
        f"- Primary evidence: `{task.primary_evidence_type.value}`",
        f"- Generator: `{candidate.generator_model}` / `{candidate.generator_prompt_version}`",
        f"- Static checks: `{record.static_checks_passed}`",
        f"- Independent verifier: `{record.independent_verifier_status}`",
        f"- Eligible for difficulty: `{record.eligible_for_difficulty}`",
        f"- Original PDF: [{pdf_path.name}]({pdf_path.resolve()})",
        (
            "- Sample review decision: "
            f"[sample_review_decision.json]({(suggestions_path.parent / 'sample_review_decision.json').resolve()})"
        ),
        "",
        "## Question",
        "",
        task.prompt,
        "",
        "## Gold answer",
        "",
        task.gold_answer,
        "",
        "## Independent reconstruction",
        "",
        (
            record.independent_reconstruction.reconstructed_answer
            if record.independent_reconstruction
            else "_Not run._"
        ),
        "",
        "## Independent audit",
        "",
    ]
    decision = record.independent_verification
    if decision:
        lines.extend(
            [
                f"- Gold supported: `{decision.gold_supported}`",
                f"- Input complete: `{decision.input_complete}`",
                f"- Requires human review: `{decision.requires_human_review}`",
                f"- Verified claims: `{', '.join(decision.verified_claim_ids)}`",
                f"- Disputed claims: `{', '.join(decision.disputed_claim_ids) or 'none'}`",
                f"- Failure reasons: `{'; '.join(decision.failure_reasons) or 'none'}`",
            ]
        )
    else:
        lines.append("_Not run._")

    lines.extend(
        [
            "",
            "## Atomic rubric",
            "",
            "| ID | Type | Severity | Criterion |",
            "|---|---|---|---|",
        ]
    )
    for criterion in candidate.rubric:
        lines.append(
            "| "
            + " | ".join(
                [
                    criterion.criterion_id,
                    criterion.criterion_type,
                    criterion.severity,
                    _safe_cell(criterion.criterion),
                ]
            )
            + " |"
        )

    lines.extend(["", "## Bbox repair review", ""])
    if not suggestions:
        lines.append("_No deterministic bbox repair is currently required._")
    else:
        lines.extend(
            [
                "These are deterministic suggestions only. They do not mutate the evidence graph.",
                "",
                f"- Machine-readable suggestions: [{suggestions_path.name}]({suggestions_path.resolve()})",
                "- Record the human decision in `bbox_repair_decisions.json` beside that file.",
                "",
            ]
        )
        nodes_by_id = {node.id: node for node in task.evidence_graph.nodes}
        claims_by_node: dict[str, list[str]] = defaultdict(list)
        for claim in task.claims:
            for reference in claim.supported_by:
                if reference in nodes_by_id:
                    claims_by_node[reference].append(f"{claim.claim_id}: {claim.text}")
        for suggestion in suggestions:
            node = nodes_by_id[suggestion.node_id]
            original_coverage = (
                "n/a"
                if suggestion.original_token_coverage is None
                else f"{suggestion.original_token_coverage:.4f}"
            )
            suggested_coverage = (
                "n/a"
                if suggestion.suggested_token_coverage is None
                else f"{suggestion.suggested_token_coverage:.4f}"
            )
            lines.extend(
                [
                    f"### Evidence `{suggestion.node_id}` · PDF page {suggestion.page_number}",
                    "",
                    f"- Alignment: `{suggestion.alignment_status}`",
                    f"- Confidence: `{suggestion.confidence}`",
                    f"- Original bbox: `{_bbox_text(suggestion.original_bbox)}`",
                    (
                        f"- Suggested bbox: `{_bbox_text(suggestion.suggested_bbox)}`"
                        if suggestion.suggested_bbox is not None
                        else "- Suggested bbox: _none_"
                    ),
                    f"- Coverage: `{original_coverage}` → `{suggested_coverage}`",
                    f"- Matched blocks: `{', '.join(suggestion.matched_block_ids) or 'none'}`",
                    f"- Reason: {suggestion.reason}",
                    f"- Excerpt: {_safe_cell(node.excerpt or '_No excerpt._')}",
                    "- Dependent claims:",
                ]
            )
            for claim_text in claims_by_node.get(node.id, []):
                lines.append(f"  - {_safe_cell(claim_text)}")
            if not claims_by_node.get(node.id):
                lines.append("  - _No direct claim reference._")
            assets = crop_assets.get(node.id, {})
            if "original" in assets:
                lines.extend(
                    [
                        "",
                        "Original crop:",
                        "",
                        f"![Original crop for {node.id}]({assets['original'].resolve()})",
                    ]
                )
            if "suggested" in assets:
                lines.extend(
                    [
                        "",
                        "Suggested crop:",
                        "",
                        f"![Suggested crop for {node.id}]({assets['suggested'].resolve()})",
                    ]
                )
            lines.extend(
                [
                    "",
                    "- [ ] Accept suggested bbox",
                    "- [ ] Reject or replace with a manual bbox",
                    "",
                ]
            )

    lines.extend(["", "## Evidence pages", ""])
    for page_number in sorted(evidence_by_page):
        page = pages[page_number]
        lines.extend(
            [
                f"### PDF page {page_number}",
                "",
                f"![PDF page {page_number}]({page.image_path.resolve()})",
                "",
            ]
        )
        for node in evidence_by_page[page_number]:
            bbox = node.bbox
            lines.extend(
                [
                    f"- `{node.id}` · role `{node.role.value}` · key `{node.key}` · "
                    f"bbox `({bbox.x0:.3f}, {bbox.y0:.3f}, {bbox.x1:.3f}, {bbox.y1:.3f})`",
                    f"  - {_safe_cell(node.excerpt or '_No excerpt._')}",
                ]
            )
        lines.append("")

    lines.extend(["## Claims and derivations", ""])
    for claim in task.claims:
        lines.append(f"- `{claim.claim_id}`: {claim.text}")
        lines.append(f"  - Supported by: `{', '.join(claim.supported_by)}`")
    if task.derivations:
        lines.extend(["", "### Derivations", ""])
        for derivation in task.derivations:
            lines.append(f"- `{derivation.result_claim}` = `{derivation.expression}`")
            lines.append(f"  - Inputs: `{', '.join(derivation.inputs)}`")
    lines.append("")
    return "\n".join(lines)


def run_review_pack(config: AppConfig, output_root: Path) -> list[Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    parsed_by_id: dict[str, ParsedDocument] = {}
    for directory in config.paths.parsed.iterdir():
        path = directory / "document.json"
        if path.exists():
            parsed = ParsedDocument.model_validate_json(path.read_text(encoding="utf-8"))
            parsed_by_id[parsed.document_id] = parsed
    pdf_by_id = {
        payload["document_id"]: Path(payload["pdf_path"])
        for payload in read_jsonl(config.paths.documents)
    }

    written: list[Path] = []
    index_lines = [f"# Review pack: {config.run_id}", ""]
    for payload in read_jsonl(config.paths.verified):
        record = ValidatedCandidate.model_validate(payload)
        candidate = record.candidate
        parsed = parsed_by_id[candidate.document_id]
        suggestions, crop_assets, suggestions_path = _bbox_review_assets(
            record, parsed, config, output_root
        )
        path = output_root / f"{candidate.sample_id}.md"
        path.write_text(
            _candidate_markdown(
                record,
                parsed,
                pdf_by_id[candidate.document_id],
                suggestions,
                crop_assets,
                suggestions_path,
            ),
            encoding="utf-8",
        )
        written.append(path)
        index_lines.append(
            f"- [{candidate.sample_id}]({path.name}) — "
            f"`{candidate.task.primary_evidence_type.value}` — "
            f"verifier `{record.independent_verifier_status}`"
        )
    index_path = output_root / "README.md"
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return [index_path, *written]
