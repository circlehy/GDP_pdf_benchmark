"""Turn a reviewed source manifest into normalized document candidates."""

from __future__ import annotations

import hashlib

import yaml

from pdf_sft.config import AppConfig
from pdf_sft.io import write_jsonl_atomic
from pdf_sft.schemas import DocumentCandidate, LicenseRecord, SourceManifest, utc_now
from pdf_sft.security import validate_source_url


def _candidate_id(source_id: str, source_url: str) -> str:
    digest = hashlib.sha256(f"{source_id}\0{source_url}".encode()).hexdigest()[:20]
    return f"candidate_{digest}"


def run_discover(config: AppConfig) -> list[DocumentCandidate]:
    raw = yaml.safe_load(config.source_manifest.read_text(encoding="utf-8")) or {}
    source = SourceManifest.model_validate(raw)
    candidates: list[DocumentCandidate] = []
    seen_urls: set[str] = set()
    for document in source.documents:
        validate_source_url(document.source_url, config.security)
        if document.source_url in seen_urls:
            continue
        seen_urls.add(document.source_url)
        candidates.append(
            DocumentCandidate(
                candidate_id=_candidate_id(source.source_id, document.source_url),
                source_id=source.source_id,
                source_url=document.source_url,
                title=document.title,
                publisher=document.publisher,
                discovered_at=utc_now(),
                license=LicenseRecord(
                    status=document.license_status,
                    license_id=document.license_id,
                    evidence_url=document.license_evidence_url,
                    third_party_material_status=document.third_party_material_status,
                    review_notes=document.review_notes,
                    reviewed_at=utc_now(),
                ),
            )
        )
    write_jsonl_atomic(config.paths.discovery, candidates)
    return candidates
