from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class Settings:
    ollama_host: str
    default_model: str
    max_steps: int
    command_timeout_seconds: int
    max_file_chars: int


def get_settings() -> Settings:
    return Settings(
        ollama_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/"),
        default_model=os.getenv("OLLAMA_MODEL", "qwen2.5-coder:latest").strip() or "qwen2.5-coder:latest",
        max_steps=int(os.getenv("AGENT_MAX_STEPS", "8")),
        command_timeout_seconds=int(os.getenv("AGENT_COMMAND_TIMEOUT", "120")),
        max_file_chars=int(os.getenv("AGENT_MAX_FILE_CHARS", "30000")),
    )
