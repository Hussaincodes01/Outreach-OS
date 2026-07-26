"""Aggregate import of all SQLAlchemy models.

Importing this module ensures every model is registered on Base.metadata,
which Alembic needs for autogeneration (and we use for `target_metadata`).
"""
from __future__ import annotations

from outreach_os.domain.models.agent_run import AgentRun
from outreach_os.domain.models.audit import AuditEvent
from outreach_os.domain.models.billing_portal_token import BillingPortalToken
from outreach_os.domain.models.campaign import Campaign
from outreach_os.domain.models.campaign_step import CampaignStep
from outreach_os.domain.models.credential import Credential
from outreach_os.domain.models.crm_connection import CrmConnection
from outreach_os.domain.models.crm_sync_event import CrmSyncEvent
from outreach_os.domain.models.draft import Draft
from outreach_os.domain.models.icp import Icp
from outreach_os.domain.models.knowledge_base_chunk import KnowledgeBaseChunk
from outreach_os.domain.models.knowledge_base_item import KnowledgeBaseItem
from outreach_os.domain.models.lead import Lead
from outreach_os.domain.models.lead_source import LeadSource, LeadSourceKind
from outreach_os.domain.models.mailbox import Mailbox
from outreach_os.domain.models.meeting import Meeting
from outreach_os.domain.models.notification import Notification
from outreach_os.domain.models.notification_preference import NotificationPreference
from outreach_os.domain.models.plan import Plan
from outreach_os.domain.models.proxy import Proxy
from outreach_os.domain.models.reply import Reply
from outreach_os.domain.models.scraping_job import ScrapingJob, ScrapingJobStatus
from outreach_os.domain.models.send import Send
from outreach_os.domain.models.sequence_run import SequenceRun
from outreach_os.domain.models.sequence_step import SequenceStep
from outreach_os.domain.models.slack_webhook import SlackWebhook
from outreach_os.domain.models.subscription import Subscription
from outreach_os.domain.models.suppression import Suppression
from outreach_os.domain.models.tenant import Tenant
from outreach_os.domain.models.tracking_event import TrackingEvent
from outreach_os.domain.models.usage_event import UsageEvent
from outreach_os.domain.models.user import AppUser, UserRole

__all__ = [
    "AgentRun",
    "AppUser",
    "AuditEvent",
    "BillingPortalToken",
    "Campaign",
    "CampaignStep",
    "Credential",
    "CrmConnection",
    "CrmSyncEvent",
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
