"""Freeze document views and build target-visible text/multimodal packages."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pymupdf

from pdf_sft.config import AppConfig, DocumentViewOverrideConfig
from pdf_sft.io import read_jsonl, write_json_atomic
from pdf_sft.schemas import (
    DocumentRecord,
    DocumentScope,
    DocumentView,
    InputProfile,
    PageRange,
    ParsedDocument,
    TargetInputPackage,
    TokenAccounting,
)
from pdf_sft.security import ensure_training_path_allowed
from pdf_sft.tokenization import count_text_tokens, tokenizer_label


class DocumentViewBudgetError(ValueError):
    """The full or explicitly bounded view does not fit the configured target context."""


def _document_key(document_id: str) -> str:
    return document_id.split(":", 1)[-1]


def _parse_ranges(
    override: DocumentViewOverrideConfig, source_page_count: int
) -> tuple[list[PageRange], list[int]]:
    page_numbers: list[int] = []
    for raw_range in override.included_page_ranges:
        parts = raw_range.strip().split("-", 1)
        try:
            start = int(parts[0])
            end = int(parts[1]) if len(parts) == 2 else start
        except ValueError as exc:
            raise ValueError(f"Invalid page range {raw_range!r}") from exc
        if start < 1 or end < start or end > source_page_count:
            raise ValueError(
                f"Page range {raw_range!r} is outside document pages 1-{source_page_count}"
            )
        page_numbers.extend(range(start, end + 1))
    page_numbers = sorted(set(page_numbers))
    if not page_numbers:
        raise ValueError("A document view override cannot be empty")
    ranges: list[PageRange] = []
    range_start = previous = page_numbers[0]
    for page in page_numbers[1:]:
        if page != previous + 1:
            ranges.append(PageRange(start=range_start, end=previous))
            range_start = page
        previous = page
    ranges.append(PageRange(start=range_start, end=previous))
    return ranges, page_numbers


def _view_for(parsed: ParsedDocument, config: AppConfig) -> DocumentView:
    key = _document_key(parsed.document_id)
    override = config.document_view.overrides.get(parsed.document_id)
    if override is None:
        override = config.document_view.overrides.get(key)
    if override is None:
        page_numbers = list(range(1, parsed.page_count + 1))
        ranges = [PageRange(start=1, end=parsed.page_count)]
        scope = DocumentScope.full_pdf
        reason = None
    else:
        ranges, page_numbers = _parse_ranges(override, parsed.page_count)
        scope = (
            DocumentScope.full_pdf
            if page_numbers == list(range(1, parsed.page_count + 1))
            else DocumentScope.bounded
        )
        reason = override.reason if scope == DocumentScope.bounded else None

    digest = hashlib.sha256(
        f"{parsed.document_id}\0{','.join(map(str, page_numbers))}".encode()
    ).hexdigest()[:16]
    suffix = "full" if scope == DocumentScope.full_pdf else f"bounded-{digest}"
    return DocumentView(
        document_view_id=f"{parsed.document_id}:{suffix}",
        document_id=parsed.document_id,
        scope=scope,
        source_page_count=parsed.page_count,
        included_page_ranges=ranges,
        included_page_numbers=page_numbers,
        truncation_reason=reason,
    )


def format_document_text(parsed: ParsedDocument, page_numbers: list[int]) -> str:
    by_page = {page.page_number: page for page in parsed.pages}
    chunks: list[str] = []
    for page_number in page_numbers:
        page = by_page[page_number]
        chunks.append(
            f"[Page {page_number}]\n{page.extracted_text.strip()}\n[End Page {page_number}]"
        )
    text = "\n\n".join(chunks).strip()
    if not text:
        raise ValueError(f"LiteParse produced no target-visible text for {parsed.document_id}")
    return text


def _render_at_dpi(
    document: DocumentRecord,
    parsed: ParsedDocument,
    page_numbers: list[int],
    dpi: int,
    config: AppConfig,
) -> list[Path]:
    if dpi == parsed.dpi:
        by_page = {page.page_number: page.image_path for page in parsed.pages}
        return [by_page[page].resolve() for page in page_numbers]

    pdf_path = ensure_training_path_allowed(document.pdf_path, config.security)
    output_root = config.paths.parsed / _document_key(document.document_id) / f"render_{dpi}dpi"
    output_root.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    paths: list[Path] = []
    with pymupdf.open(pdf_path) as pdf:
        for page_number in page_numbers:
            output_path = output_root / f"page_{page_number:04d}.png"
            if not output_path.exists():
                pixmap = pdf[page_number - 1].get_pixmap(
                    matrix=pymupdf.Matrix(zoom, zoom), alpha=False
                )
                pixmap.save(output_path)
            paths.append(output_path.resolve())
    return paths


def _provisional_accounting(
    parsed: ParsedDocument,
    view: DocumentView,
    profile: InputProfile,
    document_text: str,
    image_dpi: int | None,
    config: AppConfig,
) -> TokenAccounting:
    budget = config.context_budget
    if budget.text_tokenizer_path is not None:
        text_tokens = count_text_tokens(document_text, budget.text_tokenizer_path)
        text_counter = tokenizer_label(budget.text_tokenizer_path)
        text_tokens_exact = True
    else:
        text_tokens = math.ceil(len(document_text) / budget.provisional_chars_per_token)
        text_counter = f"provisional:chars/{budget.provisional_chars_per_token:g}"
        text_tokens_exact = False
    image_tokens = 0
    if profile == InputProfile.multimodal:
        assert image_dpi is not None
        by_page = {page.page_number: page for page in parsed.pages}
        megapixels = sum(
            (by_page[number].width_points * image_dpi / 72.0)
            * (by_page[number].height_points * image_dpi / 72.0)
            / 1_000_000
            for number in view.included_page_numbers
        )
        image_tokens = math.ceil(megapixels * budget.provisional_image_tokens_per_megapixel)
    estimated_input = (
        text_tokens
        + image_tokens
        + budget.question_reserve_tokens
        + budget.system_prompt_reserve_tokens
    )
    utilization = estimated_input / budget.model_context_tokens
    fits = (
        utilization <= budget.maximum_input_utilization
        and estimated_input + budget.minimum_output_and_safety_reserve_tokens
        <= budget.model_context_tokens
    )
    return TokenAccounting(
        tokenizer_or_estimator=text_counter,
        vision_processor=(
            f"provisional:{budget.provisional_image_tokens_per_megapixel}/megapixel"
            if profile == InputProfile.multimodal
            else None
        ),
        exact=False,
        text_tokens_exact=text_tokens_exact,
        image_tokens_exact=profile == InputProfile.text_only,
        document_text_tokens=text_tokens,
        page_image_tokens=image_tokens,
        question_reserve_tokens=budget.question_reserve_tokens,
        system_prompt_reserve_tokens=budget.system_prompt_reserve_tokens,
        answer_and_safety_reserve_tokens=budget.minimum_output_and_safety_reserve_tokens,
        estimated_input_tokens=estimated_input,
        context_window_tokens=budget.model_context_tokens,
        input_utilization=utilization,
        fits_context=fits,
    )


def build_input_package(
    document: DocumentRecord,
    parsed: ParsedDocument,
    config: AppConfig,
    profile: InputProfile,
) -> tuple[DocumentView, TargetInputPackage]:
    view = _view_for(parsed, config)
    document_text = format_document_text(parsed, view.included_page_numbers)
    image_paths: list[Path] = []
    selected_dpi: int | None = None

    dpi_candidates: list[int | None]
    if profile == InputProfile.text_only:
        dpi_candidates = [None]
    else:
        dpi_candidates = [
            dpi
            for dpi in (config.target_input.page_image_dpi, 120, 96, 72)
            if config.target_input.minimum_page_image_dpi
            <= dpi
            <= config.target_input.page_image_dpi
        ]
        dpi_candidates = list(dict.fromkeys(dpi_candidates))

    accounting: TokenAccounting | None = None
    for dpi in dpi_candidates:
        candidate = _provisional_accounting(parsed, view, profile, document_text, dpi, config)
        accounting = candidate
        selected_dpi = dpi
        if candidate.fits_context:
            break
    assert accounting is not None
    if not accounting.fits_context:
        scope_hint = (
            "Choose semantically complete page ranges in document_view.overrides before "
            "generation; the pipeline will not silently truncate an existing task."
        )
        raise DocumentViewBudgetError(
            f"{parsed.document_id} does not fit {profile.value} at the minimum allowed image "
            f"DPI; estimated input utilization={accounting.input_utilization:.3f}. {scope_hint}"
        )

    if profile == InputProfile.multimodal:
        assert selected_dpi is not None
        image_paths = _render_at_dpi(
            document,
            parsed,
            view.included_page_numbers,
            selected_dpi,
            config,
        )

    package_digest = hashlib.sha256(
        f"{view.document_view_id}\0{profile.value}\0{selected_dpi}".encode()
    ).hexdigest()[:20]
    package = TargetInputPackage(
        package_id=f"input_{package_digest}",
        document_view_id=view.document_view_id,
        document_id=view.document_id,
        profile=profile,
        page_image_dpi=selected_dpi,
        page_numbers=view.included_page_numbers,
        text_empty_page_numbers=[
            page.page_number
            for page in parsed.pages
            if page.page_number in view.included_page_numbers and not page.extracted_text.strip()
        ],
        document_text=document_text,
        page_image_paths=image_paths,
        token_accounting=accounting,
    )
    return view, package


def run_build_input(
    config: AppConfig, *, profile: InputProfile | None = None
) -> list[TargetInputPackage]:
    selected_profile = profile or InputProfile(config.target_input.profile)
    documents = {
        record.document_id: record
        for record in (
            DocumentRecord.model_validate(payload) for payload in read_jsonl(config.paths.documents)
        )
    }
    packages: list[TargetInputPackage] = []
    for document_dir in sorted(config.paths.parsed.iterdir()):
        parsed_path = document_dir / "document.json"
        if not parsed_path.exists():
            continue
        parsed = ParsedDocument.model_validate_json(parsed_path.read_text(encoding="utf-8"))
        document = documents.get(parsed.document_id)
        if document is None:
            raise ValueError(f"Missing document record for {parsed.document_id}")
        view, package = build_input_package(document, parsed, config, selected_profile)
        key = _document_key(parsed.document_id)
        write_json_atomic(config.paths.document_views / f"{key}.json", view)
        write_json_atomic(
            config.paths.input_packages / selected_profile.value / f"{key}.json", package
        )
        packages.append(package)
    return packages


def load_input_packages(config: AppConfig, profile: InputProfile) -> dict[str, TargetInputPackage]:
    root = config.paths.input_packages / profile.value
    if not root.exists():
        raise FileNotFoundError(
            f"Input packages do not exist for {profile.value}; run pdf-sft build-input first"
        )
    packages: dict[str, TargetInputPackage] = {}
    for path in sorted(root.glob("*.json")):
        package = TargetInputPackage.model_validate_json(path.read_text(encoding="utf-8"))
        packages[package.document_id] = package
    return packages
