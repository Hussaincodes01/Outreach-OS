"""Billing provider abstraction + Stub implementation.

In dev/test we use the `StubBillingClient`, which simulates Stripe
endpoints in-memory: every call to `create_checkout_session` returns
a URL on our own backend that immediately "completes" the session,
firing the same webhook code path as a real Stripe event.

In prod we swap to the `StripeBillingClient` (httpx-based, no SDK
dependency to keep the install lean).
"""
from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


class BillingClient(Protocol):
    def create_checkout_session(
        self,
        *,
        customer_id: str | None,
        price_lookup_key: str,
        success_url: str,
        cancel_url: str,
    ) -> str: ...

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str: ...

    def verify_webhook_signature(
        self, *, payload: bytes, signature: str
    ) -> dict[str, Any]: ...


class StubBillingClient:
    """In-memory billing client. Used in dev / tests.

    `create_checkout_session` returns a URL of the form
        {api_base}/v1/billing/stub/complete?session=cs_test_...
    The billing API exposes a handler at that path that flips the
    tenant's subscription to active and returns a redirect.
    """

    def __init__(self, *, api_base: str) -> None:
        self._api_base = api_base.rstrip("/")
        self.sessions: dict[str, dict[str, Any]] = {}
        self.portal_calls: list[dict[str, Any]] = []

    def create_checkout_session(
        self,
        *,
        customer_id: str | None,
        price_lookup_key: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        session_id = "cs_test_" + secrets.token_urlsafe(12)
        self.sessions[session_id] = {
            "customer_id": customer_id,
            "price_lookup_key": price_lookup_key,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        return f"{self._api_base}/v1/billing/stub/complete?session={session_id}"

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        self.portal_calls.append(
            {"customer_id": customer_id, "return_url": return_url}
        )
        return return_url + "?portal=stub&customer=" + customer_id

    def verify_webhook_signature(
        self, *, payload: bytes, signature: str
    ) -> dict[str, Any]:
        # Stub: no signature check. Tests can override.
        import json
        return json.loads(payload.decode("utf-8"))


class StripeBillingClient:
    """Real Stripe client (httpx). Implement when we go live."""

    def __init__(
        self, *, api_key: str, webhook_secret: str, api_base: str = "https://api.stripe.com"
    ) -> None:
        self._api_key = api_key
        self._secret = webhook_secret
        self._api_base = api_base.rstrip("/")

    def create_checkout_session(
        self,
        *,
        customer_id: str | None,
        price_lookup_key: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        # Real Stripe call \u2014 minimal example.
        data: dict[str, str] = {
            "mode": "subscription",
            "line_items[0][price_lookup_key]": price_lookup_key,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if customer_id:
            data["customer"] = customer_id
        resp = httpx.post(
            f"{self._api_base}/v1/checkout/sessions",
            data=data,
            auth=(self._api_key, ""),
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["url"]

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        resp = httpx.post(
            f"{self._api_base}/v1/billing_portal/sessions",
            data={"customer": customer_id, "return_url": return_url},
            auth=(self._api_key, ""),
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["url"]

    def verify_webhook_signature(
        self, *, payload: bytes, signature: str
    ) -> dict[str, Any]:
        # Stripe signs payloads with HMAC-SHA256 of the timestamp + body.
        # We re-implement the check here to avoid pulling in the SDK.
        import hashlib
        import hmac
        import time

        if not signature:
            raise ValueError("missing signature")
        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        ts = parts.get("t", "")
        v1 = parts.get("v1", "")
        if not ts or not v1:
            raise ValueError("malformed signature")
        # 1 minute replay window (reduced from 5min for tighter security)
        if abs(time.time() - int(ts)) > 60:
            raise ValueError("signature too old")
        signed = ts.encode("ascii") + b"." + payload
        expected = hmac.new(
            self._secret.encode("utf-8"), signed, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, v1):
            raise ValueError("invalid signature")
        import json
        return json.loads(payload.decode("utf-8"))


_client: BillingClient | None = None


def get_billing_client() -> BillingClient:
    global _client
    if _client is None:
        from outreach_os.core.config import get_settings
        s = get_settings()
        if s.billing_provider == "stripe":
            _client = StripeBillingClient(
                api_key=s.stripe_secret_key.get_secret_value(),
                webhook_secret=s.stripe_webhook_secret.get_secret_value(),
            )
        else:
            _client = StubBillingClient(api_base=s.public_base_url)
    return _client


def set_billing_client(client: BillingClient | None) -> None:
    """Test seam \u2014 swap the global client for a stub."""
    global _client
    _client = client


__all__ = [
    "BillingClient",
    "StubBillingClient",
    "StripeBillingClient",
    "get_billing_client",
    "set_billing_client",
]
