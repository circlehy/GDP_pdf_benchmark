"""Export training conversations separately from audit sidecars."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_json_atomic, write_jsonl_atomic
from pdf_sft.schemas import DifficultyRecord, InputProfile
from pdf_sft.stages.build_input import load_input_packages
from pdf_sft.tokenization import count_text_tokens, tokenizer_label


def _split_for_document(document_id: str) -> str:
    bucket = int(hashlib.sha256(document_id.encode()).hexdigest()[:8], 16) % 100
    if bucket < 90:
        return "train"
    if bucket < 95:
        return "validation"
    return "internal_holdout"


def _user_content(profile: InputProfile, image_paths: list[Path], text: str) -> list[dict]:
    content: list[dict] = []
    if profile == InputProfile.multimodal:
        content.extend({"type": "image", "path": str(path.resolve())} for path in image_paths)
    content.append({"type": "text", "text": text})
    return content


def run_export(
    config: AppConfig,
    *,
    input_path: Path | None = None,
    output_root: Path | None = None,
    allow_predicted_difficulty: bool = False,
) -> dict:
    """Export only hard-admitted, final-passed records; never include audit hints in user input."""

    input_path = (input_path or config.paths.hard).resolve()
    output_root = (output_root or config.paths.exports).resolve()
    records_by_split: dict[str, list[dict]] = defaultdict(list)
    sidecars: list[dict] = []
    packages_by_profile = {}
    rejected: list[dict] = []
    total_sequence_tokens = 0

    for payload in read_jsonl(input_path):
        difficulty_record = DifficultyRecord.model_validate(payload)
        record = difficulty_record.validated
        assessment = difficulty_record.assessment
        candidate = record.candidate
        reasons: list[str] = []
        if record.final_validation_status != "passed" or not record.eligible_for_difficulty:
            reasons.append("final_validation_not_passed")
        if not assessment.admitted_as_hard:
            reasons.append("not_admitted_as_hard")
        if not assessment.difficulty_verified and not allow_predicted_difficulty:
            reasons.append("difficulty_not_verified")
        if record.human_review_status != "approved":
            reasons.append("human_review_not_approved")
        if reasons:
            rejected.append({"sample_id": candidate.sample_id, "reasons": reasons})
            continue

        profile = candidate.input_profile
        if profile not in packages_by_profile:
            packages_by_profile[profile] = load_input_packages(config, profile)
        package = packages_by_profile[profile].get(candidate.document_id)
        if package is None or package.document_view_id != candidate.document_view_id:
            rejected.append(
                {"sample_id": candidate.sample_id, "reasons": ["input_package_mismatch"]}
            )
            continue
        user_text = f"{candidate.task.prompt}\n\n{package.document_text}"
        answer = candidate.task.gold_answer
        tokenizer_path = config.context_budget.text_tokenizer_path
        if tokenizer_path is not None:
            text_tokens = count_text_tokens(f"{user_text}\n{answer}", tokenizer_path)
            text_counter = tokenizer_label(tokenizer_path)
            text_tokens_exact = True
        else:
            text_tokens = math.ceil(
                (len(user_text) + len(answer)) / config.context_budget.provisional_chars_per_token
            )
            text_counter = package.token_accounting.tokenizer_or_estimator
            text_tokens_exact = False
        estimated_sequence_tokens = text_tokens + package.token_accounting.page_image_tokens
        if estimated_sequence_tokens > config.context_budget.model_context_tokens:
            rejected.append(
                {"sample_id": candidate.sample_id, "reasons": ["export_sequence_over_context"]}
            )
            continue
        total_sequence_tokens += estimated_sequence_tokens
        split = _split_for_document(candidate.document_id)
        training_record = {
            "schema_version": "0.1",
            "sample_id": candidate.sample_id,
            "document_id": candidate.document_id,
            "document_view_id": candidate.document_view_id,
            "input_profile": profile.value,
            "messages": [
                {
                    "role": "user",
                    "content": _user_content(profile, package.page_image_paths, user_text),
                },
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": answer}],
                },
            ],
            "token_accounting": {
                "tokenizer_or_estimator": text_counter,
                "vision_processor": package.token_accounting.vision_processor,
                "exact": False,
                "text_tokens_exact": text_tokens_exact,
                "image_tokens_exact": package.token_accounting.image_tokens_exact,
                "text_content_tokens": text_tokens,
                "estimated_sequence_tokens": estimated_sequence_tokens,
                "context_window_tokens": config.context_budget.model_context_tokens,
                "sequence_utilization": (
                    estimated_sequence_tokens / config.context_budget.model_context_tokens
                ),
            },
        }
        records_by_split[split].append(training_record)
        sidecars.append(
            {
                "schema_version": "0.1",
                "sample_id": candidate.sample_id,
                "split": split,
                "source": {
                    "document_id": candidate.document_id,
                    "document_view_id": candidate.document_view_id,
                },
                "task_audit": {
                    "claims": [claim.model_dump(mode="json") for claim in candidate.task.claims],
                    "derivations": [
                        item.model_dump(mode="json") for item in candidate.task.derivations
                    ],
                    "evidence_graph": candidate.task.evidence_graph.model_dump(mode="json"),
                    "rubric": [item.model_dump(mode="json") for item in candidate.rubric],
                },
                "validation": {
                    "checks": [check.model_dump(mode="json") for check in record.checks],
                    "bbox_repairs": [
                        repair.model_dump(mode="json") for repair in record.bbox_repairs
                    ],
                    "rubric_overrides": [
                        override.model_dump(mode="json") for override in record.rubric_overrides
                    ],
                    "independent_verifier_model": record.independent_verifier_model,
                    "independent_verifier_status": record.independent_verifier_status,
                    "human_review_status": record.human_review_status,
                    "final_validation_status": record.final_validation_status,
                },
                "difficulty": assessment.model_dump(mode="json"),
            }
        )

    output_root.mkdir(parents=True, exist_ok=True)
    for split in ("train", "validation", "internal_holdout"):
        write_jsonl_atomic(output_root / f"{split}.jsonl", records_by_split.get(split, []))
    write_jsonl_atomic(output_root / "sidecar.jsonl", sidecars)
    write_jsonl_atomic(output_root / "rejected.jsonl", rejected)
    manifest = {
        "schema_version": "0.1",
        "run_id": config.run_id,
        "input_path": str(input_path),
        "allow_predicted_difficulty": allow_predicted_difficulty,
        "training_records": sum(len(items) for items in records_by_split.values()),
        "split_counts": {
            split: len(records_by_split.get(split, []))
            for split in ("train", "validation", "internal_holdout")
        },
        "sidecar_records": len(sidecars),
        "rejected_records": len(rejected),
        "estimated_total_sequence_tokens": total_sequence_tokens,
        "token_accounting_exact": False,
        "text_tokenizer_configured": config.context_budget.text_tokenizer_path is not None,
        "text_content_token_accounting_exact": bool(sidecars)
        and config.context_budget.text_tokenizer_path is not None,
        "vision_token_accounting_exact": bool(sidecars)
        and all(
            record["token_accounting"]["image_tokens_exact"]
            for records in records_by_split.values()
            for record in records
        ),
        "serialization_template_exact": False,
        "release_ready": bool(sidecars)
        and all(item["difficulty"]["difficulty_verified"] for item in sidecars),
    }
    write_json_atomic(output_root / "manifest.json", manifest)
    return manifest
