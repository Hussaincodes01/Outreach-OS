"""Aggregate import of all SQLAlchemy models.

Importing this module ensures every model is registered on Base.metadata,
which Alembic needs for autogeneration (and we use for `target_metadata`).
"""
from __future__ import annotations

from outreach_os.domain.models.agent_run import AgentRun  # noqa: F401
from outreach_os.domain.models.audit import AuditEvent  # noqa: F401
from outreach_os.domain.models.billing_portal_token import BillingPortalToken  # noqa: F401
from outreach_os.domain.models.campaign import Campaign  # noqa: F401
from outreach_os.domain.models.campaign_step import CampaignStep  # noqa: F401
from outreach_os.domain.models.crm_connection import CrmConnection  # noqa: F401
from outreach_os.domain.models.crm_sync_event import CrmSyncEvent  # noqa: F401
from outreach_os.domain.models.credential import Credential  # noqa: F401
from outreach_os.domain.models.draft import Draft  # noqa: F401
from outreach_os.domain.models.icp import Icp  # noqa: F401
from outreach_os.domain.models.knowledge_base_chunk import KnowledgeBaseChunk  # noqa: F401
from outreach_os.domain.models.knowledge_base_item import KnowledgeBaseItem  # noqa: F401
from outreach_os.domain.models.lead import Lead  # noqa: F401
from outreach_os.domain.models.lead_source import LeadSource, LeadSourceKind  # noqa: F401
from outreach_os.domain.models.mailbox import Mailbox  # noqa: F401
from outreach_os.domain.models.meeting import Meeting  # noqa: F401
from outreach_os.domain.models.notification import Notification  # noqa: F401
from outreach_os.domain.models.notification_preference import NotificationPreference  # noqa: F401
from outreach_os.domain.models.plan import Plan  # noqa: F401
from outreach_os.domain.models.proxy import Proxy  # noqa: F401
from outreach_os.domain.models.reply import Reply  # noqa: F401
from outreach_os.domain.models.scraping_job import ScrapingJob, ScrapingJobStatus  # noqa: F401
from outreach_os.domain.models.send import Send  # noqa: F401
from outreach_os.domain.models.sequence_run import SequenceRun  # noqa: F401
from outreach_os.domain.models.sequence_step import SequenceStep  # noqa: F401
from outreach_os.domain.models.slack_webhook import SlackWebhook  # noqa: F401
from outreach_os.domain.models.subscription import Subscription  # noqa: F401
from outreach_os.domain.models.suppression import Suppression  # noqa: F401
from outreach_os.domain.models.tenant import Tenant  # noqa: F401
from outreach_os.domain.models.tracking_event import TrackingEvent  # noqa: F401
from outreach_os.domain.models.usage_event import UsageEvent  # noqa: F401
from outreach_os.domain.models.user import AppUser, UserRole  # noqa: F401

__all__ = [
    "AgentRun",
    "AppUser",
    "AuditEvent",
    "BillingPortalToken",
    "Campaign",
    "CampaignStep",
    "CrmConnection",
    "CrmSyncEvent",
    "Credential",
    "Draft",
    "Icp",
    "KnowledgeBaseChunk",
    "KnowledgeBaseItem",
    "Lead",
    "LeadSource",
    "LeadSourceKind",
    "Mailbox",
    "Meeting",
    "Notification",
    "NotificationPreference",
    "Plan",
    "Proxy",
    "Reply",
    "ScrapingJob",
    "ScrapingJobStatus",
    "Send",
    "SequenceRun",
    "SequenceStep",
    "SlackWebhook",
    "Subscription",
    "Suppression",
    "Tenant",
    "TrackingEvent",
    "UsageEvent",
    "UserRole",
]
