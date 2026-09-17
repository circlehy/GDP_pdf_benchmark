"""Structured model clients for OpenAI Responses and local compatible servers."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from pdf_sft.config import ModelConfig

OutputT = TypeVar("OutputT", bound=BaseModel)


class ModelConfigurationError(ValueError):
    pass


def strict_json_schema(model: type[BaseModel]) -> dict:
    """Make Pydantic output compatible with OpenAI strict Structured Outputs."""

    schema = model.model_json_schema()

    def normalize(value):
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                value["required"] = list(properties)
                value["additionalProperties"] = False
            for child in value.values():
                normalize(child)
        elif isinstance(value, list):
            for child in value:
                normalize(child)

    normalize(schema)
    return schema


def _data_url(path: Path, media_type: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


class StructuredModelClient:
    def __init__(self, config: ModelConfig):
        self.config = config
        api_key = os.environ.get(config.api_key_env, "").strip()
        if not api_key:
            raise ModelConfigurationError(
                f"Environment variable {config.api_key_env} is required for {config.model}"
            )
        self.client = OpenAI(api_key=api_key, base_url=config.base_url)
        self.last_call_metadata: dict = {}
        self.last_raw_output: str | None = None

    def generate(
        self,
        *,
        prompt: str,
        output_type: type[OutputT],
        pdf_path: Path | None = None,
        image_paths: list[Path] | None = None,
        prompt_cache_key: str | None = None,
    ) -> OutputT:
        if self.config.provider == "openai_responses":
            return self._responses_generate(
                prompt=prompt,
                output_type=output_type,
                pdf_path=pdf_path,
                image_paths=image_paths or [],
                prompt_cache_key=prompt_cache_key,
            )
        if self.config.provider == "openai_compatible_chat":
            if pdf_path is not None:
                raise ModelConfigurationError(
                    "Local chat-compatible clients require rendered page images, not PDF input"
                )
            return self._chat_generate(
                prompt=prompt,
                output_type=output_type,
                image_paths=image_paths or [],
            )
        raise ModelConfigurationError(f"Unsupported provider: {self.config.provider}")

    def _responses_generate(
        self,
        *,
        prompt: str,
        output_type: type[OutputT],
        pdf_path: Path | None,
        image_paths: list[Path],
        prompt_cache_key: str | None,
    ) -> OutputT:
        content: list[dict] = []
        if pdf_path is not None:
            content.append(
                {
                    "type": "input_file",
                    "filename": pdf_path.name,
                    "file_data": _data_url(pdf_path, "application/pdf"),
                }
            )
        for image_path in image_paths:
            content.append(
                {
                    "type": "input_image",
                    "image_url": _data_url(image_path, "image/png"),
                }
            )
        content.append({"type": "input_text", "text": prompt})
        kwargs = {
            "model": self.config.model,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": self.config.max_output_tokens,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": output_type.__name__,
                    "strict": True,
                    "schema": strict_json_schema(output_type),
                }
            },
        }
        if self.config.reasoning_effort:
            kwargs["reasoning"] = {"effort": self.config.reasoning_effort}
        if prompt_cache_key:
            kwargs["prompt_cache_key"] = prompt_cache_key
        response = self.client.responses.create(**kwargs)
        self.last_raw_output = response.output_text
        self.last_call_metadata = {
            "response_id": response.id,
            "model": response.model,
            "provider": self.config.provider,
            "status": response.status,
            "incomplete_details": (
                response.incomplete_details.model_dump(mode="json")
                if response.incomplete_details
                else None
            ),
            "output_characters": len(response.output_text),
            "usage": response.usage.model_dump(mode="json") if response.usage else None,
        }
        return output_type.model_validate_json(response.output_text)

    def _chat_generate(
        self,
        *,
        prompt: str,
        output_type: type[OutputT],
        image_paths: list[Path],
    ) -> OutputT:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for image_path in image_paths:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(image_path, "image/png")},
                }
            )
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=self.config.max_output_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": output_type.__name__,
                    "strict": True,
                    "schema": strict_json_schema(output_type),
                },
            },
        )
        raw = response.choices[0].message.content
        if not raw:
            raise ValueError(f"Model {self.config.model} returned no structured content")
        self.last_raw_output = raw
        self.last_call_metadata = {
            "response_id": response.id,
            "model": response.model,
            "provider": self.config.provider,
            "status": "completed",
            "incomplete_details": None,
            "output_characters": len(raw),
            "usage": response.usage.model_dump(mode="json") if response.usage else None,
        }
        return output_type.model_validate(json.loads(raw))
