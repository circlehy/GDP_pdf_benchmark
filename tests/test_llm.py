from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from pdf_sft.config import ModelConfig
from pdf_sft.llm import StructuredModelClient, strict_json_schema


class Child(BaseModel):
    required_value: int
    optional_value: str | None = None


class Parent(BaseModel):
    child: Child
    optional_children: list[Child] | None = None


def test_strict_json_schema_requires_nullable_properties_recursively() -> None:
    schema = strict_json_schema(Parent)
    assert schema["required"] == ["child", "optional_children"]
    assert schema["additionalProperties"] is False
    child = schema["$defs"]["Child"]
    assert child["required"] == ["required_value", "optional_value"]
    assert child["additionalProperties"] is False


def test_responses_client_forwards_prompt_cache_key() -> None:
    captured: dict = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="resp_test",
                model="test-model",
                status="completed",
                incomplete_details=None,
                output_text='{"required_value": 1, "optional_value": null}',
                usage=None,
            )

    client = StructuredModelClient.__new__(StructuredModelClient)
    client.config = ModelConfig(
        provider="openai_responses",
        model="test-model",
        api_key_env="TEST_KEY",
        max_output_tokens=100,
    )
    client.client = SimpleNamespace(responses=FakeResponses())
    client.last_call_metadata = {}
    client.last_raw_output = None

    client.generate(
        prompt="test",
        output_type=Child,
        prompt_cache_key="stable-evidence-key",
    )
    assert captured["prompt_cache_key"] == "stable-evidence-key"


def test_chat_client_places_full_page_images_before_text(tmp_path: Path) -> None:
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                id="chat_test",
                model="test-vlm",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"required_value": 1, "optional_value": null}',
                            reasoning="checked",
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"synthetic-page-image")
    client = StructuredModelClient.__new__(StructuredModelClient)
    client.config = ModelConfig(
        provider="openai_compatible_chat",
        model="test-vlm",
        api_key_env="TEST_KEY",
        reasoning_effort="high",
        max_output_tokens=100,
        temperature=0.1,
        top_p=0.95,
    )
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    client.last_call_metadata = {}
    client.last_raw_output = None

    client.generate(prompt="question and full text", output_type=Child, image_paths=[image_path])

    content = captured["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[-1] == {"type": "text", "text": "question and full text"}
    assert captured["extra_body"] == {"reasoning_effort": "high"}
    assert captured["temperature"] == 0.1
    assert captured["top_p"] == 0.95
    assert client.last_call_metadata["finish_reason"] == "stop"
    assert client.last_call_metadata["reasoning_characters"] == 7


def test_chat_client_records_length_finish_before_empty_content_error() -> None:
    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                id="chat_length",
                model="test-vlm",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=None, reasoning="budget exhausted"),
                        finish_reason="length",
                    )
                ],
                usage=None,
            )

    client = StructuredModelClient.__new__(StructuredModelClient)
    client.config = ModelConfig(
        provider="openai_compatible_chat",
        model="test-vlm",
        api_key_env="TEST_KEY",
        max_output_tokens=100,
    )
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    client.last_call_metadata = {}
    client.last_raw_output = None

    with pytest.raises(ValueError, match="returned no structured content"):
        client.generate(prompt="test", output_type=Child)

    assert client.last_call_metadata["finish_reason"] == "length"
    assert client.last_call_metadata["output_characters"] == 0
    assert client.last_call_metadata["reasoning_characters"] == len("budget exhausted")
