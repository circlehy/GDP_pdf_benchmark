from pathlib import Path

from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace

from pdf_sft.tokenization import count_text_tokens, tokenizer_label


def _write_test_tokenizer(root: Path) -> Path:
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "hello": 1, "world": 2}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    root.mkdir(parents=True)
    tokenizer.save(str(root / "tokenizer.json"))
    return root


def test_exact_local_tokenizer_count_and_stable_label(tmp_path: Path) -> None:
    root = _write_test_tokenizer(tmp_path / "tokenizer")

    assert count_text_tokens("hello world hello", root) == 3
    assert tokenizer_label(root).startswith("hf-fast:tokenizer:sha256:")
