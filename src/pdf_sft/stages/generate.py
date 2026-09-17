"""Evidence-first candidate generation using the configured OpenAI model."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_json_atomic, write_jsonl_atomic
from pdf_sft.llm import StructuredModelClient
from pdf_sft.schemas import DocumentRecord, GeneratedCandidate, GenerationBatchDraft
from pdf_sft.security import ensure_training_path_allowed

PROMPT_VERSION = "generator_v0"


def _sample_id(document_id: str, index: int, prompt_version: str) -> str:
    digest = hashlib.sha256(f"{document_id}\0{index}\0{prompt_version}".encode()).hexdigest()[:20]
    return f"pdfsft_{digest}"


def run_generate(
    config: AppConfig,
    prompt_path: Path,
    *,
    limit: int | None = None,
    overwrite: bool = False,
) -> list[GeneratedCandidate]:
    prompt_template = prompt_path.read_text(encoding="utf-8")
    prompt = prompt_template.format(candidate_count=config.generation.candidates_per_document)
    client = StructuredModelClient(config.models.generator)
    generated = (
        []
        if overwrite
        else [
            GeneratedCandidate.model_validate(payload)
            for payload in read_jsonl(config.paths.generated)
        ]
    )
    completed_document_ids = {candidate.document_id for candidate in generated}
    processed = 0
    for payload in read_jsonl(config.paths.documents):
        document = DocumentRecord.model_validate(payload)
        if document.document_id in completed_document_ids:
            continue
        if limit is not None and processed >= limit:
            break
        processed += 1
        pdf_path = ensure_training_path_allowed(document.pdf_path, config.security)
        document_key = document.document_id.split(":", 1)[-1]
        call_log_root = config.paths.logs / "api" / config.run_id / "generate"
        try:
            batch = client.generate(
                prompt=prompt,
                output_type=GenerationBatchDraft,
                pdf_path=pdf_path,
            )
        except Exception:
            if client.last_call_metadata:
                write_json_atomic(call_log_root / f"{document_key}.json", client.last_call_metadata)
            if client.last_raw_output:
                raw_path = call_log_root / f"{document_key}.raw.txt"
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(client.last_raw_output, encoding="utf-8")
            raise
        write_json_atomic(call_log_root / f"{document_key}.json", client.last_call_metadata)
        response_id = client.last_call_metadata.get("response_id")
        if len(batch.candidates) != config.generation.candidates_per_document:
            raise ValueError(
                f"Generator returned {len(batch.candidates)} candidates for "
                f"{document.document_id}; "
                f"expected {config.generation.candidates_per_document}"
            )
        for index, draft in enumerate(batch.candidates):
            generated.append(
                GeneratedCandidate(
                    sample_id=_sample_id(document.document_id, index, PROMPT_VERSION),
                    document_id=document.document_id,
                    task=draft.task,
                    rubric=draft.rubric,
                    generator_model=config.models.generator.model,
                    generator_prompt_version=PROMPT_VERSION,
                    generator_response_id=response_id,
                )
            )
        completed_document_ids.add(document.document_id)
        write_jsonl_atomic(config.paths.generated, generated)
    if not config.paths.generated.exists():
        write_jsonl_atomic(config.paths.generated, generated)
    return generated
