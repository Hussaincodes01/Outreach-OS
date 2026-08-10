"""Deterministic FakeLLMClient for tests.

The agent pipeline calls `llm.chat(...)` 3 times (niche, style, draft) and
`llm.embed(...)` once (RAG query). We need each to return predictable
output that exercises the actual logic in the agent / RAG service.

Embeddings: a 1536-dim vector derived from a seeded hash of the input
text. Two equal inputs get the same vector; two different inputs get
clearly-different vectors (deterministic, but distinct enough that
cosine similarity between dissimilar inputs is well below 0.5).

Chat: pick the right canned response by inspecting the system prompt.
This lets the same fake serve niche / style / draft in one test.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from typing import Any

from outreach_os.core.llm import LLMResponse, LLMUsage


def _text_to_vec(text: str, dim: int = 1536) -> list[float]:
    """Deterministic embedding-like vector.

    The first 8 bytes of the SHA-256 of `text` seed a 32-bit int that we
    expand to `dim` floats in [-1, 1]. Different inputs give uncorrelated
    vectors; equal inputs give identical vectors.
    """
    h = hashlib.sha256(text.encode("utf-8")).digest()
    seed_int = struct.unpack(">I", h[:4])[0]
    out: list[float] = []
    for i in range(dim):
        # Cheap LCG: deterministic per (seed, i).
        v = (seed_int ^ (i * 0x9E3779B1)) & 0xFFFFFFFF
        out.append(((v / 0xFFFFFFFF) * 2.0) - 1.0)
    # L2-normalize so cosine distance is meaningful.
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


class FakeLLMClient:
    """Deterministic, no-network LLMClient. Token counts are stable per
    call so tests can assert on usage."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        # Tests can set this to override the canned reply classification.
        # Tuple: (classification, confidence, reason). Consumed once.
        self.next_reply_classification: tuple[str, float, str] | None = None
        # Queue of tool-call batches for the research agent, popped one per
        # chat() call. Each entry is a list of {id, name, arguments} dicts.
        # Empty queue -> the fake "answers" instead of calling a tool, which
        # is how the loop terminates.
        self.next_tool_calls: list[list[dict[str, str]]] = []

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 800,
        temperature: float = 0.7,
        timeout: int | None = None,
        response_format: dict[str, str] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "model": model,
                "messages": list(messages),
                "max_tokens": max_tokens,
                "tools": [t["function"]["name"] for t in tools] if tools else None,
            }
        )
        # Mirror the real client: tool calls come back on `raw`, not in text.
        if tools and self.next_tool_calls:
            batch = self.next_tool_calls.pop(0)
            return LLMResponse(
                text="",
                usage=LLMUsage(input_tokens=40, output_tokens=20),
                raw={"tool_calls": batch},
            )
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if len(messages) > 1 else ""

        if "email body, plain text" in system or "personalised B2B cold-outreach" in system:
            # Draft node. Include a tiny mention of the lead name so tests
            # can assert on personalisation.
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
            # Style node.
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
            # Niche node.
            text = json.dumps(
                {
                    "role_seniority": "VP",
                    "function": "Sales",
                    "primary_concern": "hitting next quarter's pipeline target",
                    "buying_window": "this_quarter",
                }
            )
        elif "classify an inbound email reply" in system:
            # Reply classifier (Phase 4+5). If a test set
            # `next_reply_classification`, use that and consume it.
            if self.next_reply_classification is not None:
                cls, conf, reason = self.next_reply_classification
                self.next_reply_classification = None
                text = json.dumps(
                    {"classification": cls, "confidence": conf, "reason": reason}
                )
            else:
                # Default: keyword-match the reply body so a generic
                # "let's chat" body still classifies as positive.
                body = user.lower()
                if "let's chat" in body or "book a meeting" in body or "sure" in body:
                    text = json.dumps(
                        {"classification": "positive", "confidence": 0.9, "reason": "stub-positive"}
                    )
                elif "remove me" in body or "unsubscribe" in body or "stop emailing" in body:
                    text = json.dumps(
                        {"classification": "unsubscribe", "confidence": 0.9, "reason": "stub-unsub"}
                    )
                elif "not interested" in body:
                    text = json.dumps(
                        {"classification": "negative", "confidence": 0.9, "reason": "stub-neg"}
                    )
                elif "out of office" in body or "vacation" in body:
                    text = json.dumps(
                        {"classification": "ooo", "confidence": 0.9, "reason": "stub-ooo"}
                    )
                else:
                    text = json.dumps(
                        {"classification": "other", "confidence": 0.5, "reason": "stub-default"}
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
        dimensions: int | None = None,
    ) -> list[list[float]]:
        self.calls.append({"model": model, "embed": list(inputs)})
        return [_text_to_vec(s) for s in inputs]


__all__ = ["FakeLLMClient", "_text_to_vec"]
