"""Generate a readable, page-linked review pack for validated candidates."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl
from pdf_sft.schemas import ParsedDocument, ValidatedCandidate


def _safe_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _candidate_markdown(
    record: ValidatedCandidate,
    parsed: ParsedDocument,
    pdf_path: Path,
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
        lines.append(
            f"- `{claim.claim_id}`: {claim.text}  \n  Supported by: `{', '.join(claim.supported_by)}`"
        )
    if task.derivations:
        lines.extend(["", "### Derivations", ""])
        for derivation in task.derivations:
            lines.append(
                f"- `{derivation.result_claim}` = `{derivation.expression}`  \n"
                f"  Inputs: `{', '.join(derivation.inputs)}`"
            )
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
        path = output_root / f"{candidate.sample_id}.md"
        path.write_text(
            _candidate_markdown(record, parsed, pdf_by_id[candidate.document_id]),
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
