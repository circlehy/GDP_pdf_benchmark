"""Command-line entry point for reproducible pipeline stages."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pdf_sft.config import AppConfig, load_config
from pdf_sft.manifests import stage_manifest
from pdf_sft.schemas import InputProfile
from pdf_sft.stages.build_input import run_build_input
from pdf_sft.stages.difficulty_gate import run_difficulty_gate
from pdf_sft.stages.discover import run_discover
from pdf_sft.stages.export import run_export
from pdf_sft.stages.finalize import run_finalize
from pdf_sft.stages.generate import run_generate
from pdf_sft.stages.ingest import run_ingest
from pdf_sft.stages.parse import run_parse
from pdf_sft.stages.repair import run_apply_bbox_repairs
from pdf_sft.stages.report import run_report
from pdf_sft.stages.review_pack import run_review_pack
from pdf_sft.stages.verify import run_model_verify, run_static_verify

DEFAULT_CONFIG = Path("configs/runs/smoke_test.yaml")
DEFAULT_GENERATOR_PROMPT = Path("configs/prompts/generator_v0.md")
DEFAULT_VERIFIER_PROMPT = Path("configs/prompts/verifier_v0.md")
DEFAULT_VERIFIER_AUDIT_PROMPT = Path("configs/prompts/verifier_audit_v0.md")
DEFAULT_DIFFICULTY_JUDGE_PROMPT = Path("configs/prompts/difficulty_judge_v0.md")


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)


def _load(args: argparse.Namespace) -> AppConfig:
    return load_config(args.config)


def _resolve_project_path(config: AppConfig, path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (config.project_root / path).resolve()


def _use_verified_records(config: AppConfig, path: Path | None) -> AppConfig:
    if path is None:
        return config
    configured = config.model_copy(deep=True)
    configured.paths.verified = _resolve_project_path(configured, path)
    return configured


def _run_manifested(
    *,
    config: AppConfig,
    config_path: Path,
    stage: str,
    inputs: list[Path],
    outputs: list[Path],
    function,
    count,
):
    with stage_manifest(
        run_id=config.run_id,
        stage=stage,
        config_path=config_path,
        log_root=config.paths.logs,
        input_paths=inputs,
        output_paths=outputs,
    ) as manifest:
        result = function()
        manifest.counters.update(count(result))
        return result


def command_validate_config(args: argparse.Namespace) -> None:
    config = _load(args)
    summary = {
        "schema_version": config.schema_version,
        "run_id": config.run_id,
        "project_root": str(config.project_root),
        "source_manifest": str(config.source_manifest),
        "forbidden_input_roots": [str(path) for path in config.security.forbidden_input_roots],
        "target_input": {
            "profile": config.target_input.profile,
            "extractor": f"{config.parse.text_extractor}=={config.parse.text_extractor_version}",
            "ocr_language": config.parse.ocr_language,
            "page_image_dpi": config.target_input.page_image_dpi,
            "model_context_tokens": config.context_budget.model_context_tokens,
            "text_tokenizer_path": (
                str(config.context_budget.text_tokenizer_path)
                if config.context_budget.text_tokenizer_path is not None
                else None
            ),
            "target_input_utilization": config.context_budget.target_input_utilization,
            "maximum_input_utilization": config.context_budget.maximum_input_utilization,
        },
        "models": {
            role: {
                "provider": model.provider,
                "model": model.model,
                "api_key_env": model.api_key_env,
                "api_key_is_set": bool(os.environ.get(model.api_key_env, "").strip()),
            }
            for role, model in config.models
            if model is not None
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def command_discover(args: argparse.Namespace) -> None:
    config = _load(args)
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="discover",
        inputs=[config.source_manifest],
        outputs=[config.paths.discovery],
        function=lambda: run_discover(config),
        count=lambda records: {"candidates": len(records)},
    )
    print(f"Discovered {len(result)} candidates -> {config.paths.discovery}")


def command_ingest(args: argparse.Namespace) -> None:
    config = _load(args)
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="ingest",
        inputs=[config.paths.discovery],
        outputs=[config.paths.documents, config.paths.raw_pdfs],
        function=lambda: run_ingest(config),
        count=lambda records: {"documents": len(records)},
    )
    print(f"Ingested {len(result)} documents -> {config.paths.documents}")


def command_parse(args: argparse.Namespace) -> None:
    config = _load(args)
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="parse",
        inputs=[config.paths.documents, config.paths.raw_pdfs],
        outputs=[config.paths.parsed],
        function=lambda: run_parse(config),
        count=lambda records: {
            "documents": len(records),
            "pages": sum(document.page_count for document in records),
        },
    )
    print(f"Parsed {len(result)} documents / {sum(item.page_count for item in result)} pages")


def command_generate(args: argparse.Namespace) -> None:
    config = _load(args)
    prompt_path = args.prompt.resolve()
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="generate",
        inputs=[config.paths.documents, prompt_path],
        outputs=[config.paths.generated],
        function=lambda: run_generate(
            config, prompt_path, limit=args.limit, overwrite=args.overwrite
        ),
        count=lambda records: {"candidates": len(records)},
    )
    print(f"Generated {len(result)} candidates -> {config.paths.generated}")


def command_build_input(args: argparse.Namespace) -> None:
    config = _load(args)
    profile = InputProfile(args.profile or config.target_input.profile)
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="build_input",
        inputs=[config.paths.documents, config.paths.parsed],
        outputs=[config.paths.document_views, config.paths.input_packages / profile.value],
        function=lambda: run_build_input(config, profile=profile),
        count=lambda records: {
            "documents": len(records),
            "pages": sum(len(record.page_numbers) for record in records),
            "estimated_input_tokens": sum(
                record.token_accounting.estimated_input_tokens for record in records
            ),
        },
    )
    print(
        f"Built {len(result)} {profile.value} input packages -> "
        f"{config.paths.input_packages / profile.value}"
    )


def command_static_verify(args: argparse.Namespace) -> None:
    config = _load(args)
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="static_verify",
        inputs=[config.paths.generated, config.paths.parsed],
        outputs=[config.paths.verified, config.paths.rejected],
        function=lambda: run_static_verify(config),
        count=lambda groups: {"accepted": len(groups[0]), "rejected": len(groups[1])},
    )
    accepted, rejected = result
    print(f"Static verification: {len(accepted)} accepted, {len(rejected)} rejected")
    print(
        "Accepted records remain ineligible for difficulty scoring until all final-validation "
        "gates pass"
    )


def command_model_verify(args: argparse.Namespace) -> None:
    config = _use_verified_records(_load(args), args.records)
    reconstruction_prompt = args.prompt.resolve()
    audit_prompt = args.audit_prompt.resolve()
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="model_verify",
        inputs=[config.paths.verified, config.paths.parsed, reconstruction_prompt, audit_prompt],
        outputs=[config.paths.verified],
        function=lambda: run_model_verify(
            config,
            reconstruction_prompt,
            audit_prompt,
            limit=args.limit,
            overwrite=args.overwrite,
        ),
        count=lambda records: {
            status: sum(item.independent_verifier_status == status for item in records)
            for status in ("passed", "failed", "needs_review", "not_run")
        },
    )
    counts = {
        status: sum(item.independent_verifier_status == status for item in result)
        for status in ("passed", "failed", "needs_review", "not_run")
    }
    print(f"Independent verification: {counts}")


def command_review_pack(args: argparse.Namespace) -> None:
    config = _use_verified_records(_load(args), args.records)
    output_root = (config.project_root / args.output).resolve()
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="review_pack",
        inputs=[config.paths.verified, config.paths.documents, config.paths.parsed],
        outputs=[output_root],
        function=lambda: run_review_pack(config, output_root),
        count=lambda paths: {"files": len(paths), "candidates": max(0, len(paths) - 1)},
    )
    print(f"Review pack: {len(result) - 1} candidates -> {result[0]}")


def command_apply_bbox_repairs(args: argparse.Namespace) -> None:
    config = _load(args)
    review_pack_root = _resolve_project_path(config, args.review_pack)
    input_path = _resolve_project_path(config, args.records) if args.records is not None else None
    output_path = _resolve_project_path(config, args.output) if args.output is not None else None
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="apply_bbox_repairs",
        inputs=[
            input_path or config.paths.verified,
            review_pack_root,
            config.paths.parsed,
        ],
        outputs=[output_path or config.paths.repaired],
        function=lambda: run_apply_bbox_repairs(
            config,
            review_pack_root,
            input_path=input_path,
            output_path=output_path,
        ),
        count=lambda records: {
            "records": len(records),
            "applied_repairs": sum(len(record.bbox_repairs) for record in records),
            "unresolved_records": sum(
                any(
                    check.check == "bbox_repair_decisions_resolved" and not check.passed
                    for check in record.checks
                )
                for record in records
            ),
        },
    )
    applied = sum(len(record.bbox_repairs) for record in result)
    unresolved = sum(
        any(
            check.check == "bbox_repair_decisions_resolved" and not check.passed
            for check in record.checks
        )
        for record in result
    )
    print(
        f"BBox repairs: {applied} applied, {unresolved} records unresolved -> "
        f"{output_path or config.paths.repaired}"
    )


def command_finalize(args: argparse.Namespace) -> None:
    config = _load(args)
    review_pack_root = _resolve_project_path(config, args.review_pack)
    input_path = (
        _resolve_project_path(config, args.records)
        if args.records is not None
        else config.paths.repaired
    )
    output_path = (
        _resolve_project_path(config, args.output)
        if args.output is not None
        else config.paths.finalized
    )
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="finalize",
        inputs=[input_path, review_pack_root, config.paths.documents, config.paths.parsed],
        outputs=[output_path],
        function=lambda: run_finalize(
            config,
            review_pack_root,
            input_path=input_path,
            output_path=output_path,
        ),
        count=lambda records: {
            status: sum(record.final_validation_status == status for record in records)
            for status in ("passed", "failed", "needs_review", "not_run")
        },
    )
    counts = {
        status: sum(record.final_validation_status == status for record in result)
        for status in ("passed", "failed", "needs_review", "not_run")
    }
    print(f"Final validation: {counts} -> {output_path}")


def command_difficulty_gate(args: argparse.Namespace) -> None:
    config = _load(args)
    input_path = (
        _resolve_project_path(config, args.records)
        if args.records is not None
        else config.paths.finalized
    )
    output_path = (
        _resolve_project_path(config, args.output) if args.output is not None else config.paths.hard
    )
    prompt_path = args.prompt.resolve()
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="difficulty_gate",
        inputs=[input_path, prompt_path],
        outputs=[output_path],
        function=lambda: run_difficulty_gate(
            config,
            prompt_path,
            mode=args.mode,
            input_path=input_path,
            output_path=output_path,
            limit=args.limit,
        ),
        count=lambda records: {
            "assessed": len(records),
            "predicted_hard": sum(
                record.assessment.predicted_label == "hard" for record in records
            ),
            "admitted_hard": sum(record.assessment.admitted_as_hard for record in records),
        },
    )
    print(
        f"Difficulty gate: {len(result)} assessed, "
        f"{sum(item.assessment.admitted_as_hard for item in result)} admitted -> {output_path}"
    )


def command_export(args: argparse.Namespace) -> None:
    config = _load(args)
    input_path = (
        _resolve_project_path(config, args.records)
        if args.records is not None
        else config.paths.hard
    )
    output_root = (
        _resolve_project_path(config, args.output)
        if args.output is not None
        else config.paths.exports
    )
    manifest = _run_manifested(
        config=config,
        config_path=args.config,
        stage="export",
        inputs=[input_path, config.paths.input_packages],
        outputs=[output_root],
        function=lambda: run_export(
            config,
            input_path=input_path,
            output_root=output_root,
            allow_predicted_difficulty=args.allow_predicted_difficulty,
        ),
        count=lambda result: {
            "training_records": result["training_records"],
            "rejected_records": result["rejected_records"],
            "estimated_total_sequence_tokens": result["estimated_total_sequence_tokens"],
        },
    )
    print(
        f"Export: {manifest['training_records']} training records, "
        f"{manifest['rejected_records']} rejected -> {output_root}"
    )


def command_report(args: argparse.Namespace) -> None:
    config = _load(args)
    output_path = (
        _resolve_project_path(config, args.output)
        if args.output is not None
        else config.project_root / "reports" / config.run_id / "pipeline_report.md"
    )
    result = _run_manifested(
        config=config,
        config_path=args.config,
        stage="report",
        inputs=[
            config.paths.generated,
            config.paths.verified,
            config.paths.rejected,
            config.paths.repaired,
            config.paths.finalized,
            config.paths.hard,
            config.paths.exports,
            config.paths.input_packages / config.target_input.profile,
        ],
        outputs=[output_path, output_path.with_suffix(".json")],
        function=lambda: run_report(config, output_path),
        count=lambda summary: {
            "generated": summary["generated"],
            "static_accepted": summary["static_accepted"],
            "difficulty_admitted": summary["difficulty_admitted"],
        },
    )
    print(f"Pipeline report: release_ready={result['release_ready']} -> {output_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdf-sft", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="Validate configuration safely")
    _add_config_argument(validate)
    validate.set_defaults(handler=command_validate_config)

    discover = subparsers.add_parser("discover", help="Normalize reviewed source candidates")
    _add_config_argument(discover)
    discover.set_defaults(handler=command_discover)

    ingest = subparsers.add_parser("ingest", help="Download approved PDFs")
    _add_config_argument(ingest)
    ingest.set_defaults(handler=command_ingest)

    parse = subparsers.add_parser("parse", help="Render and parse ingested PDFs")
    _add_config_argument(parse)
    parse.set_defaults(handler=command_parse)

    build_input = subparsers.add_parser(
        "build-input", help="Freeze document views and build target-visible packages"
    )
    _add_config_argument(build_input)
    build_input.add_argument(
        "--profile",
        choices=[profile.value for profile in InputProfile],
        default=None,
        help="Override target_input.profile (default configuration: multimodal)",
    )
    build_input.set_defaults(handler=command_build_input)

    generate = subparsers.add_parser("generate", help="Generate evidence-first candidates")
    _add_config_argument(generate)
    generate.add_argument("--prompt", type=Path, default=DEFAULT_GENERATOR_PROMPT)
    generate.add_argument(
        "--limit", type=int, default=None, help="Process at most N documents for a smoke run"
    )
    generate.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate completed documents instead of resuming",
    )
    generate.set_defaults(handler=command_generate)

    verify = subparsers.add_parser(
        "static-verify", help="Run deterministic schema and evidence-graph checks"
    )
    _add_config_argument(verify)
    verify.set_defaults(handler=command_static_verify)

    model_verify = subparsers.add_parser(
        "model-verify", help="Blindly reconstruct answers and independently audit gold claims"
    )
    _add_config_argument(model_verify)
    model_verify.add_argument("--prompt", type=Path, default=DEFAULT_VERIFIER_PROMPT)
    model_verify.add_argument("--audit-prompt", type=Path, default=DEFAULT_VERIFIER_AUDIT_PROMPT)
    model_verify.add_argument(
        "--limit", type=int, default=None, help="Process at most N candidates"
    )
    model_verify.add_argument(
        "--overwrite", action="store_true", help="Repeat verification for completed candidates"
    )
    model_verify.add_argument(
        "--records", type=Path, default=None, help="Use an alternate validated JSONL artifact"
    )
    model_verify.set_defaults(handler=command_model_verify)

    apply_repairs = subparsers.add_parser(
        "apply-bbox-repairs",
        help="Apply reviewer-accepted bbox decisions to a new validated JSONL artifact",
    )
    _add_config_argument(apply_repairs)
    apply_repairs.add_argument("--review-pack", type=Path, required=True)
    apply_repairs.add_argument(
        "--records", type=Path, default=None, help="Validated JSONL to repair"
    )
    apply_repairs.add_argument(
        "--output", type=Path, default=None, help="Output JSONL; defaults to paths.repaired"
    )
    apply_repairs.set_defaults(handler=command_apply_bbox_repairs)

    finalize = subparsers.add_parser(
        "finalize",
        help="Run conservative automatic and human gates before difficulty scoring",
    )
    _add_config_argument(finalize)
    finalize.add_argument("--review-pack", type=Path, required=True)
    finalize.add_argument(
        "--records", type=Path, default=None, help="Input JSONL; defaults to paths.repaired"
    )
    finalize.add_argument(
        "--output", type=Path, default=None, help="Output JSONL; defaults to paths.finalized"
    )
    finalize.set_defaults(handler=command_finalize)

    difficulty_gate = subparsers.add_parser(
        "difficulty-gate", help="Score final-passed samples and optionally judge solver failures"
    )
    _add_config_argument(difficulty_gate)
    difficulty_gate.add_argument("--mode", choices=["predicted", "judged"], default="predicted")
    difficulty_gate.add_argument("--prompt", type=Path, default=DEFAULT_DIFFICULTY_JUDGE_PROMPT)
    difficulty_gate.add_argument("--records", type=Path, default=None)
    difficulty_gate.add_argument("--output", type=Path, default=None)
    difficulty_gate.add_argument("--limit", type=int, default=None)
    difficulty_gate.set_defaults(handler=command_difficulty_gate)

    export = subparsers.add_parser(
        "export", help="Export hint-free training conversations and separate audit sidecars"
    )
    _add_config_argument(export)
    export.add_argument("--records", type=Path, default=None)
    export.add_argument("--output", type=Path, default=None)
    export.add_argument(
        "--allow-predicted-difficulty",
        action="store_true",
        help="Allow structurally predicted hard samples for non-release pilot exports",
    )
    export.set_defaults(handler=command_export)

    report = subparsers.add_parser("report", help="Summarize the pipeline funnel and blockers")
    _add_config_argument(report)
    report.add_argument("--output", type=Path, default=None)
    report.set_defaults(handler=command_report)

    review_pack = subparsers.add_parser(
        "review-pack",
        help="Generate task reports with evidence pages and non-mutating bbox repair suggestions",
    )
    _add_config_argument(review_pack)
    review_pack.add_argument(
        "--output", type=Path, default=Path("reports/smoke_test_v0/review_pack")
    )
    review_pack.add_argument(
        "--records", type=Path, default=None, help="Use an alternate validated JSONL artifact"
    )
    review_pack.set_defaults(handler=command_review_pack)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)
