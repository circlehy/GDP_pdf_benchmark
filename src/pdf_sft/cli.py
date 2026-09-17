"""Command-line entry point for reproducible pipeline stages."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pdf_sft.config import AppConfig, load_config
from pdf_sft.manifests import stage_manifest
from pdf_sft.stages.discover import run_discover
from pdf_sft.stages.generate import run_generate
from pdf_sft.stages.ingest import run_ingest
from pdf_sft.stages.parse import run_parse
from pdf_sft.stages.review_pack import run_review_pack
from pdf_sft.stages.verify import run_model_verify, run_static_verify

DEFAULT_CONFIG = Path("configs/runs/smoke_test.yaml")
DEFAULT_GENERATOR_PROMPT = Path("configs/prompts/generator_v0.md")
DEFAULT_VERIFIER_PROMPT = Path("configs/prompts/verifier_v0.md")
DEFAULT_VERIFIER_AUDIT_PROMPT = Path("configs/prompts/verifier_audit_v0.md")


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)


def _load(args: argparse.Namespace) -> AppConfig:
    return load_config(args.config)


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
        "models": {
            role: {
                "provider": model.provider,
                "model": model.model,
                "api_key_env": model.api_key_env,
                "api_key_is_set": bool(os.environ.get(model.api_key_env, "").strip()),
            }
            for role, model in config.models
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
        "Accepted records remain ineligible for difficulty scoring until independent verification"
    )


def command_model_verify(args: argparse.Namespace) -> None:
    config = _load(args)
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
    config = _load(args)
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
    model_verify.set_defaults(handler=command_model_verify)

    review_pack = subparsers.add_parser(
        "review-pack", help="Generate readable task, answer, rubric, and evidence-page reports"
    )
    _add_config_argument(review_pack)
    review_pack.add_argument(
        "--output", type=Path, default=Path("reports/smoke_test_v0/review_pack")
    )
    review_pack.set_defaults(handler=command_review_pack)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)
