"""Build the canonical AA-aligned page IR with LiteParse text and page renders."""

from __future__ import annotations

from importlib.metadata import version

import pymupdf
from liteparse import LiteParse

from pdf_sft.config import AppConfig
from pdf_sft.io import read_jsonl, write_json_atomic
from pdf_sft.schemas import (
    BoundingBox,
    DocumentRecord,
    ParsedBlock,
    ParsedDocument,
    ParsedPage,
)
from pdf_sft.security import ensure_training_path_allowed


def _normalized_bbox(raw: tuple[float, float, float, float], width: float, height: float):
    x0, y0, x1, y1 = raw
    x0 = min(1.0, max(0.0, x0 / width))
    y0 = min(1.0, max(0.0, y0 / height))
    x1 = min(1.0, max(0.0, x1 / width))
    y1 = min(1.0, max(0.0, y1 / height))
    if x1 <= x0 or y1 <= y0:
        return None
    return BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


def parse_document(record: DocumentRecord, config: AppConfig) -> ParsedDocument:
    pdf_path = ensure_training_path_allowed(record.pdf_path, config.security)
    document_key = record.document_id.split(":", 1)[-1]
    output_root = config.paths.parsed / document_key
    output_root.mkdir(parents=True, exist_ok=True)
    parsed_pages: list[ParsedPage] = []
    zoom = config.parse.dpi / 72.0

    text_parser = LiteParse(
        ocr_enabled=config.parse.ocr_enabled,
        ocr_language=config.parse.ocr_language,
        tessdata_path=(
            str(config.parse.tessdata_path) if config.parse.tessdata_path is not None else None
        ),
        dpi=float(config.parse.dpi),
        output_format="text",
        quiet=True,
        num_workers=config.parse.num_workers,
    )
    complexity = text_parser.is_complex(pdf_path)
    liteparse_result = text_parser.parse(pdf_path)
    liteparse_pages = {page.page_num: page for page in liteparse_result.pages}
    needs_ocr_by_page = {page.page_number: page.needs_ocr for page in complexity}

    with pymupdf.open(pdf_path) as pdf:
        if len(liteparse_pages) != len(pdf):
            raise ValueError(
                f"LiteParse returned {len(liteparse_pages)} pages for {record.document_id}; "
                f"PDF contains {len(pdf)} pages"
            )
        for page_index, page in enumerate(pdf):
            page_number = page_index + 1
            liteparse_page = liteparse_pages.get(page_number)
            if liteparse_page is None:
                raise ValueError(f"LiteParse omitted page {page_number} for {record.document_id}")
            image_path = output_root / f"page_{page_number:04d}.png"
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            pixmap.save(image_path)
            native_text = page.get_text("text")
            blocks: list[ParsedBlock] = []
            for order, block in enumerate(page.get_text("blocks")):
                bbox = _normalized_bbox(block[:4], page.rect.width, page.rect.height)
                if bbox is None:
                    continue
                block_type = int(block[6]) if len(block) > 6 else 0
                blocks.append(
                    ParsedBlock(
                        block_id=f"p{page_number}_b{order}",
                        kind="text" if block_type == 0 else "image",
                        bbox=bbox,
                        text=str(block[4]).strip() if block_type == 0 else "",
                        reading_order=order,
                    )
                )
            parsed_pages.append(
                ParsedPage(
                    page_number=page_number,
                    width_points=page.rect.width,
                    height_points=page.rect.height,
                    image_path=image_path.resolve(),
                    extracted_text=liteparse_page.text,
                    extracted_text_chars=len(liteparse_page.text.strip()),
                    native_text=native_text,
                    native_text_chars=len(native_text.strip()),
                    needs_ocr=needs_ocr_by_page.get(
                        page_number,
                        len(native_text.strip()) < config.parse.native_text_min_chars_per_page,
                    ),
                    blocks=blocks,
                )
            )

    parsed = ParsedDocument(
        document_id=record.document_id,
        schema_version="0.2",
        parser="liteparse",
        parser_version=version("liteparse"),
        renderer="pymupdf",
        renderer_version=pymupdf.__version__,
        ocr_enabled=config.parse.ocr_enabled,
        ocr_language=config.parse.ocr_language,
        dpi=config.parse.dpi,
        page_count=len(parsed_pages),
        pages=parsed_pages,
    )
    write_json_atomic(output_root / "document.json", parsed)
    return parsed


def run_parse(config: AppConfig) -> list[ParsedDocument]:
    ensure_training_path_allowed(config.paths.documents, config.security)
    parsed = [
        parse_document(DocumentRecord.model_validate(payload), config)
        for payload in read_jsonl(config.paths.documents)
    ]
    return parsed
