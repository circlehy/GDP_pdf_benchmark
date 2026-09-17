"""Build a compact funnel and readiness report from immutable stage artifacts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_json_atomic
from pdf_sft.schemas import (
    DifficultyRecord,
    GeneratedCandidate,
    TargetInputPackage,
    ValidatedCandidate,
)
from pdf_sft.tokenization import count_text_tokens


def _validated(path: Path) -> list[ValidatedCandidate]:
    return [ValidatedCandidate.model_validate(payload) for payload in read_jsonl(path)]


def _input_packages(config: AppConfig) -> list[TargetInputPackage]:
    root = config.paths.input_packages / config.target_input.profile
    if not root.exists():
        return []
    return [
        TargetInputPackage.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*.json"))
    ]


def run_report(config: AppConfig, output_path: Path) -> dict:
    generated = [
        GeneratedCandidate.model_validate(payload) for payload in read_jsonl(config.paths.generated)
    ]
    verified = _validated(config.paths.verified)
    rejected = _validated(config.paths.rejected)
    repaired = _validated(config.paths.repaired)
    finalized = _validated(config.paths.finalized)
    difficulty = [
        DifficultyRecord.model_validate(payload) for payload in read_jsonl(config.paths.hard)
    ]
    input_packages = _input_packages(config)
    export_manifest_path = config.paths.exports / "manifest.json"
    export_manifest = (
        json.loads(export_manifest_path.read_text(encoding="utf-8"))
        if export_manifest_path.exists()
        else None
    )
    static_reasons = Counter(
        check.check for record in rejected for check in record.checks if not check.passed
    )
    final_blockers = Counter(
        check.check
        for record in finalized
        for check in record.checks
        if check.check.startswith("final_") and not check.passed
    )
    token_packages = [
        {
            "document_id": package.document_id,
            "pages": len(package.page_numbers),
            "page_image_dpi": package.page_image_dpi,
            "document_text_tokens": package.token_accounting.document_text_tokens,
            "page_image_tokens": package.token_accounting.page_image_tokens,
            "estimated_input_tokens": package.token_accounting.estimated_input_tokens,
            "input_utilization": package.token_accounting.input_utilization,
            "text_tokens_exact": package.token_accounting.text_tokens_exact,
            "image_tokens_exact": package.token_accounting.image_tokens_exact,
        }
        for package in input_packages
    ]
    packages_by_view = {package.document_view_id: package for package in input_packages}
    generated_sequences: list[dict] = []
    tokenizer_path = config.context_budget.text_tokenizer_path
    if tokenizer_path is not None:
        for candidate in generated:
            package = packages_by_view.get(candidate.document_view_id)
            if package is None or package.profile != candidate.input_profile:
                continue
            text_content = (
                f"{candidate.task.prompt}\n\n{package.document_text}\n{candidate.task.gold_answer}"
            )
            text_content_tokens = count_text_tokens(text_content, tokenizer_path)
            estimated_sequence_tokens = (
                text_content_tokens + package.token_accounting.page_image_tokens
            )
            generated_sequences.append(
                {
                    "sample_id": candidate.sample_id,
                    "document_id": candidate.document_id,
                    "pages": len(package.page_numbers),
                    "text_content_tokens": text_content_tokens,
                    "page_image_tokens": package.token_accounting.page_image_tokens,
                    "estimated_sequence_tokens": estimated_sequence_tokens,
                    "sequence_utilization": (
                        estimated_sequence_tokens / config.context_budget.model_context_tokens
                    ),
                }
            )
    token_accounting = {
        "package_count": len(input_packages),
        "tokenizer_or_estimator": sorted(
            {package.token_accounting.tokenizer_or_estimator for package in input_packages}
        ),
        "text_tokens_exact": bool(input_packages)
        and all(package.token_accounting.text_tokens_exact for package in input_packages),
        "image_tokens_exact": bool(input_packages)
        and all(package.token_accounting.image_tokens_exact for package in input_packages),
        "document_text_tokens": sum(
            package.token_accounting.document_text_tokens for package in input_packages
        ),
        "page_image_tokens": sum(
            package.token_accounting.page_image_tokens for package in input_packages
        ),
        "estimated_input_tokens": sum(
            package.token_accounting.estimated_input_tokens for package in input_packages
        ),
        "packages": token_packages,
        "generated_sequences": generated_sequences,
    }
    summary = {
        "schema_version": "0.1",
        "run_id": config.run_id,
        "documents": sum(1 for _ in read_jsonl(config.paths.documents)),
        "generated": len(generated),
        "task_type_distribution": dict(
            Counter(item.task.primary_evidence_type.value for item in generated)
        ),
        "static_accepted": len(verified),
        "static_rejected": len(rejected),
        "static_rejection_reasons": dict(static_reasons),
        "verifier_statuses": dict(
            Counter(record.independent_verifier_status for record in verified)
        ),
        "repaired_records": len(repaired),
        "applied_bbox_repairs": sum(len(record.bbox_repairs) for record in repaired),
        "applied_rubric_overrides": sum(len(record.rubric_overrides) for record in finalized),
        "human_review_statuses": dict(Counter(record.human_review_status for record in finalized)),
        "final_statuses": dict(Counter(record.final_validation_status for record in finalized)),
        "final_blockers": dict(final_blockers),
        "difficulty_assessed": len(difficulty),
        "difficulty_admitted": sum(item.assessment.admitted_as_hard for item in difficulty),
        "difficulty_labels": dict(Counter(item.assessment.predicted_label for item in difficulty)),
        "token_accounting": token_accounting,
        "export": export_manifest,
    }
    release_ready = bool(export_manifest and export_manifest.get("release_ready"))
    blockers: list[str] = []
    if final_blockers:
        blockers.append("final_validation_incomplete")
    if not difficulty:
        blockers.append("no_difficulty_assessments")
    if not release_ready:
        blockers.append("export_not_release_ready")
    summary["release_ready"] = release_ready
    summary["blockers"] = blockers

    json_path = output_path.with_suffix(".json")
    write_json_atomic(json_path, summary)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Pipeline report: {config.run_id}",
        "",
        f"- Documents: **{summary['documents']}**",
        f"- Generated: **{summary['generated']}** — `{summary['task_type_distribution']}`",
        f"- Static accepted/rejected: **{len(verified)} / {len(rejected)}**",
        f"- Verifier statuses: `{summary['verifier_statuses']}`",
        f"- Applied bbox repairs: **{summary['applied_bbox_repairs']}**",
        f"- Applied rubric overrides: **{summary['applied_rubric_overrides']}**",
        f"- Human review statuses: `{summary['human_review_statuses']}`",
        f"- Final statuses: `{summary['final_statuses']}`",
        f"- Difficulty assessed/admitted: **{len(difficulty)} / {summary['difficulty_admitted']}**",
        f"- Difficulty labels: `{summary['difficulty_labels']}`",
        f"- Exact document-text accounting: **{token_accounting['text_tokens_exact']}**",
        f"- Exact image-token accounting: **{token_accounting['image_tokens_exact']}**",
        f"- Release ready: **{release_ready}**",
        "",
        "## Static rejection reasons",
        "",
    ]
    lines.extend(f"- `{reason}`: {count}" for reason, count in sorted(static_reasons.items()))
    if not static_reasons:
        lines.append("- None")
    lines.extend(["", "## Final blockers", ""])
    lines.extend(f"- `{reason}`: {count}" for reason, count in sorted(final_blockers.items()))
    if not final_blockers:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Context accounting",
            "",
            "| Document | Pages | Text tokens | Image tokens* | Input tokens* | Utilization |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        "| {document_id} | {pages} | {document_text_tokens:,} | {page_image_tokens:,} | "
        "{estimated_input_tokens:,} | {input_utilization:.1%} |".format(**package)
        for package in token_packages
    )
    if not token_packages:
        lines.append("| None | 0 | 0 | 0 | 0 | 0% |")
    lines.extend(
        [
            "",
            "### Generated task sequence estimates",
            "",
            "| Sample | Pages | Text content tokens | Image tokens* | Sequence tokens* | "
            "Utilization |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(
        "| {sample_id} | {pages} | {text_content_tokens:,} | {page_image_tokens:,} | "
        "{estimated_sequence_tokens:,} | {sequence_utilization:.1%} |".format(**sequence)
        for sequence in generated_sequences
    )
    if not generated_sequences:
        lines.append("| None | 0 | 0 | 0 | 0 | 0% |")
    lines.extend(
        [
            "",
            "\\* Text counts use the configured target tokenizer when marked exact. Image and total "
            "counts remain estimates until the target vision processor and final chat template are "
            "frozen.",
        ]
    )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "`release_ready=false` is expected while human review, judged difficulty, or exact target "
            "token accounting is incomplete. The pipeline must report zero release-ready records rather "
            "than silently weakening those gates.",
            "",
            f"Machine-readable report: [{json_path.name}]({json_path.resolve()})",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return summary
