"""Evidence-first generation from the target-visible training package."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_json_atomic, write_jsonl_atomic
from pdf_sft.llm import StructuredModelClient
from pdf_sft.schemas import DocumentRecord, GeneratedCandidate, GenerationBatchDraft, InputProfile
from pdf_sft.stages.build_input import load_input_packages

PROMPT_VERSION = "generator_v2"


def _sample_id(document_id: str, index: int, prompt_version: str) -> str:
    digest = hashlib.sha256(f"{document_id}\0{index}\0{prompt_version}".encode()).hexdigest()[:20]
    return f"pdfsft_{digest}"


def _structure_repair_prompt(raw_output: str, error: Exception, candidate_count: int) -> str:
    return f"""Your previous structured generation output failed deterministic schema validation.
Return the complete corrected JSON batch with exactly {candidate_count} candidates.

Only repair schema/reference integrity: operation order and IDs, final_output reachability,
claim/derivation/rubric references, required fields, and candidate count. Preserve the task's
question, evidence meaning, gold answer, and difficulty. Do not explain the repair.

VALIDATION ERROR
{type(error).__name__}: {error}

PREVIOUS JSON OUTPUT
{raw_output}
"""


def requested_type_schedule(weights: dict[str, float], total: int) -> list[str]:
    """Allocate an exact, smoothly interleaved run-level task-type schedule."""

    if total <= 0:
        return []
    raw = {name: weight * total for name, weight in weights.items()}
    quotas = {name: math.floor(value) for name, value in raw.items()}
    remaining = total - sum(quotas.values())
    order = {name: index for index, name in enumerate(weights)}
    for name in sorted(weights, key=lambda item: (-(raw[item] - quotas[item]), order[item]))[
        :remaining
    ]:
        quotas[name] += 1

    current = {name: 0 for name in weights}
    used = {name: 0 for name in weights}
    schedule: list[str] = []
    for _ in range(total):
        for name in weights:
            current[name] += quotas[name]
        available = [name for name in weights if used[name] < quotas[name]]
        selected = max(available, key=lambda name: (current[name], -order[name]))
        schedule.append(selected)
        used[selected] += 1
        current[selected] -= total
    return schedule


def run_generate(
    config: AppConfig,
    prompt_path: Path,
    *,
    limit: int | None = None,
    overwrite: bool = False,
) -> list[GeneratedCandidate]:
    prompt_template = prompt_path.read_text(encoding="utf-8")
    prompt_digest = hashlib.sha256(prompt_template.encode("utf-8")).hexdigest()[:12]
    prompt_version = f"{PROMPT_VERSION}+sha256:{prompt_digest}"
    base_prompt = prompt_template.format(candidate_count=config.generation.candidates_per_document)
    client = StructuredModelClient(config.models.generator)
    profile = InputProfile(config.target_input.profile)
    packages = load_input_packages(config, profile)
    generated = (
        []
        if overwrite
        else [
            GeneratedCandidate.model_validate(payload)
            for payload in read_jsonl(config.paths.generated)
        ]
    )
    completed_document_ids = {candidate.document_id for candidate in generated}
    documents = [
        DocumentRecord.model_validate(payload) for payload in read_jsonl(config.paths.documents)
    ]
    requested_types = requested_type_schedule(
        config.generation.primary_evidence_type_weights,
        len(documents) * config.generation.candidates_per_document,
    )
    processed = 0
    for document_index, document in enumerate(documents):
        if document.document_id in completed_document_ids:
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        package = packages.get(document.document_id)
        if package is None:
            raise ValueError(
                f"Missing {profile.value} input package for {document.document_id}; "
                "run pdf-sft build-input first"
            )
        estimated_input_tokens = package.token_accounting.estimated_input_tokens
        if not config.models.generator.estimated_request_fits(estimated_input_tokens):
            raise ValueError(
                f"Estimated request for {document.document_id} needs "
                f"{estimated_input_tokens} input + "
                f"{config.models.generator.max_output_tokens} output tokens, exceeding "
                f"generator {config.models.generator.model} context window "
                f"{config.models.generator.context_window_tokens}; use a semantically bounded "
                "document view or a longer-context generator"
            )
        document_key = document.document_id.split(":", 1)[-1]
        type_start = document_index * config.generation.candidates_per_document
        document_requested_types = requested_types[
            type_start : type_start + config.generation.candidates_per_document
        ]
        prompt = (
            f"{base_prompt}\n\n"
            f"TARGET INPUT PROFILE: {profile.value}\n"
            "REQUIRED PRIMARY EVIDENCE TYPES BY CANDIDATE INDEX: "
            f"{document_requested_types}\n"
            "Candidate i MUST use the type at index i as primary_evidence_type; this is a hard "
            "batch quota, not a suggestion.\n"
            f"DOCUMENT VIEW ID: {package.document_view_id}\n"
            f"PAGES WITH NO EXTRACTED TEXT: {package.text_empty_page_numbers}\n"
            "The complete LiteParse text visible to the target model follows. Page markers are "
            "part of the delivery format. In multimodal mode, the same complete pages are also "
            "attached as images before this text.\n\n"
            f"{package.document_text}"
        )
        call_log_root = config.paths.logs / "api" / config.run_id / "generate"
        request_prompt = prompt
        request_images = package.page_image_paths
        batch = None
        for attempt in range(1, config.generation.max_structure_repair_attempts + 2):
            try:
                batch = client.generate(
                    prompt=request_prompt,
                    output_type=GenerationBatchDraft,
                    image_paths=request_images,
                )
                write_json_atomic(
                    call_log_root / f"{document_key}.attempt_{attempt}.json",
                    client.last_call_metadata,
                )
                break
            except Exception as exc:
                if client.last_call_metadata:
                    write_json_atomic(
                        call_log_root / f"{document_key}.attempt_{attempt}.json",
                        client.last_call_metadata,
                    )
                if client.last_raw_output:
                    raw_path = call_log_root / f"{document_key}.attempt_{attempt}.raw.txt"
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_text(client.last_raw_output, encoding="utf-8")
                if (
                    attempt > config.generation.max_structure_repair_attempts
                    or not client.last_raw_output
                ):
                    raise
                request_prompt = _structure_repair_prompt(
                    client.last_raw_output,
                    exc,
                    config.generation.candidates_per_document,
                )
                request_images = []
        assert batch is not None
        write_json_atomic(call_log_root / f"{document_key}.json", client.last_call_metadata)
        response_id = client.last_call_metadata.get("response_id")
        if len(batch.candidates) != config.generation.candidates_per_document:
            raise ValueError(
                f"Generator returned {len(batch.candidates)} candidates for "
                f"{document.document_id}; "
                f"expected {config.generation.candidates_per_document}"
            )
        returned_types = [draft.task.primary_evidence_type.value for draft in batch.candidates]
        if returned_types != document_requested_types:
            raise ValueError(
                f"Generator returned primary evidence types {returned_types} for "
                f"{document.document_id}; required {document_requested_types}"
            )
        for index, draft in enumerate(batch.candidates):
            if profile not in draft.task.supported_input_profiles:
                raise ValueError(
                    f"Generator marked candidate {index} unsupported for its generation profile "
                    f"{profile.value}"
                )
            if profile == InputProfile.text_only and draft.task.requires_visual_evidence:
                raise ValueError("A text_only candidate cannot require visual evidence")
            generated.append(
                GeneratedCandidate(
                    sample_id=_sample_id(document.document_id, index, prompt_version),
                    document_id=document.document_id,
                    document_view_id=package.document_view_id,
                    input_profile=profile,
                    task=draft.task,
                    rubric=draft.rubric,
                    generator_model=config.models.generator.model,
                    generator_prompt_version=prompt_version,
                    generator_response_id=response_id,
                )
            )
        completed_document_ids.add(document.document_id)
        write_jsonl_atomic(config.paths.generated, generated)
    if not config.paths.generated.exists():
        write_jsonl_atomic(config.paths.generated, generated)
    return generated
