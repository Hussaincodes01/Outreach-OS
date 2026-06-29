"""Calendar abstraction \u2014 provider-agnostic create/update/cancel surface.

The default in dev / tests is `StubCalendarClient`, which records every
event in-memory and returns a synthetic `provider_event_id`. Real adapters
(Google Calendar, Microsoft Graph) implement the same Protocol and can be
swapped in via `get_calendar_client()`.

`ICSBuilder` produces RFC 5545 iCalendar strings for event attachments
and web-download endpoints. iCalendar clients (Outlook, Apple Calendar,
Google Calendar) use the UID across syncs to recognise updates to the
same event \u2014 we keep the UID stable through every status change.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

log = logging.getLogger(__name__)


class CalendarError(RuntimeError):
    """Wraps any calendar provider failure (auth, rate limit, 4xx, network)."""


@dataclass
class CalendarEvent:
    """What the meeting service hands the calendar client."""
    ics_uid: str
    subject: str
    description: str | None
    location: str | None
    start: datetime
    end: datetime
    organizer_email: str
    attendee_emails: list[str] = field(default_factory=list)
    sequence: int = 0
    # STATUS: TENTATIVE for `proposed`, CONFIRMED for `confirmed`,
    # CANCELLED for `cancelled`. RFC 5545 \u00a73.8.1.11.
    status: str = "TENTATIVE"


@dataclass
class CalendarReceipt:
    """Provider's acknowledgement of a created/updated event."""
    provider_event_id: str
    raw: dict[str, Any] | None = None


class CalendarClient(Protocol):
    def create(self, event: CalendarEvent) -> CalendarReceipt: ...
    def update(self, provider_event_id: str, event: CalendarEvent) -> CalendarReceipt: ...
    def cancel(self, provider_event_id: str) -> CalendarReceipt: ...


class StubCalendarClient:
    """Default calendar for dev / tests.

    Records every event in `self.events` keyed by provider_event_id.
    Returns synthetic IDs. Throws CalendarError only when should_fail.
    """

    def __init__(self) -> None:
        self.events: dict[str, CalendarEvent] = {}
        self.should_fail = False

    def create(self, event: CalendarEvent) -> CalendarReceipt:
        if self.should_fail:
            raise CalendarError("stub calendar configured to fail")
        provider_event_id = f"cal-stub-{secrets.token_hex(8)}"
        self.events[provider_event_id] = event
        log.info(
            "stub-calendar create uid=%s subject=%r status=%s start=%s",
            event.ics_uid, event.subject[:60], event.status, event.start,
        )
        return CalendarReceipt(provider_event_id=provider_event_id, raw={"stub": True})

    def update(self, provider_event_id: str, event: CalendarEvent) -> CalendarReceipt:
        if self.should_fail:
            raise CalendarError("stub calendar configured to fail")
        self.events[provider_event_id] = event
        log.info("stub-calendar update provider_event_id=%s status=%s",
                 provider_event_id, event.status)
        return CalendarReceipt(provider_event_id=provider_event_id, raw={"stub": True})

    def cancel(self, provider_event_id: str) -> CalendarReceipt:
        if provider_event_id in self.events:
            self.events[provider_event_id].status = "CANCELLED"
        return CalendarReceipt(provider_event_id=provider_event_id, raw={"stub": True})

    def reset(self) -> None:
        self.events = {}
        self.should_fail = False


# --- ICS builder (RFC 5545) ---

def _format_ics_dt(dt: datetime) -> str:
    """Format a datetime as YYYYMMDDTHHMMSSZ in UTC (the trailing Z
    means UTC per RFC 5545 \u00a73.3.5). Naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _escape_ics_text(value: str) -> str:
    """Escape per RFC 5545 \u00a73.3.11: backslash, comma, semicolon, newline."""
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _fold_line(line: str) -> str:
    """RFC 5545 \u00a73.1: lines should be folded at 75 octets with CRLF + space.
    We approximate with character count (good enough for English text +
    ASCII headers). Unicode multi-byte characters may exceed 75 octets
    in pathological cases; we don't fold them to keep this simple."""
    if len(line) <= 75:
        return line
    parts: list[str] = []
    while len(line) > 75:
        parts.append(line[:75])
        line = " " + line[75:]
    parts.append(line)
    return "\r\n".join(parts)


class ICSBuilder:
    """Builds RFC 5545 iCalendar payloads for a single VEVENT."""

    DTSTAMP = _format_ics_dt(datetime.now(timezone.utc))

    @classmethod
    def build(cls, event: CalendarEvent) -> str:
        """Return a full VCALENDAR with one VEVENT \u2014 ready to email as
        a text/calendar attachment or write to disk.

        Output ends with CRLF and uses line-folding for long lines.
        """
        lines: list[str] = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Outreach OS//Meeting Booking//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:REQUEST" if event.status != "CANCELLED" else "METHOD:CANCEL",
            "BEGIN:VEVENT",
            f"UID:{event.ics_uid}",
            f"SEQUENCE:{event.sequence}",
            f"DTSTAMP:{cls.DTSTAMP}",
            f"DTSTART:{_format_ics_dt(event.start)}",
            f"DTEND:{_format_ics_dt(event.end)}",
            f"STATUS:{event.status}",
            f"SUMMARY:{_escape_ics_text(event.subject)}",
        ]
        if event.description:
            lines.append(f"DESCRIPTION:{_escape_ics_text(event.description)}")
        if event.location:
            lines.append(f"LOCATION:{_escape_ics_text(event.location)}")
        lines.append(f"ORGANIZER;CN=Outreach OS:mailto:{event.organizer_email}")
        for attendee in event.attendee_emails:
            lines.append(f"ATTENDEE;ROLE=REQ-PARTICIPIPANT:mailto:{attendee}")
        lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
        return "\r\n".join(_fold_line(line) for line in lines)


def generate_ics_uid() -> str:
    """Globally unique, stable iCalendar UID. Format follows
    `cryptographic-token@outreach-os.local` convention."""
    return f"{uuid.uuid4().hex}@outreach-os.local"


# --- Module-level singleton ---

_default_calendar: CalendarClient | None = None


def get_calendar_client() -> CalendarClient:
    """Return the process-wide calendar client.

    Default is the StubCalendarClient. Tests and the e2e demo inject
    their own stub by calling `set_calendar_client`.
    """
    global _default_calendar
    if _default_calendar is None:
        _default_calendar = StubCalendarClient()
    return _default_calendar


def set_calendar_client(client: CalendarClient | None) -> None:
    global _default_calendar
    _default_calendar = client


__all__ = [
    "CalendarClient",
    "CalendarError",
    "CalendarEvent",
    "CalendarReceipt",
    "ICSBuilder",
    "StubCalendarClient",
    "generate_ics_uid",
    "get_calendar_client",
    "set_calendar_client",
]
