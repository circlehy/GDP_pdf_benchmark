#!/usr/bin/env python3
"""Download an immutable, eval-only snapshot of surgeai/GDP.pdf."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

REPO_ID = "surgeai/GDP.pdf"
REPO_TYPE = "dataset"
DEFAULT_OUTPUT = Path("benchmarks/gdp_pdf")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Eval-only output directory (default: benchmarks/gdp_pdf)",
    )
    parser.add_argument(
        "--revision",
        default="main",
        help="Branch, tag, or commit to resolve before download (default: main)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    source = output / "source"
    output.mkdir(parents=True, exist_ok=True)

    api = HfApi()
    info = api.dataset_info(REPO_ID, revision=args.revision)
    resolved_revision = info.sha

    snapshot_download(
        repo_id=REPO_ID,
        repo_type=REPO_TYPE,
        revision=resolved_revision,
        local_dir=source,
    )

    required_paths = [source / "README.md", source / "data.parquet", source / "pdfs"]
    missing_paths = [str(path) for path in required_paths if not path.exists()]
    if missing_paths:
        raise RuntimeError(f"Incomplete snapshot; missing required paths: {missing_paths}")

    pdf_paths = sorted((source / "pdfs").glob("*.pdf"))
    if len(pdf_paths) != 100:
        raise RuntimeError(
            f"Expected 100 GDP.pdf documents at this revision, found {len(pdf_paths)}"
        )

    files = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or ".cache" in path.parts:
            continue
        files.append(
            {
                "path": path.relative_to(source).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    manifest = {
        "asset_class": "eval_only_benchmark",
        "training_allowed": False,
        "repo_id": REPO_ID,
        "repo_type": REPO_TYPE,
        "requested_revision": args.revision,
        "resolved_revision": resolved_revision,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_directory": str(source),
        "pdf_count": len(pdf_paths),
        "file_count": len(files),
        "total_size_bytes": sum(item["size_bytes"] for item in files),
        "files": files,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Downloaded {len(files)} files from {REPO_ID}@{resolved_revision}")
    print(f"PDF count: {len(pdf_paths)}")
    print(f"Total bytes: {manifest['total_size_bytes']}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
