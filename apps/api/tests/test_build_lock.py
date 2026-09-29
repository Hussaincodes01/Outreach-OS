"""The API image must install exactly the locked dependency set."""
from __future__ import annotations

import pathlib
import re

API_DIR = pathlib.Path(__file__).resolve().parents[1]
REPO = API_DIR.parents[1]


def test_every_runtime_dependency_is_pinned_in_the_lock() -> None:
    lock = (API_DIR / "requirements.lock").read_text(encoding="utf-8")
    pinned = {
        m.group(1).lower().replace("_", "-")
        for m in re.finditer(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==", lock, re.MULTILINE)
    }
    for name in ("fastapi", "sqlalchemy", "litellm", "celery", "asyncpg", "gunicorn"):
        assert name in pinned, f"{name} not pinned in requirements.lock"


def test_dockerfile_installs_deps_before_copying_source() -> None:
    text = (REPO / "infra" / "docker" / "Dockerfile.api").read_text(encoding="utf-8")
    lock_install = text.index("requirements.lock")
    source_copy = text.index("COPY apps/api/src")
    assert lock_install < source_copy, "dependencies must be installed before the source is copied"
