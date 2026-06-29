"""Per-tenant notification preference CRUD.

GET /v1/notification-preferences
PUT /v1/notification-preferences  \u2014 upsert (event_key + channels)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from outreach_os.api.deps import AuthContext, get_current_user, get_scoped_db
from outreach_os.domain.models.notification_preference import NotificationPreference
from outreach_os.domain.schemas.phase6 import (
    NotificationPreferenceIn,
    NotificationPreferenceOut,
    NotificationPreferencePage,
)

router = APIRouter(prefix="/notification-preferences", tags=["notifications"])


def _to_out(p: NotificationPreference) -> NotificationPreferenceOut:
    return NotificationPreferenceOut(
        event_key=p.event_key,
        channel_in_app=p.channel_in_app,
        channel_email_digest=p.channel_email_digest,
        channel_slack=p.channel_slack,
        updated_at=p.updated_at,
    )


@router.get("", response_model=NotificationPreferencePage)
async def list_preferences(
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> NotificationPreferencePage:
    rows = (
        (
            await db.execute(
                select(NotificationPreference).order_by(NotificationPreference.event_key)
            )
        )
        .scalars()
        .all()
    )
    return NotificationPreferencePage(items=[_to_out(r) for r in rows])


@router.put("", response_model=NotificationPreferenceOut)
async def upsert_preference(
    body: NotificationPreferenceIn,
    _user: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_scoped_db),
) -> NotificationPreferenceOut:
    existing = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.event_key == body.event_key
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing is None:
        existing = NotificationPreference(
            tenant_id=_user.tenant_id,
            event_key=body.event_key,
            channel_in_app=body.channel_in_app,
            channel_email_digest=body.channel_email_digest,
            channel_slack=body.channel_slack,
        )
        db.add(existing)
    else:
        existing.channel_in_app = body.channel_in_app
        existing.channel_email_digest = body.channel_email_digest
        existing.channel_slack = body.channel_slack
    existing.updated_at = now
    await db.flush()
    return _to_out(existing)


__all__ = ["router"]
