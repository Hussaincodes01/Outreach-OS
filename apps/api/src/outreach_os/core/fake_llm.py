"""Deterministic offline LLM client — used when no provider API key is set.

This is the same code as `tests/fake_llm.py` but lives in the main package
so the runtime factory in `core/llm.py` can fall back to it. It returns
predictable JSON for niche/style/draft prompts and 1536-dim vectors derived
from a hash of the input — so a local dev run or the e2e demo still
produces a complete, end-to-end draft + trace.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from typing import Any

from outreach_os.core.llm import LLMResponse, LLMUsage


def _text_to_vec(text: str, dim: int = 1536) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    seed_int = struct.unpack(">I", h[:4])[0]
    out: list[float] = []
    for i in range(dim):
        v = (seed_int ^ (i * 0x9E3779B1)) & 0xFFFFFFFF
        out.append(((v / 0xFFFFFFFF) * 2.0) - 1.0)
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


class FakeLLMClient:
    """Deterministic, no-network LLMClient. Token counts are stable per
    call so tests can assert on usage."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 800,
        temperature: float = 0.7,
        timeout: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {"model": model, "messages": list(messages), "max_tokens": max_tokens}
        )
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if len(messages) > 1 else ""

        if "email body, plain text" in system or "personalised B2B cold-outreach" in system:
            first = user.split("LEAD:\n", 1)[-1].split("\n", 1)[0] if "LEAD:\n" in user else "there"
            text = json.dumps(
                {
                    "subject": f"Quick question for {first[:40]}",
                    "body": (
                        "Hi there,\n\n"
                        "Noticed your team has been hiring SDRs and thought our "
                        "outreach tooling might help. Worth a 15-min look next week?\n\n"
                        "Best,\n"
                    ),
                }
            )
        elif "extract a precise" in system:
            text = json.dumps(
                {
                    "tone": "casual",
                    "greeting": "Hi {first_name},",
                    "sign_off": "Best,",
                    "avg_length": "short",
                    "signature": "specific",
                    "avoid": ["synergy"],
                }
            )
        elif "classify a B2B" in system:
            text = json.dumps(
                {
                    "role_seniority": "VP",
                    "function": "Sales",
                    "primary_concern": "hitting next quarter's pipeline target",
                    "buying_window": "this_quarter",
                }
            )
        elif "classify an inbound email reply" in system:
            u = user.lower()
            if "unsubscribe" in u or "remove me" in u or "stop emailing" in u:
                cls, conf = "unsubscribe", 0.95
            elif "not interested" in u or "no thank" in u or "please remove" in u:
                cls, conf = "negative", 0.9
            elif "out of office" in u or "ooo" in u or "vacation" in u:
                cls, conf = "ooo", 0.9
            elif (
                "let's chat" in u or "let's talk" in u or "book a meeting" in u
                or "schedule a call" in u or "sounds good" in u
                or "happy to" in u or "i'd love to" in u or "i would love to" in u
            ):
                cls, conf = "positive", 0.9
            elif "?" in user or "what" in u or "how" in u:
                cls, conf = "question", 0.7
            else:
                cls, conf = "other", 0.5
            text = json.dumps(
                {
                    "classification": cls,
                    "confidence": conf,
                    "reason": f"keyword-matched to {cls} for offline stub",
                }
            )
        else:
            text = "{}"

        return LLMResponse(
            text=text,
            usage=LLMUsage(input_tokens=len(system) + len(user), output_tokens=len(text)),
        )

    def embed(
        self,
        model: str,
        inputs: list[str],
        *,
        timeout: int | None = None,
    ) -> list[list[float]]:
        self.calls.append({"model": model, "embed": list(inputs)})
        return [_text_to_vec(s) for s in inputs]


__all__ = ["FakeLLMClient", "_text_to_vec"]
