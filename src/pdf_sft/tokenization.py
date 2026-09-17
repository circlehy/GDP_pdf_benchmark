"""Exact text-token accounting backed by a local Hugging Face tokenizer."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from tokenizers import Tokenizer


def tokenizer_json_path(tokenizer_path: Path) -> Path:
    """Resolve either a tokenizer directory or a direct tokenizer.json path."""

    path = tokenizer_path.resolve()
    candidate = path / "tokenizer.json" if path.is_dir() else path
    if not candidate.is_file():
        raise FileNotFoundError(f"Tokenizer JSON does not exist: {candidate}")
    return candidate


@lru_cache(maxsize=4)
def _load_tokenizer(path: str) -> Tokenizer:
    return Tokenizer.from_file(path)


@lru_cache(maxsize=4)
def _tokenizer_fingerprint(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def tokenizer_label(tokenizer_path: Path) -> str:
    path = tokenizer_json_path(tokenizer_path)
    name = path.parent.name if path.name == "tokenizer.json" else path.stem
    return f"hf-fast:{name}:sha256:{_tokenizer_fingerprint(str(path))}"


def count_text_tokens(text: str, tokenizer_path: Path) -> int:
    """Count content tokens without inventing an unavailable chat template."""

    path = tokenizer_json_path(tokenizer_path)
    return len(_load_tokenizer(str(path)).encode(text, add_special_tokens=False).ids)
