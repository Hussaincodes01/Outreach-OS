"""Provider API keys supplied by the operator through environment / .env.

This is a single-user build: one workspace, one operator, so keys configured
for the process belong to that operator. Values come from the process
environment first (Docker `env_file`), then from the `.env` file Settings
reads (native runs, where .env is not exported into os.environ).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def _dotenv_path() -> Path:
    return Path(".env")


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str | None]:
    path = _dotenv_path()
    return dict(dotenv_values(path)) if path.is_file() else {}


def reset_env_cache() -> None:
    """Forget the cached `.env` contents. Call after changing `_dotenv_path`
    (tests) or after the file could plausibly have changed on disk."""
    _dotenv.cache_clear()


def env_value(name: str) -> str | None:
    """Look up `name`, process environment first, then `.env`.

    An empty string counts as unset — that is how an operator clears a key
    without deleting the line from `.env`.
    """
    value = os.environ.get(name)
    if value is None:
        value = _dotenv().get(name)
    value = (value or "").strip()
    return value or None


def _prefix(name: str) -> str:
    return _NON_ALNUM.sub("_", name).upper()


def provider_key_var(provider: str) -> str:
    """e.g. `openai` -> `OPENAI_API_KEY`, `together-ai` -> `TOGETHER_AI_API_KEY`."""
    return f"{_prefix(provider)}_API_KEY"


def provider_base_var(provider: str) -> str:
    """e.g. `ollama` -> `OLLAMA_API_BASE`."""
    return f"{_prefix(provider)}_API_BASE"


def scraping_key_var(kind: str) -> str:
    """e.g. `serper` -> `SERPER_API_KEY`."""
    return f"{_prefix(kind)}_API_KEY"


__all__ = [
    "env_value",
    "provider_base_var",
    "provider_key_var",
    "reset_env_cache",
    "scraping_key_var",
]
