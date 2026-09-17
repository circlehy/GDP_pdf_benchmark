"""Render PDF pages and extract native text blocks with normalized coordinates."""

from __future__ import annotations

import pymupdf

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

    with pymupdf.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf):
            page_number = page_index + 1
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
                    native_text=native_text,
                    native_text_chars=len(native_text.strip()),
                    needs_ocr=(
                        len(native_text.strip()) < config.parse.native_text_min_chars_per_page
                    ),
                    blocks=blocks,
                )
            )

    parsed = ParsedDocument(
        document_id=record.document_id,
        parser="pymupdf",
        parser_version=pymupdf.__version__,
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
