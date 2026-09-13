#!/usr/bin/env python3
"""End-to-end smoke test against the running Outreach OS stack.

Exercises the real HTTP API, a real SMTP send and a real IMAP reply capture
against GreenMail -- no mocks, no third-party packages (stdlib only:
urllib, json, email, imaplib, smtplib, uuid, argparse, time, csv).

Usage:
    python scripts/e2e_smoke.py
    python scripts/e2e_smoke.py --api http://localhost:8000 \\
        --imap-host localhost --imap-port 3143 --smtp-host-internal greenmail

Prints one line per check:
    PASS <name>[: <detail>]
    FAIL <name>: <reason>
    SKIP <name>: <reason>

Exits 0 iff no check FAILed (SKIPped checks do not affect the exit code).

Checks (in order):
  1. health           GET /health and /health/ready
  2. workspace        GET /v1/tenants/me (no auth header)
  3. onboarding       GET /v1/onboarding
  4. icp               POST /v1/icps
  5. lead_import      POST /v1/leads/import (multipart, hand-built)
  6. mailbox          POST /v1/mailboxes/smtp
  7. smtp_delivery    POST /v1/mailboxes/{id}/send-test, then poll GreenMail IMAP
  8. llm_configured   GET /v1/credentials/providers
  9. provider_test    POST /v1/credentials/providers/{provider}/test
 10. draft_send_reply campaign -> draft -> sequence -> send -> reply, end to end
 11. ws_notifications optional; always SKIP
"""
from __future__ import annotations

import argparse
import csv
import email
import imaplib
import io
import json
import smtplib
import sys
import time
import urllib.error
import urllib.request
import uuid
from email.mime.text import MIMEText
from email.utils import make_msgid
from typing import Any

BOUNDARY = "----OutreachOSSmokeBoundary7c1d9f4a"

RESULTS: list[tuple[str, str, str]] = []  # (name, status, detail/reason)


def record(name: str, status: str, detail: str = "") -> None:
    RESULTS.append((name, status, detail))
    line = f"{status} {name}"
    if detail:
        line += f": {detail}"
    print(line, flush=True)


# --------------------------------------------------------------------------
# HTTP helpers (stdlib urllib only)
# --------------------------------------------------------------------------


def http_json(
    method: str, url: str, json_body: Any = None, timeout: float = 15.0
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return _do_request(req, timeout)


def http_multipart(
    url: str, fields: dict[str, str], file_field: str, filename: str,
    file_content: bytes, content_type: str = "text/csv", timeout: float = 30.0,
) -> tuple[int, Any]:
    body = _build_multipart(fields, file_field, filename, file_content, content_type)
    headers = {
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={BOUNDARY}",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    return _do_request(req, timeout)


def _do_request(req: urllib.request.Request, timeout: float) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{req.method} {req.full_url} failed: {exc.reason}") from exc
    if not raw:
        return status, None
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw.decode("utf-8", "replace")


def _build_multipart(
    fields: dict[str, str], file_field: str, filename: str,
    file_content: bytes, content_type: str,
) -> bytes:
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{BOUNDARY}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    parts.append(
        (
            f"--{BOUNDARY}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        + file_content
        + b"\r\n"
    )
    parts.append(f"--{BOUNDARY}--\r\n".encode("utf-8"))
    return b"".join(parts)


# --------------------------------------------------------------------------
# IMAP / SMTP helpers (stdlib only)
# --------------------------------------------------------------------------


def imap_wait_for_subject(
    host: str, port: int, username: str, marker: str, timeout_seconds: float,
    poll_seconds: float = 2.0,
) -> bytes | None:
    """Poll GreenMail's INBOX for `username` until a message whose subject
    contains `marker` shows up, or the deadline passes. Returns the raw
    RFC822 bytes of the first match, or None on timeout. Uses BODY.PEEK so
    the message is not marked \\Seen (mirrors the real poll_inboxes task,
    which only marks \\Seen after durably handling a message)."""
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            conn = imaplib.IMAP4(host, port)
            try:
                conn.login(username, "any-password")
                conn.select("INBOX")
                typ, data = conn.search(None, "SUBJECT", marker)
                if typ == "OK" and data and data[0]:
                    num = data[0].split()[-1]
                    typ, msg_data = conn.fetch(num, "(BODY.PEEK[])")
                    if typ == "OK" and msg_data and isinstance(msg_data[0], tuple):
                        return msg_data[0][1]
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001 - report the last error on timeout
            last_error = str(exc)
        time.sleep(poll_seconds)
    if last_error:
        raise RuntimeError(f"IMAP polling error (last attempt): {last_error}")
    return None


def smtp_send_reply(
    host: str, port: int, *, from_addr: str, to_addr: str, subject: str,
    body: str, in_reply_to: str, references: str,
) -> None:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["In-Reply-To"] = in_reply_to
    msg["References"] = references
    msg["Message-ID"] = make_msgid(domain="prospect.example.com")
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.sendmail(from_addr, [to_addr], msg.as_string())


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def check_health(api: str) -> bool:
    try:
        status, body = http_json("GET", f"{api}/health")
        status2, body2 = http_json("GET", f"{api}/health/ready")
    except RuntimeError as exc:
        record("health", "FAIL", str(exc))
        return False
    ok = (
        status == 200 and isinstance(body, dict) and body.get("status") == "ok"
        and status2 == 200 and isinstance(body2, dict) and body2.get("status") == "ok"
    )
    if ok:
        record("health", "PASS")
        return True
    record(
        "health", "FAIL",
        f"/health -> {status} {body!r}, /health/ready -> {status2} {body2!r}",
    )
    return False


def check_workspace(api: str) -> bool:
    try:
        status, body = http_json("GET", f"{api}/v1/tenants/me")
    except RuntimeError as exc:
        record("workspace", "FAIL", str(exc))
        return False
    if status == 200 and isinstance(body, dict) and body.get("slug") == "local":
        record("workspace", "PASS", f"name={body.get('name')!r}")
        return True
    record("workspace", "FAIL", f"GET /v1/tenants/me -> {status} {body!r}")
    return False


def check_onboarding(api: str) -> bool:
    try:
        status, body = http_json("GET", f"{api}/v1/onboarding")
    except RuntimeError as exc:
        record("onboarding", "FAIL", str(exc))
        return False
    if status == 200 and isinstance(body, dict) and isinstance(body.get("steps"), list):
        record("onboarding", "PASS", f"{len(body['steps'])} steps")
        return True
    record("onboarding", "FAIL", f"GET /v1/onboarding -> {status} {body!r}")
    return False


def check_icp(api: str) -> str | None:
    payload = {
        "name": f"Smoke ICP {uuid.uuid4().hex[:8]}",
        "description": "Created by scripts/e2e_smoke.py",
        "industries": ["Software"],
        "company_sizes": ["11-50"],
        "geos": ["US"],
        "titles": ["VP Sales"],
        "signals": [],
        "extra": {},
        "is_active": True,
    }
    try:
        status, body = http_json("POST", f"{api}/v1/icps", payload)
    except RuntimeError as exc:
        record("icp", "FAIL", str(exc))
        return None
    if status == 201 and isinstance(body, dict) and body.get("id"):
        record("icp", "PASS", f"id={body['id']}")
        return str(body["id"])
    record("icp", "FAIL", f"POST /v1/icps -> {status} {body!r}")
    return None


def check_lead_import(api: str, prospect_email: str) -> str | None:
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["email", "name", "company"])
    writer.writerow([prospect_email, "Prospect Person", "Prospect Co"])
    csv_bytes = csv_buf.getvalue().encode("utf-8")
    mapping = json.dumps({"email": "email", "name": "full_name", "company": "company_name"})
    try:
        status, body = http_multipart(
            f"{api}/v1/leads/import",
            fields={"mapping": mapping},
            file_field="file",
            filename="smoke_leads.csv",
            file_content=csv_bytes,
        )
    except RuntimeError as exc:
        record("lead_import", "FAIL", str(exc))
        return None
    if status == 200 and isinstance(body, dict) and body.get("imported") == 1:
        record(
            "lead_import", "PASS",
            f"imported=1 duplicates={body.get('duplicates')} skipped={body.get('skipped')}",
        )
    else:
        record("lead_import", "FAIL", f"POST /v1/leads/import -> {status} {body!r}")
        return None

    # The import result does not carry lead ids; look the row back up so
    # later checks (draft/sequence) have a lead_id to work with.
    try:
        status, body = http_json(
            "GET", f"{api}/v1/leads?source=csv_import&limit=200"
        )
    except RuntimeError:
        return None
    if status == 200 and isinstance(body, dict):
        for item in body.get("items", []):
            if item.get("email") == prospect_email:
                return str(item["id"])
    return None


def check_mailbox(api: str, sender_email: str, smtp_host_internal: str, smtp_port_internal: int) -> str | None:
    payload = {
        "email_address": sender_email,
        "host": smtp_host_internal,
        "port": smtp_port_internal,
        "username": sender_email,
        "password": sender_email,
        "use_tls": False,
        "daily_send_cap": 500,
        "imap_host": smtp_host_internal,
        "imap_port": 3143,
        "imap_use_ssl": False,
    }
    try:
        status, body = http_json("POST", f"{api}/v1/mailboxes/smtp", payload)
    except RuntimeError as exc:
        record("mailbox", "FAIL", str(exc))
        return None
    if status == 201 and isinstance(body, dict) and body.get("id") and body.get("imap_enabled") is True:
        record("mailbox", "PASS", f"id={body['id']} imap_enabled=True")
        return str(body["id"])
    record("mailbox", "FAIL", f"POST /v1/mailboxes/smtp -> {status} {body!r}")
    return None


def check_smtp_delivery(
    api: str, mailbox_id: str, prospect_email: str, imap_host: str, imap_port: int,
    imap_wait_seconds: float,
) -> bool:
    marker = uuid.uuid4().hex
    subject = f"Outreach OS smoke test {marker}"
    payload = {"to": prospect_email, "subject": subject, "body": "Smoke test body."}
    try:
        status, body = http_json(
            "POST", f"{api}/v1/mailboxes/{mailbox_id}/send-test", payload
        )
    except RuntimeError as exc:
        record("smtp_delivery", "FAIL", str(exc))
        return False
    if not (status == 200 and isinstance(body, dict) and body.get("ok") is True):
        record("smtp_delivery", "FAIL", f"POST send-test -> {status} {body!r}")
        return False

    try:
        raw = imap_wait_for_subject(
            imap_host, imap_port, prospect_email, marker, imap_wait_seconds
        )
    except RuntimeError as exc:
        record("smtp_delivery", "FAIL", f"send-test accepted but IMAP check errored: {exc}")
        return False
    if raw is None:
        record(
            "smtp_delivery", "FAIL",
            f"send-test accepted but message did not appear in GreenMail IMAP "
            f"within {imap_wait_seconds:.0f}s",
        )
        return False
    record("smtp_delivery", "PASS", f"message received by GreenMail within {imap_wait_seconds:.0f}s")
    return True


def check_llm_configured(api: str) -> tuple[bool, str | None]:
    """Returns (any_connected, provider_id). Records its own PASS/SKIP."""
    try:
        status, body = http_json("GET", f"{api}/v1/credentials/providers")
    except RuntimeError as exc:
        record("llm_configured", "FAIL", str(exc))
        return False, None
    if status != 200 or not isinstance(body, list):
        record("llm_configured", "FAIL", f"GET /v1/credentials/providers -> {status} {body!r}")
        return False, None
    connected = [p for p in body if p.get("connected")]
    if not connected:
        record("llm_configured", "SKIP", "no LLM key in .env")
        return False, None
    provider = str(connected[0]["provider"])
    record(
        "llm_configured", "PASS",
        f"{len(connected)} connected provider(s), using {provider!r}",
    )
    return True, provider


def check_provider_test(api: str, provider: str) -> bool:
    try:
        status, body = http_json("POST", f"{api}/v1/credentials/providers/{provider}/test")
    except RuntimeError as exc:
        record("provider_test", "FAIL", str(exc))
        return False
    if status == 200 and isinstance(body, dict) and body.get("ok") is True:
        record("provider_test", "PASS", f"provider={provider} message={body.get('message')!r}")
        return True
    record("provider_test", "FAIL", f"POST providers/{provider}/test -> {status} {body!r}")
    return False


def check_draft_send_reply(
    api: str, lead_id: str, sender_email: str, prospect_email: str,
    imap_host: str, imap_port: int, smtp_host: str, smtp_port: int,
    send_due_interval: float, inbox_poll_interval: float,
) -> bool:
    name = "draft_send_reply"

    # 1. Campaign with one step.
    camp_payload = {
        "name": f"Smoke Campaign {uuid.uuid4().hex[:8]}",
        "description": "Created by scripts/e2e_smoke.py",
        "steps": [
            {
                "step_number": 1,
                "delay_days": 0,
                "subject_template": "Quick question",
                "goal": "Book a 15-minute call",
            }
        ],
    }
    try:
        status, body = http_json("POST", f"{api}/v1/campaigns", camp_payload)
    except RuntimeError as exc:
        record(name, "FAIL", f"create campaign: {exc}")
        return False
    if status != 201 or not isinstance(body, dict) or not body.get("steps"):
        record(name, "FAIL", f"POST /v1/campaigns -> {status} {body!r}")
        return False
    campaign_id = body["id"]
    step_id = body["steps"][0]["id"]

    # 2. Generate a draft for the lead.
    try:
        status, body = http_json(
            "POST", f"{api}/v1/drafts/generate",
            {"lead_id": lead_id, "step_id": step_id, "force_regenerate": True},
        )
    except RuntimeError as exc:
        record(name, "FAIL", f"generate draft: {exc}")
        return False
    if status != 200 or not isinstance(body, dict) or body.get("status") != "ready":
        record(name, "FAIL", f"POST /v1/drafts/generate -> {status} {body!r}")
        return False

    # 3. Start the sequence.
    seq_payload = {
        "campaign_id": campaign_id,
        "name": f"Smoke Sequence {uuid.uuid4().hex[:8]}",
        "lead_ids": [lead_id],
        "ignore_caps": True,
    }
    try:
        status, body = http_json("POST", f"{api}/v1/sequences", seq_payload)
    except RuntimeError as exc:
        record(name, "FAIL", f"start sequence: {exc}")
        return False
    if status != 201 or not isinstance(body, dict) or not body.get("id"):
        record(name, "FAIL", f"POST /v1/sequences -> {status} {body!r}")
        return False
    run_id = body["id"]

    # 4. Wait up to 3x SEND_DUE_INTERVAL_SECONDS for a "sent" send.
    deadline = time.monotonic() + 3 * send_due_interval
    send: dict[str, Any] | None = None
    last_statuses: set[str] = set()
    while time.monotonic() < deadline:
        try:
            status, body = http_json("GET", f"{api}/v1/sends?run_id={run_id}")
        except RuntimeError as exc:
            record(name, "FAIL", f"poll sends: {exc}")
            return False
        if status == 200 and isinstance(body, dict):
            for item in body.get("items", []):
                last_statuses.add(str(item.get("status")))
                if item.get("status") == "sent":
                    send = item
                    break
        if send is not None:
            break
        time.sleep(5)
    if send is None:
        # Not sent in time. Be explicit if a send window appears to be the
        # cause (this build's send.py has no send-window gate as of this
        # writing, so this is a defensive check for future regressions).
        if "queued" in last_statuses or "pending" in last_statuses:
            record(
                name, "FAIL",
                f"no send reached status 'sent' within {3 * send_due_interval:.0f}s "
                f"(observed statuses: {sorted(last_statuses) or ['none yet']}). If a send "
                "window is blocking delivery, set SEND_WINDOW_START_HOUR=0 and "
                "SEND_WINDOW_END_HOUR=24 in .env and restart.",
            )
        else:
            record(
                name, "FAIL",
                f"no send appeared for run {run_id} within "
                f"{3 * send_due_interval:.0f}s (observed statuses: {sorted(last_statuses) or ['none']})",
            )
        return False

    api_message_id = send.get("message_id_header")

    # 5. Confirm GreenMail actually received it, and read its Message-ID.
    marker = str(send.get("subject") or "")
    try:
        raw = imap_wait_for_subject(imap_host, imap_port, prospect_email, marker or "Outreach", 30.0)
    except RuntimeError as exc:
        record(name, "FAIL", f"sent per API, but IMAP confirmation errored: {exc}")
        return False
    if raw is None:
        record(name, "FAIL", "send status=sent per API, but message never appeared in GreenMail IMAP")
        return False
    delivered_msg = email.message_from_bytes(raw)
    delivered_message_id = delivered_msg.get("Message-ID", api_message_id)

    # 6. Reply from the prospect to the sender, In-Reply-To the delivered mail.
    try:
        smtp_send_reply(
            smtp_host, smtp_port,
            from_addr=prospect_email, to_addr=sender_email,
            subject=f"Re: {send.get('subject') or ''}",
            body="Thanks, let's talk.",
            in_reply_to=delivered_message_id, references=delivered_message_id,
        )
    except Exception as exc:  # noqa: BLE001
        record(name, "FAIL", f"could not deliver reply via SMTP: {exc}")
        return False

    # 7. Wait up to 3x INBOX_POLL_INTERVAL_SECONDS for GET /v1/replies to see it.
    deadline = time.monotonic() + 3 * inbox_poll_interval
    found = False
    while time.monotonic() < deadline:
        try:
            status, body = http_json("GET", f"{api}/v1/replies?run_id={run_id}")
        except RuntimeError as exc:
            record(name, "FAIL", f"poll replies: {exc}")
            return False
        if status == 200 and isinstance(body, dict) and body.get("items"):
            found = True
            break
        time.sleep(5)
    if not found:
        record(
            name, "FAIL",
            f"reply delivered over SMTP but GET /v1/replies never showed it within "
            f"{3 * inbox_poll_interval:.0f}s (IMAP poll interval / mailbox app-password issue?)",
        )
        return False

    record(name, "PASS", f"run={run_id} send={send['id']} reply captured via IMAP poll")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--imap-host", default="localhost")
    parser.add_argument("--imap-port", type=int, default=3143)
    parser.add_argument("--smtp-host", default="localhost", help="host-side SMTP (for the reply the prospect sends)")
    parser.add_argument("--smtp-port", type=int, default=3025)
    parser.add_argument("--smtp-host-internal", default="greenmail", help="hostname the API container uses to reach GreenMail")
    parser.add_argument("--smtp-port-internal", type=int, default=3025)
    parser.add_argument("--imap-wait-seconds", type=float, default=30.0)
    parser.add_argument("--send-due-interval", type=float, default=60.0, help="SEND_DUE_INTERVAL_SECONDS")
    parser.add_argument("--inbox-poll-interval", type=float, default=120.0, help="INBOX_POLL_INTERVAL_SECONDS")
    args = parser.parse_args()

    api = args.api.rstrip("/")
    run_id_suffix = uuid.uuid4().hex[:8]
    prospect_email = f"prospect-{run_id_suffix}@example.com"
    sender_email = f"sender-{run_id_suffix}@example.com"

    print(f"== Outreach OS smoke test against {api} ==")

    # 1-3: independent read checks.
    check_health(api)
    check_workspace(api)
    check_onboarding(api)

    # 4: ICP (independent, but its success/failure doesn't gate later checks).
    check_icp(api)

    # 5: lead import -> lead_id needed for check 10.
    lead_id = check_lead_import(api, prospect_email)

    # 6: mailbox -> mailbox_id needed for check 7.
    mailbox_id = check_mailbox(api, sender_email, args.smtp_host_internal, args.smtp_port_internal)

    # 7: SMTP delivery, depends on mailbox_id.
    if mailbox_id is not None:
        check_smtp_delivery(
            api, mailbox_id, prospect_email, args.imap_host, args.imap_port, args.imap_wait_seconds
        )
    else:
        record("smtp_delivery", "FAIL", "blocked: mailbox check did not produce a mailbox_id")

    # 8: LLM configured -> gates 9, 10.
    any_connected, provider = check_llm_configured(api)

    if any_connected and provider:
        check_provider_test(api, provider)
        if lead_id is not None:
            check_draft_send_reply(
                api, lead_id, sender_email, prospect_email,
                args.imap_host, args.imap_port, args.smtp_host, args.smtp_port,
                args.send_due_interval, args.inbox_poll_interval,
            )
        else:
            record("draft_send_reply", "FAIL", "blocked: lead_import did not produce a lead_id")
    else:
        record("provider_test", "SKIP", "no LLM key in .env")
        record("draft_send_reply", "SKIP", "no LLM key in .env")

    # 11: optional, always skipped.
    record("ws_notifications", "SKIP", "optional per spec -- not exercised")

    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    skipped = sum(1 for _, s, _ in RESULTS if s == "SKIP")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
