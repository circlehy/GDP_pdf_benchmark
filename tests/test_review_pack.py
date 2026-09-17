from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from pdf_sft.config import load_config
from pdf_sft.io import write_json_atomic
from pdf_sft.schemas import BoundingBox, GeneratedCandidate, ParsedBlock, ParsedDocument, ParsedPage
from pdf_sft.stages.review_pack import _bbox_review_assets, _candidate_markdown
from pdf_sft.stages.verify import verify_candidate_static


def _page_image(path: Path, label: str) -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), label)
    page.get_pixmap(alpha=False).save(path)
    document.close()


def test_review_pack_writes_non_mutating_bbox_repair_artifacts(
    valid_candidate: GeneratedCandidate,
    tmp_path: Path,
) -> None:
    config = load_config(Path("configs/runs/smoke_test.yaml"))
    excerpt = "compressor pressure ratio reaches 42 at the design point"
    node = valid_candidate.task.evidence_graph.nodes[0]
    node.excerpt = excerpt
    node.bbox = BoundingBox(x0=0.05, y0=0.05, x1=0.45, y1=0.20)
    page_1_image = tmp_path / "page_1.png"
    page_2_image = tmp_path / "page_2.png"
    _page_image(page_1_image, "Page one")
    _page_image(page_2_image, "Page two")
    parsed = ParsedDocument(
        document_id="sha256:test",
        parser="test",
        parser_version="1",
        dpi=144,
        page_count=2,
        pages=[
            ParsedPage(
                page_number=1,
                width_points=612,
                height_points=792,
                image_path=page_1_image,
                extracted_text=excerpt,
                extracted_text_chars=len(excerpt),
                native_text=excerpt,
                native_text_chars=len(excerpt),
                needs_ocr=False,
                blocks=[
                    ParsedBlock(
                        block_id="wrong-region",
                        kind="text",
                        bbox=BoundingBox(x0=0.05, y0=0.05, x1=0.45, y1=0.20),
                        text="unrelated introduction",
                        reading_order=0,
                    ),
                    ParsedBlock(
                        block_id="right-region",
                        kind="text",
                        bbox=BoundingBox(x0=0.50, y0=0.50, x1=0.95, y1=0.70),
                        text=excerpt,
                        reading_order=1,
                    ),
                ],
            ),
            ParsedPage(
                page_number=2,
                width_points=612,
                height_points=792,
                image_path=page_2_image,
                extracted_text="controlling exception",
                extracted_text_chars=21,
                native_text="controlling exception",
                native_text_chars=21,
                needs_ocr=False,
                blocks=[],
            ),
        ],
    )
    record = verify_candidate_static(valid_candidate, parsed, config)
    output_root = tmp_path / "review_pack"

    suggestions, crop_assets, suggestions_path = _bbox_review_assets(
        record, parsed, config, output_root
    )

    assert len(suggestions) == 1
    assert suggestions[0].suggested_bbox == BoundingBox(x0=0.50, y0=0.50, x1=0.95, y1=0.70)
    assert crop_assets["e1"]["original"].exists()
    assert crop_assets["e1"]["suggested"].exists()
    payload = json.loads(suggestions_path.read_text(encoding="utf-8"))
    assert not payload["mutation_applied"]
    assert payload["suggestions"][0]["node_id"] == "e1"
    decisions = json.loads(
        (suggestions_path.parent / "bbox_repair_decisions.json").read_text(encoding="utf-8")
    )
    assert decisions["decisions"][0]["decision"] == "pending"
    sample_decision = json.loads(
        (suggestions_path.parent / "sample_review_decision.json").read_text(encoding="utf-8")
    )
    assert sample_decision["decision"] == "pending"
    assert not sample_decision["checklist"]["gold_answer_verified"]
    decisions["decisions"][0]["decision"] = "accepted"
    write_json_atomic(suggestions_path.parent / "bbox_repair_decisions.json", decisions)
    _bbox_review_assets(record, parsed, config, output_root)
    preserved = json.loads(
        (suggestions_path.parent / "bbox_repair_decisions.json").read_text(encoding="utf-8")
    )
    assert preserved["decisions"][0]["decision"] == "accepted"
    assert node.bbox == BoundingBox(x0=0.05, y0=0.05, x1=0.45, y1=0.20)

    markdown = _candidate_markdown(
        record,
        parsed,
        tmp_path / "source.pdf",
        suggestions,
        crop_assets,
        suggestions_path,
    )
    assert "Original crop" in markdown
    assert "Suggested crop" in markdown
    assert "Accept suggested bbox" in markdown
    assert "c1: The adjusted value is 90." in markdown
