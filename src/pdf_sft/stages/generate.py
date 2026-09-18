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


def _hard_target_instructions(config: AppConfig) -> str:
    generation = config.generation
    if generation.target_difficulty != "hard":
        return ""
    return (
        "\nHARD-TASK TARGET (mandatory for every candidate):\n"
        f"- Use at least {generation.hard_min_evidence_nodes} decisive evidence nodes across "
        f"at least {generation.hard_min_evidence_pages} distinct pages.\n"
        f"- Use at least {generation.hard_min_dependent_operations} dependent operations in one "
        "connected chain, including at least two non-lookup operations.\n"
        "- Require a multi-stage professional decision: combine, filter, reconcile, compare, or "
        "calculate before reaching the final answer.\n"
        "- Include a plausible near-match, exception, threshold, footnote, or scope trap that must "
        "be actively ruled out.\n"
        "- Cover at least two distinct Tier 2 axes and two distinct Tier 3 axes when the document "
        "supports them.\n"
        "- Do not pad the graph with redundant nodes or operations merely to reach these counts.\n"
    )


def _prior_candidate_summary(candidates: list[GeneratedCandidate]) -> str:
    if not candidates:
        return "None; this is the first batch for the document."
    lines: list[str] = []
    for candidate in candidates:
        pages = sorted({node.page for node in candidate.task.evidence_graph.nodes})
        operations = [operation.op for operation in candidate.task.evidence_graph.operations]
        lines.append(
            f"- {candidate.sample_id}: type={candidate.task.primary_evidence_type.value}; "
            f"pages={pages}; operations={operations}; question={candidate.task.prompt}"
        )
    return "\n".join(lines)


def _document_selected(document_id: str, selectors: set[str] | None) -> bool:
    if not selectors:
        return True
    digest = document_id.split(":", 1)[-1]
    return document_id in selectors or digest in selectors


def generation_batch_policy_errors(
    batch: GenerationBatchDraft,
    config: AppConfig,
    *,
    required_types: list[str],
    profile: InputProfile,
) -> list[str]:
    errors: list[str] = []
    if len(batch.candidates) != len(required_types):
        errors.append(f"candidate_count={len(batch.candidates)}; required={len(required_types)}")
        return errors
    for index, draft in enumerate(batch.candidates):
        prefix = f"candidate[{index}]"
        task = draft.task
        graph = task.evidence_graph
        if task.primary_evidence_type.value != required_types[index]:
            errors.append(
                f"{prefix}.primary_evidence_type={task.primary_evidence_type.value}; "
                f"required={required_types[index]}"
            )
        if profile not in task.supported_input_profiles:
            errors.append(f"{prefix} does not support profile {profile.value}")
        if profile == InputProfile.text_only and task.requires_visual_evidence:
            errors.append(f"{prefix} requires visual evidence under text_only profile")

        claim_ids = {claim.claim_id for claim in task.claims}
        rubric_claim_refs = {
            reference
            for criterion in draft.rubric
            for reference in criterion.supported_by
            if reference in claim_ids
        }
        uncovered_claims = sorted(claim_ids - rubric_claim_refs)
        if uncovered_claims:
            errors.append(f"{prefix} rubric misses direct claim refs {uncovered_claims}")

        operation_inputs = {operation.output: operation.inputs for operation in graph.operations}
        ancestors: set[str] = set()
        stack = [graph.final_output]
        while stack:
            reference = stack.pop()
            if reference in ancestors:
                continue
            ancestors.add(reference)
            stack.extend(operation_inputs.get(reference, []))
        disconnected = sorted(
            node.id for node in graph.nodes if node.key and node.id not in ancestors
        )
        if disconnected:
            errors.append(f"{prefix} key evidence disconnected from final_output: {disconnected}")

        if config.generation.target_difficulty == "hard":
            distinct_pages = {node.page for node in graph.nodes}
            non_lookup = sum(operation.op != "lookup" for operation in graph.operations)
            if len(graph.nodes) < config.generation.hard_min_evidence_nodes:
                errors.append(f"{prefix} has only {len(graph.nodes)} evidence nodes")
            if len(distinct_pages) < config.generation.hard_min_evidence_pages:
                errors.append(f"{prefix} has evidence on only {len(distinct_pages)} pages")
            if len(graph.operations) < config.generation.hard_min_dependent_operations:
                errors.append(f"{prefix} has only {len(graph.operations)} operations")
            if non_lookup < 2:
                errors.append(f"{prefix} has only {non_lookup} non-lookup operations")
    return errors


def run_generate(
    config: AppConfig,
    prompt_path: Path,
    *,
    limit: int | None = None,
    overwrite: bool = False,
    document_ids: list[str] | None = None,
) -> list[GeneratedCandidate]:
    prompt_template = prompt_path.read_text(encoding="utf-8")
    prompt_digest = hashlib.sha256(prompt_template.encode("utf-8")).hexdigest()[:12]
    policy = config.generation
    policy_text = (
        f"{policy.target_difficulty}:{policy.candidates_per_document}:"
        f"{policy.batches_per_document}:{policy.hard_min_evidence_nodes}:"
        f"{policy.hard_min_evidence_pages}:{policy.hard_min_dependent_operations}"
    )
    policy_digest = hashlib.sha256(policy_text.encode()).hexdigest()[:8]
    prompt_version = f"{PROMPT_VERSION}+sha256:{prompt_digest}+policy:{policy_digest}"
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
    selectors = set(document_ids or []) or None
    documents = [
        DocumentRecord.model_validate(payload) for payload in read_jsonl(config.paths.documents)
    ]
    documents = [
        document for document in documents if _document_selected(document.document_id, selectors)
    ]
    if selectors and not documents:
        raise ValueError(f"No document matched --document-id values: {sorted(selectors)}")
    candidates_per_batch = config.generation.candidates_per_document
    batches_per_document = config.generation.batches_per_document
    total_per_document = candidates_per_batch * batches_per_document
    requested_types = requested_type_schedule(
        config.generation.primary_evidence_type_weights,
        len(documents) * total_per_document,
    )
    processed = 0
    for document_index, document in enumerate(documents):
        existing_for_document = [
            candidate for candidate in generated if candidate.document_id == document.document_id
        ]
        if len(existing_for_document) >= total_per_document:
            continue
        if len(existing_for_document) % candidates_per_batch:
            raise ValueError(
                f"Existing output for {document.document_id} contains a partial generation "
                f"batch ({len(existing_for_document)} candidates; batch size "
                f"{candidates_per_batch})"
            )
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
        call_log_root = config.paths.logs / "api" / config.run_id / "generate"
        first_batch = len(existing_for_document) // candidates_per_batch
        for batch_index in range(first_batch, batches_per_document):
            global_start = document_index * total_per_document + batch_index * candidates_per_batch
            document_requested_types = requested_types[
                global_start : global_start + candidates_per_batch
            ]
            prompt = (
                f"{base_prompt}\n\n"
                f"TARGET INPUT PROFILE: {profile.value}\n"
                "REQUIRED PRIMARY EVIDENCE TYPES BY CANDIDATE INDEX: "
                f"{document_requested_types}\n"
                "Candidate i MUST use the type at index i as primary_evidence_type; this is a "
                "hard batch quota, not a suggestion.\n"
                f"{_hard_target_instructions(config)}"
                "\nPRIOR CANDIDATES FROM THIS DOCUMENT (avoid material overlap):\n"
                f"{_prior_candidate_summary(existing_for_document)}\n"
                "New candidates must use materially different decisive evidence regions and "
                "reasoning paths. Reusing a page is allowed only when the decisive region and "
                "professional decision are different.\n"
                f"DOCUMENT VIEW ID: {package.document_view_id}\n"
                f"PAGES WITH NO EXTRACTED TEXT: {package.text_empty_page_numbers}\n"
                "The complete LiteParse text visible to the target model follows. Page markers "
                "are part of the delivery format. In multimodal mode, the same complete pages "
                "are also attached as images before this text.\n\n"
                f"{package.document_text}"
            )
            request_prompt = prompt
            request_images = package.page_image_paths
            batch = None
            batch_number = batch_index + 1
            for attempt in range(1, config.generation.max_structure_repair_attempts + 2):
                try:
                    batch = client.generate(
                        prompt=request_prompt,
                        output_type=GenerationBatchDraft,
                        image_paths=request_images,
                    )
                    policy_errors = generation_batch_policy_errors(
                        batch,
                        config,
                        required_types=document_requested_types,
                        profile=profile,
                    )
                    if policy_errors:
                        raise ValueError("; ".join(policy_errors))
                    write_json_atomic(
                        call_log_root
                        / f"{document_key}.batch_{batch_number}.attempt_{attempt}.json",
                        client.last_call_metadata,
                    )
                    break
                except Exception as exc:
                    if client.last_call_metadata:
                        write_json_atomic(
                            call_log_root
                            / f"{document_key}.batch_{batch_number}.attempt_{attempt}.json",
                            client.last_call_metadata,
                        )
                    if client.last_raw_output:
                        raw_path = (
                            call_log_root
                            / f"{document_key}.batch_{batch_number}.attempt_{attempt}.raw.txt"
                        )
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
                        candidates_per_batch,
                    )
                    request_images = []
            assert batch is not None
            write_json_atomic(
                call_log_root / f"{document_key}.batch_{batch_number}.json",
                client.last_call_metadata,
            )
            response_id = client.last_call_metadata.get("response_id")
            if len(batch.candidates) != candidates_per_batch:
                raise ValueError(
                    f"Generator returned {len(batch.candidates)} candidates for "
                    f"{document.document_id} batch {batch_number}; expected "
                    f"{candidates_per_batch}"
                )
            returned_types = [draft.task.primary_evidence_type.value for draft in batch.candidates]
            if returned_types != document_requested_types:
                raise ValueError(
                    f"Generator returned primary evidence types {returned_types} for "
                    f"{document.document_id} batch {batch_number}; required "
                    f"{document_requested_types}"
                )
            for local_index, draft in enumerate(batch.candidates):
                if profile not in draft.task.supported_input_profiles:
                    raise ValueError(
                        f"Generator marked candidate {local_index} unsupported for its generation "
                        f"profile {profile.value}"
                    )
                if profile == InputProfile.text_only and draft.task.requires_visual_evidence:
                    raise ValueError("A text_only candidate cannot require visual evidence")
                candidate_index = batch_index * candidates_per_batch + local_index
                candidate = GeneratedCandidate(
                    sample_id=_sample_id(document.document_id, candidate_index, prompt_version),
                    document_id=document.document_id,
                    document_view_id=package.document_view_id,
                    input_profile=profile,
                    task=draft.task,
                    rubric=draft.rubric,
                    generator_model=config.models.generator.model,
                    generator_prompt_version=prompt_version,
                    generator_response_id=response_id,
                )
                generated.append(candidate)
                existing_for_document.append(candidate)
            write_jsonl_atomic(config.paths.generated, generated)
    if not config.paths.generated.exists():
        write_jsonl_atomic(config.paths.generated, generated)
    return generated
