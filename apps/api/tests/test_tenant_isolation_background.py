"""Background work binds the tenant of the row it works on.

With accounts back there is no single workspace any more: the IMAP reply
poller must visit every active workspace's mailboxes, bind *that* workspace
before touching each mailbox, and file each reply under the workspace that
owns the mailbox — never under another one.
"""
from __future__ import annotations

import httpx
import pytest

from tests.conftest import bearer, signup, unique_email
from tests.test_inbox_polling import _create_sent_send, _raw_reply

_PASSWORD = "correct-horse-battery-staple"


def _mailbox(address: str) -> dict:
    return {
        "host": "smtp.example.org",
        "port": 587,
        "username": address,
        "password": "app-password",
        "email_address": address,
        "imap_host": "imap.example.org",
    }


async def _replies(client: httpx.AsyncClient, token: str) -> list[dict]:
    resp = await client.get("/v1/replies", headers=bearer(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return list(body["items"] if isinstance(body, dict) else body)


@pytest.fixture
def fake_llm():
    from outreach_os.core.llm import set_llm_client
    from tests.fake_llm import FakeLLMClient

    set_llm_client(FakeLLMClient())
    yield
    set_llm_client(None)


async def test_poller_files_each_reply_under_the_mailbox_owners_workspace(
    client: httpx.AsyncClient, fake_llm: None
) -> None:
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    a = await signup(client, email=unique_email(), password=_PASSWORD, tenant_name="Tenant A")
    b = await signup(client, email=unique_email(), password=_PASSWORD, tenant_name="Tenant B")
    _mb_a, msg_a = await _create_sent_send(
        client, _mailbox("a-box@example.org"), headers=bearer(a["access_token"])
    )
    _mb_b, msg_b = await _create_sent_send(
        client, _mailbox("b-box@example.org"), headers=bearer(b["access_token"])
    )

    # Each mailbox's IMAP inbox holds only the reply to its own send.
    inboxes = {
        "a-box@example.org": [(b"1", _raw_reply(msg_a, message_id="<reply-a@prospect.example>"))],
        "b-box@example.org": [(b"1", _raw_reply(msg_b, message_id="<reply-b@prospect.example>"))],
    }
    polled: list[str] = []

    def _fetch(cfg: dict) -> list[tuple[bytes, bytes]]:
        polled.append(cfg["username"])
        return inboxes[cfg["username"]]

    summary = await poll_inboxes_async(fetch=_fetch, mark_seen=lambda cfg, uids: None)

    assert summary == {"mailboxes": 2, "ingested": 2, "errors": 0}
    assert sorted(polled) == ["a-box@example.org", "b-box@example.org"]

    replies_a = await _replies(client, a["access_token"])
    replies_b = await _replies(client, b["access_token"])
    assert [r["message_id_header"] for r in replies_a] == ["<reply-a@prospect.example>"]
    assert [r["message_id_header"] for r in replies_b] == ["<reply-b@prospect.example>"]


async def test_poller_cannot_match_a_reply_to_another_workspaces_send(
    client: httpx.AsyncClient, fake_llm: None
) -> None:
    """A message in B's inbox that claims to answer A's send must not land in
    A's workspace: the match runs under B's tenant, where A's send is invisible."""
    from outreach_os.workers.tasks.inbox import poll_inboxes_async

    a = await signup(client, email=unique_email(), password=_PASSWORD, tenant_name="Tenant A")
    b = await signup(client, email=unique_email(), password=_PASSWORD, tenant_name="Tenant B")
    _mb_a, msg_a = await _create_sent_send(
        client, _mailbox("a-box@example.org"), headers=bearer(a["access_token"])
    )
    await _create_sent_send(client, _mailbox("b-box@example.org"), headers=bearer(b["access_token"]))

    inboxes = {
        "a-box@example.org": [],
        "b-box@example.org": [(b"1", _raw_reply(msg_a, message_id="<cross@prospect.example>"))],
    }
    await poll_inboxes_async(
        fetch=lambda cfg: inboxes[cfg["username"]], mark_seen=lambda cfg, uids: None
    )

    assert await _replies(client, a["access_token"]) == []
