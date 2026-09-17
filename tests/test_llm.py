from __future__ import annotations

from types import SimpleNamespace

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
