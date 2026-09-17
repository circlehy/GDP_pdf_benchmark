"""Stage run manifests for reproducibility and failure recovery."""

from __future__ import annotations

import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pdf_sft.io import write_json_atomic
from pdf_sft.schemas import StageRunManifest, utc_now


@contextmanager
def stage_manifest(
    *,
    run_id: str,
    stage: str,
    config_path: Path,
    log_root: Path,
    input_paths: list[Path],
    output_paths: list[Path],
) -> Iterator[StageRunManifest]:
    manifest = StageRunManifest(
        run_id=run_id,
        stage=stage,
        status="running",
        started_at=utc_now(),
        config_path=config_path.resolve(),
        input_paths=[path.resolve() for path in input_paths],
        output_paths=[path.resolve() for path in output_paths],
    )
    path = log_root / "stages" / run_id / f"{stage}.json"
    write_json_atomic(path, manifest)
    try:
        yield manifest
    except Exception as exc:
        manifest.status = "failed"
        manifest.completed_at = utc_now()
        manifest.errors.append(
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        write_json_atomic(path, manifest)
        raise
    else:
        manifest.status = "completed"
        manifest.completed_at = utc_now()
        write_json_atomic(path, manifest)
