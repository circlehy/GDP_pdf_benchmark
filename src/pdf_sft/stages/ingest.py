"""Download approved PDFs, validate bytes, and create immutable document records."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_jsonl_atomic
from pdf_sft.schemas import DocumentCandidate, DocumentRecord, LicenseStatus, utc_now
from pdf_sft.security import ensure_training_path_allowed, validate_source_url


def _download_pdf(url: str, destination: Path, *, max_bytes: int) -> tuple[str, int]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".pdf.part")
    digest = hashlib.sha256()
    size = 0
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"PDF exceeds configured limit of {max_bytes} bytes")
                    digest.update(chunk)
                    stream.write(chunk)
        with temporary.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError(f"Downloaded content is not a PDF: {url}")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), size


def run_ingest(config: AppConfig) -> list[DocumentRecord]:
    ensure_training_path_allowed(config.paths.discovery, config.security)
    ensure_training_path_allowed(config.paths.raw_pdfs, config.security)
    records: list[DocumentRecord] = []
    for payload in read_jsonl(config.paths.discovery):
        candidate = DocumentCandidate.model_validate(payload)
        if candidate.license.status != LicenseStatus.approved:
            continue
        validate_source_url(candidate.source_url, config.security)
        temporary_name = f"{candidate.candidate_id}.pdf"
        initial_path = config.paths.raw_pdfs / temporary_name
        content_hash, size = _download_pdf(
            candidate.source_url,
            initial_path,
            max_bytes=config.security.max_pdf_bytes,
        )
        final_path = config.paths.raw_pdfs / f"{content_hash}.pdf"
        if final_path.exists():
            initial_path.unlink(missing_ok=True)
        else:
            initial_path.replace(final_path)
        records.append(
            DocumentRecord(
                document_id=f"sha256:{content_hash}",
                candidate_id=candidate.candidate_id,
                source_id=candidate.source_id,
                source_url=candidate.source_url,
                title=candidate.title,
                publisher=candidate.publisher,
                retrieved_at=utc_now(),
                content_sha256=content_hash,
                size_bytes=size,
                pdf_path=final_path.resolve(),
                license=candidate.license,
            )
        )
    write_jsonl_atomic(config.paths.documents, records)
    return records
