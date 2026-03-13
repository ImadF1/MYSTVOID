from __future__ import annotations

import json
from typing import Any

from ollama import Client

from agent.schemas import ModelDecision


class OllamaJSONClient:
    def __init__(self, host: str) -> None:
        self.client = Client(host=host)

    def decide(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> ModelDecision:
        response = self.client.chat(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, *messages],
            stream=False,
            format=ModelDecision.model_json_schema(),
            options={"temperature": 0.1},
        )
        content = self._extract_content(response)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Model returned invalid JSON: {content}") from exc
        return ModelDecision.model_validate(payload)

    def _extract_content(self, response: Any) -> str:
        if hasattr(response, "message") and getattr(response.message, "content", None) is not None:
            return str(response.message.content)
        if isinstance(response, dict):
            return str(response.get("message", {}).get("content", ""))
        raise RuntimeError(f"Unsupported Ollama response type: {type(response)!r}")


def list_installed_models(host: str) -> list[str]:
    client = Client(host=host)
    response = client.list()

    if hasattr(response, "models"):
        raw_models = getattr(response, "models")
    elif isinstance(response, dict):
        raw_models = response.get("models", [])
    else:
        raise RuntimeError(f"Unsupported Ollama list response type: {type(response)!r}")

    names: list[str] = []
    for item in raw_models or []:
        if isinstance(item, dict):
            name = item.get("model") or item.get("name")
        else:
            name = getattr(item, "model", None) or getattr(item, "name", None)
        if name:
            names.append(str(name))

    deduped = sorted(dict.fromkeys(names))
    return deduped
