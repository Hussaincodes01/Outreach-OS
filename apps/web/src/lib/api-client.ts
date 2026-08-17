/**
 * Thin typed client for the Outreach OS API.
 *
 * In v1 we hand-write types for the endpoints we use. In v2 the types
 * are auto-generated from the FastAPI OpenAPI schema via the
 * `scripts/generate-api-client.sh` helper into
 * `packages/shared-types/src/index.ts`.
 */
import { useEffect } from "react";
import { useAuth } from "./auth";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface SignupInput {
  email: string;
  password: string;
  tenantName: string;
  tenantSlug?: string;
}

export interface TokenPair {
  /** JWT access token (short-lived, ~15 min) */
  access_token: string;
  /** JWT refresh token (long-lived, ~30 days) */
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
  user_id: string;
  tenant_id: string;
}

export interface UserOut {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
  /** Null until the address is confirmed. Access is never gated on this. */
  email_verified_at: string | null;
}

export interface TenantOut {
  id: string;
  slug: string;
  name: string;
  status: string;
  plan: string;
  created_at: string;
  updated_at: string;
}

export interface CredentialOut {
  id: string;
  kind: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  last_verified_at?: string | null;
  has_secret: boolean;
}

/** A connectable LLM provider. Served by the API so the UI never hard-codes
 *  a list that can drift from the backend. */
export interface ImportPreviewOut {
  headers: string[];
  sample_rows: Record<string, string>[];
  suggested_mapping: Record<string, string>;
  importable_fields: string[];
  total_rows: number;
  truncated: boolean;
  max_rows: number;
}

export interface ImportResultOut {
  imported: number;
  duplicates: number;
  skipped: number;
  total_rows: number;
  problems: { row_number: number; reason: string }[];
}

export interface ProviderOut {
  provider: string;
  credential_kind: string;
  label: string;
  console_url: string;
  supports_embeddings: boolean;
  connected: boolean;
  last_verified_at: string | null;
  description: string;
  /** Self-hosted / gateway providers take a base URL; some take no key. */
  requires_api_base: boolean;
  requires_api_key: boolean;
  api_base_hint: string | null;
  model_count: number;
}

export interface OnboardingStepOut {
  key: string;
  title: string;
  description: string;
  done: boolean;
  required: boolean;
  href: string;
  detail: string | null;
}

export interface OnboardingStatusOut {
  /** True once every required step is done, i.e. the workspace can actually run. */
  ready: boolean;
  dismissed: boolean;
  completed_at: string | null;
  next_step_key: string | null;
  steps: OnboardingStepOut[];
}

export interface ModelOut {
  id: string;
  label: string;
  provider: string;
  provider_label: string;
  supports_tools: boolean;
  context_window: number;
  tier: string;
  /** False when this workspace has no key for the model's provider. */
  available: boolean;
}

export interface EmbeddingModelOut {
  id: string;
  label: string;
  provider: string;
  provider_label: string;
  dimensions: number;
  available: boolean;
}

export interface LlmSettingsOut {
  default_llm_model: string | null;
  embedding_llm_model: string | null;
  available_models: string[];
  models: ModelOut[];
  embedding_models: EmbeddingModelOut[];
}

export interface MailboxOut {
  id: string;
  provider: "gmail" | "outlook" | "smtp";
  email_address: string;
  is_active: boolean;
  daily_send_cap: number;
  created_at: string;
}

export interface AuditEventOut {
  id: string;
  actor_kind: "user" | "system" | "agent";
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown>;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface AuditPage {
  items: AuditEventOut[];
  total: number;
  limit: number;
  offset: number;
}

// --- Phase 6: notifications ---

export type NotificationSeverity = "info" | "success" | "warning" | "error";

export interface NotificationOut {
  id: string;
  event_key: string;
  severity: NotificationSeverity;
  title: string;
  body: string | null;
  target_type: string | null;
  target_id: string | null;
  payload: Record<string, unknown>;
  read_at: string | null;
  delivered_in_app: boolean;
  delivered_email: boolean;
  delivered_slack: boolean;
  created_at: string;
}

export interface NotificationPage {
  items: NotificationOut[];
  total: number;
  unread: number;
  limit: number;
  offset: number;
}

export interface NotificationPreferenceOut {
  event_key: string;
  channel_in_app: boolean;
  channel_email_digest: boolean;
  channel_slack: boolean;
  updated_at: string;
}

export interface NotificationPreferenceIn {
  event_key: string;
  channel_in_app: boolean;
  channel_email_digest: boolean;
  channel_slack: boolean;
}

export interface NotificationPreferencePage {
  items: NotificationPreferenceOut[];
}

export interface SlackWebhookOut {
  id: string;
  name: string;
  channel: string | null;
  status: "active" | "paused" | "error";
  last_error: string | null;
  last_delivered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SlackWebhookIn {
  name?: string;
  webhook_url: string;
  channel?: string | null;
}

// --- Phase 7: billing ---

export interface PlanOut {
  id: string;
  code: string;
  name: string;
  monthly_price_cents: number;
  monthly_send_cap: number;
  monthly_lead_cap: number;
  monthly_llm_token_cap: number;
  crm_sync_enabled: boolean;
  slack_notifications_enabled: boolean;
  email_digest_enabled: boolean;
  max_team_seats: number;
  max_mailboxes: number;
  display_order: number;
}

export interface PlanListOut {
  items: PlanOut[];
}

export interface SubscriptionOut {
  id: string;
  plan: PlanOut;
  status: string;
  provider: string;
  provider_customer_id: string | null;
  provider_subscription_id: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface UsageSummaryOut {
  sends_used: number;
  sends_cap: number;
  leads_used: number;
  leads_cap: number;
  llm_tokens_used: number;
  llm_tokens_cap: number;
  reset_at: string;
  over_sends: boolean;
  over_leads: boolean;
  over_llm_tokens: boolean;
}

export interface CheckoutOut {
  checkout_url: string;
  provider: string;
}

export interface PortalOut {
  portal_url: string;
  token: string | null;
  expires_at: string | null;
}

// --- Phase 2: lead scraping ---

export interface IcpOut {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  industries: string[];
  company_sizes: string[];
  geos: string[];
  titles: string[];
  signals: string[];
  extra: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface IcpInput {
  name: string;
  description?: string | null;
  industries?: string[];
  company_sizes?: string[];
  geos?: string[];
  titles?: string[];
  signals?: string[];
  extra?: Record<string, unknown>;
  is_active?: boolean;
}

export interface LeadSourceOut {
  id: string;
  tenant_id: string;
  source: "serper" | "company_site" | "linkedin_proxycurl";
  is_enabled: boolean;
  config: Record<string, unknown>;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LeadSourceUpdate {
  is_enabled?: boolean;
  config?: Record<string, unknown>;
}

export interface LeadOut {
  id: string;
  tenant_id: string;
  source: string;
  job_id: string | null;
  first_name: string | null;
  last_name: string | null;
  full_name: string | null;
  email: string | null;
  domain: string | null;
  company_name: string | null;
  title: string | null;
  linkedin_url: string | null;
  country: string | null;
  industry: string | null;
  company_size: string | null;
  created_at: string;
}

export interface LeadPage {
  items: LeadOut[];
  total: number;
  limit: number;
  offset: number;
}

export type ScrapingJobStatus = "pending" | "running" | "completed" | "failed";

export interface ScrapingJobOut {
  id: string;
  tenant_id: string;
  icp_id: string;
  status: ScrapingJobStatus;
  sources: string[];
  requested_count: number;
  found_count: number;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScrapingJobInput {
  icp_id: string;
  sources?: string[];
  requested_count?: number;
}

export interface ProxyOut {
  id: string;
  tenant_id: string;
  label: string;
  protocol: "http" | "https" | "socks5";
  host: string;
  port: number;
  is_active: boolean;
  created_at: string;
}

export interface ProxyInput {
  label: string;
  protocol?: "http" | "https" | "socks5";
  host: string;
  port: number;
  url?: string | null;
}

// --- Phase 3: campaigns, knowledge, drafts ---

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type CampaignStatus = "draft" | "active" | "paused" | "archived";

export interface CampaignStepOut {
  id: string;
  step_number: number;
  delay_days: number;
  subject_template: string;
  goal: string | null;
}

export interface CampaignStepInput {
  step_number: number;
  delay_days: number;
  subject_template: string;
  goal?: string | null;
}

export interface CampaignOut {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  status: CampaignStatus;
  llm_model: string | null;
  style_sample_emails: string[];
  style_notes: string | null;
  is_active: boolean;
  steps: CampaignStepOut[];
  created_at: string;
  updated_at: string;
}

export interface CampaignInput {
  name: string;
  description?: string | null;
  llm_model?: string | null;
  style_sample_emails?: string[];
  style_notes?: string | null;
  steps: CampaignStepInput[];
}

export interface CampaignUpdate {
  name?: string;
  description?: string | null;
  status?: CampaignStatus;
  llm_model?: string | null;
  style_sample_emails?: string[];
  style_notes?: string | null;
}

export interface KnowledgeItemOut {
  id: string;
  tenant_id: string;
  title: string;
  source: string;
  chunk_count: number;
  body?: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeItemCreate {
  title: string;
  body: string;
  source?: string;
}

export type KnowledgePage = Page<KnowledgeItemOut>;

export type DraftStatus = "pending" | "ready" | "approved" | "rejected" | "failed";

export interface DraftOut {
  id: string;
  tenant_id: string;
  campaign_id: string;
  lead_id: string;
  step_id: string;
  step_number: number;
  status: DraftStatus;
  subject: string | null;
  body_preview: string | null;
  body?: string | null;
  body_url?: string | null;
  model_used: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface DraftUpdate {
  status?: DraftStatus;
  subject?: string | null;
  body_preview?: string | null;
}

export type DraftPage = Page<DraftOut>;

export interface AgentRunOut {
  id: string;
  tenant_id: string;
  campaign_id: string | null;
  draft_id: string | null;
  status: string;
  trace: Record<string, unknown> | null;
  input_tokens: number | null;
  output_tokens: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

// --- Phase 4: sequences, sends, replies, suppressions ---

export type SequenceStatus = "running" | "paused" | "stopped" | "completed";

export interface SequenceRunOut {
  id: string;
  name: string;
  campaign_id: string;
  status: SequenceStatus;
  stopped_reason: string | null;
  started_at: string | null;
  stopped_at: string | null;
  created_at: string;
  step_count: number;
  pending_count: number;
  sent_count: number;
  replied_count: number;
  stopped_count: number;
}

export interface SequenceRunStartIn {
  campaign_id: string;
  name: string;
  lead_ids: string[];
  start_at?: string | null;
  ignore_caps?: boolean;
}

export type SendStatus =
  | "queued"
  | "sent"
  | "bounced"
  | "failed"
  | "unsubscribed"
  | "skipped";

export interface SendOut {
  id: string;
  to_email: string;
  from_email: string;
  subject: string | null;
  body_text: string | null;
  message_id_header: string | null;
  status: SendStatus;
  error: string | null;
  queued_at: string;
  sent_at: string | null;
  opened_at: string | null;
  clicked_at: string | null;
}

export type SendPage = Page<SendOut>;

export type ReplyClassification =
  | "positive"
  | "negative"
  | "ooo"
  | "question"
  | "unsubscribe"
  | "bounce"
  | "other";

export interface ReplyOut {
  id: string;
  send_id: string;
  from_email: string;
  from_name: string | null;
  subject: string | null;
  body_text: string | null;
  received_at: string;
  classification: ReplyClassification;
  classification_confidence: number;
  classified_at: string | null;
}

export type ReplyPage = Page<ReplyOut>;

export interface ReplyIngestIn {
  message_id_header: string;
  from_email: string;
  from_name?: string | null;
  subject?: string | null;
  body_text?: string | null;
  received_at: string;
}

export type SuppressionReason = "unsubscribe" | "bounce" | "complaint" | "manual";

export interface SuppressionOut {
  id: string;
  email: string;
  reason: SuppressionReason;
  source: string | null;
  notes: string | null;
  created_at: string;
}

export type SuppressionPage = Page<SuppressionOut>;

export interface SuppressionCreateIn {
  email: string;
  reason: SuppressionReason;
  source?: string | null;
  notes?: string | null;
}

// --- Phase 5: meetings + CRM ---

export type MeetingStatus =
  | "proposed"
  | "confirmed"
  | "declined"
  | "cancelled"
  | "completed"
  | "no_show";

export interface MeetingSlot {
  index: number;
  start: string;
  end: string;
}

export interface MeetingOut {
  id: string;
  created_at: string;
  tenant_id: string;
  lead_id: string;
  mailbox_id: string | null;
  send_id: string | null;
  reply_id: string | null;
  subject: string;
  agenda: string | null;
  location: string | null;
  duration_minutes: number;
  proposed_slots: Array<{ index: number; start: string; end: string }>;
  chosen_slot: string | null;
  status: MeetingStatus;
  provider_event_id: string | null;
  ics_uid: string;
  ics_sequence: number;
  organizer_email: string;
  attendee_email: string;
  proposed_at: string;
  confirmed_at: string | null;
  declined_at: string | null;
  cancelled_at: string | null;
  updated_at: string;
}

export type MeetingPage = Page<MeetingOut>;

export interface MeetingConfirmIn {
  slot_index: number;
}

export type CrmConnectionStatus = "active" | "paused" | "error";
export type CrmProvider = "google_sheets";

export interface CrmConnectionOut {
  id: string;
  created_at: string;
  tenant_id: string;
  provider: CrmProvider;
  name: string;
  spreadsheet_id: string | null;
  sheet_range: string | null;
  column_mapping: Record<string, string>;
  access_token_credential_id: string | null;
  status: CrmConnectionStatus;
  last_sync_at: string | null;
  last_sync_error: string | null;
  updated_at: string;
}

export type CrmConnectionPage = Page<CrmConnectionOut>;

export interface CrmConnectionCreateIn {
  provider?: CrmProvider;
  name: string;
  spreadsheet_id?: string | null;
  sheet_range?: string | null;
  column_mapping?: Record<string, string>;
  access_token_credential_id?: string | null;
}

export interface CrmConnectionUpdateIn {
  name?: string;
  spreadsheet_id?: string | null;
  sheet_range?: string | null;
  column_mapping?: Record<string, string> | null;
  status?: CrmConnectionStatus | null;
}

export interface CrmSyncEventOut {
  id: string;
  created_at: string;
  tenant_id: string;
  crm_connection_id: string;
  meeting_id: string | null;
  status: "success" | "failed";
  row_written: Record<string, unknown> | null;
  error: string | null;
  synced_at: string;
}

export type CrmSyncEventPage = Page<CrmSyncEventOut>;

class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * 428 means the workspace is missing a setup step (e.g. no BYOK API key), not
 * that the request was wrong. Callers use this to send the user to onboarding
 * instead of showing a generic failure.
 */
export function isSetupRequired(err: unknown): err is ApiError {
  return err instanceof ApiError && err.status === 428;
}

let inMemoryToken: string | null = null;

function authHeader(): Record<string, string> {
  return inMemoryToken ? { Authorization: `Bearer ${inMemoryToken}` } : {};
}

async function request<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeader(),
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // body wasn't JSON
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

/**
 * Multipart POST for file uploads.
 *
 * Deliberately does NOT set Content-Type: the browser has to generate it
 * itself so it can append the multipart boundary. Setting it by hand — as
 * `request()` does for JSON — produces a body the server cannot parse.
 */
async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    body: form,
    headers: { ...authHeader() },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // body wasn't JSON
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  setAccessToken(token: string | null) {
    inMemoryToken = token;
  },

  async forgotPassword(email: string): Promise<{ message: string }> {
    return request("/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },

  async resetPassword(token: string, newPassword: string): Promise<{ message: string }> {
    return request("/v1/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    });
  },

  async verifyEmail(token: string): Promise<{ message: string }> {
    return request("/v1/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  },

  async resendVerification(): Promise<{ message: string }> {
    return request("/v1/auth/resend-verification", { method: "POST" });
  },

  async previewLeadImport(file: File): Promise<ImportPreviewOut> {
    const form = new FormData();
    form.append("file", file);
    return requestForm<ImportPreviewOut>("/v1/leads/import/preview", form);
  },

  async importLeads(
    file: File,
    mapping: Record<string, string>
  ): Promise<ImportResultOut> {
    const form = new FormData();
    form.append("file", file);
    form.append("mapping", JSON.stringify(mapping));
    return requestForm<ImportResultOut>("/v1/leads/import", form);
  },

  async signup(input: SignupInput): Promise<TokenPair> {
    return request<TokenPair>("/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        email: input.email,
        password: input.password,
        tenant_name: input.tenantName,
        tenant_slug: input.tenantSlug,
      }),
    });
  },

  async login(input: { email: string; password: string }): Promise<TokenPair> {
    return request<TokenPair>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  async refresh(refreshToken: string): Promise<TokenPair> {
    return request<TokenPair>("/v1/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  },

  /**
   * `token` is optional: once the auth bridge has run, `request()` already
   * attaches the in-memory token. Callers during sign-in, before the bridge
   * is wired, pass it explicitly.
   */
  me(token?: string): Promise<UserOut> {
    return request<UserOut>(
      "/v1/auth/me",
      token ? { headers: { Authorization: `Bearer ${token}` } } : {}
    );
  },

  // -- tenant --
  async getMyTenant(): Promise<TenantOut> {
    return request<TenantOut>("/v1/tenants/me");
  },

  // -- credentials --
  async listCredentials(): Promise<CredentialOut[]> {
    return request<CredentialOut[]>("/v1/credentials");
  },
  async createCredential(input: {
    kind: string;
    label: string;
    secret_payload: Record<string, unknown>;
  }): Promise<CredentialOut> {
    return request<CredentialOut>("/v1/credentials", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async deleteCredential(id: string): Promise<void> {
    return request<void>(`/v1/credentials/${id}`, { method: "DELETE" });
  },
  async testCredential(
    id: string
  ): Promise<{ ok: boolean; message: string; verified_live: boolean }> {
    return request<{ ok: boolean; message: string; verified_live: boolean }>(
      `/v1/credentials/${id}/test`,
      { method: "POST" }
    );
  },
  /** The connectable providers, and whether this workspace has wired each up. */
  async listProviders(): Promise<ProviderOut[]> {
    return request<ProviderOut[]>("/v1/credentials/providers");
  },

  // -- onboarding --
  async getOnboarding(): Promise<OnboardingStatusOut> {
    return request<OnboardingStatusOut>("/v1/onboarding");
  },
  async dismissOnboarding(dismissed: boolean): Promise<OnboardingStatusOut> {
    return request<OnboardingStatusOut>("/v1/onboarding/dismiss", {
      method: "POST",
      body: JSON.stringify({ dismissed }),
    });
  },
  async getLlmSettings(): Promise<LlmSettingsOut> {
    return request<LlmSettingsOut>("/v1/onboarding/llm-settings");
  },
  async updateLlmSettings(input: {
    default_llm_model: string | null;
    embedding_llm_model: string | null;
  }): Promise<LlmSettingsOut> {
    return request<LlmSettingsOut>("/v1/onboarding/llm-settings", {
      method: "PUT",
      body: JSON.stringify(input),
    });
  },

  // -- mailboxes --
  async listMailboxes(): Promise<MailboxOut[]> {
    return request<MailboxOut[]>("/v1/mailboxes");
  },
  async deleteMailbox(id: string): Promise<void> {
    return request<void>(`/v1/mailboxes/${id}`, { method: "DELETE" });
  },
  async gmailOAuthStart(): Promise<{ auth_url: string; state: string }> {
    return request<{ auth_url: string; state: string }>(
      "/v1/mailboxes/oauth/gmail/start"
    );
  },
  async outlookOAuthStart(): Promise<{ auth_url: string; state: string }> {
    return request<{ auth_url: string; state: string }>(
      "/v1/mailboxes/oauth/outlook/start"
    );
  },
  async createSmtpMailbox(input: {
    host: string;
    port: number;
    username: string;
    password: string;
    email_address: string;
    use_tls: boolean;
    daily_send_cap: number;
  }): Promise<MailboxOut> {
    return request<MailboxOut>("/v1/mailboxes/smtp", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async sendTest(mailboxId: string, input: { to: string; subject: string; body: string }): Promise<{ ok: boolean; message: string }> {
    return request<{ ok: boolean; message: string }>(
      `/v1/mailboxes/${mailboxId}/send-test`,
      { method: "POST", body: JSON.stringify(input) }
    );
  },

  // -- audit --
  async listAudit(params: {
    action?: string;
    actor_kind?: "user" | "system" | "agent";
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<AuditPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
    return request<AuditPage>(`/v1/audit?${usp.toString()}`);
  },
  auditCsvUrl(): string {
    return `${API_URL}/v1/audit/export.csv`;
  },
  auditJsonUrl(): string {
    return `${API_URL}/v1/audit/export.json`;
  },

  // -- Notifications --
  async listNotifications(params: {
    event_key?: string;
    unread_only?: boolean;
    limit?: number;
    offset?: number;
  } = {}): Promise<NotificationPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) usp.append(k, String(v));
    });
    return request<NotificationPage>(`/v1/notifications?${usp.toString()}`);
  },
  async unreadCount(): Promise<{ unread: number }> {
    return request<{ unread: number }>("/v1/notifications/unread_count");
  },
  async notificationEvents(): Promise<{ events: string[] }> {
    return request<{ events: string[] }>("/v1/notifications/events");
  },
  async markNotificationsRead(ids: string[]): Promise<{ updated: number }> {
    return request<{ updated: number }>("/v1/notifications/mark_read", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
  },

  // -- Notification preferences --
  async listPreferences(): Promise<NotificationPreferencePage> {
    return request<NotificationPreferencePage>("/v1/notification-preferences");
  },
  async upsertPreference(input: NotificationPreferenceIn): Promise<NotificationPreferenceOut> {
    return request<NotificationPreferenceOut>("/v1/notification-preferences", {
      method: "PUT",
      body: JSON.stringify(input),
    });
  },

  // -- Slack webhooks --
  async listSlackWebhooks(): Promise<SlackWebhookOut[]> {
    return request<SlackWebhookOut[]>("/v1/slack-webhooks");
  },
  async createSlackWebhook(input: SlackWebhookIn): Promise<SlackWebhookOut> {
    return request<SlackWebhookOut>("/v1/slack-webhooks", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async pauseSlackWebhook(id: string): Promise<SlackWebhookOut> {
    return request<SlackWebhookOut>(`/v1/slack-webhooks/${id}/pause`, { method: "POST" });
  },
  async resumeSlackWebhook(id: string): Promise<SlackWebhookOut> {
    return request<SlackWebhookOut>(`/v1/slack-webhooks/${id}/resume`, { method: "POST" });
  },
  async deleteSlackWebhook(id: string): Promise<void> {
    return request<void>(`/v1/slack-webhooks/${id}`, { method: "DELETE" });
  },

  // -- Billing --
  async listPlans(): Promise<PlanListOut> {
    return request<PlanListOut>("/v1/billing/plans");
  },
  async getSubscription(): Promise<SubscriptionOut | null> {
    return request<SubscriptionOut | null>("/v1/billing/subscription");
  },
  async getUsage(): Promise<UsageSummaryOut> {
    return request<UsageSummaryOut>("/v1/billing/usage");
  },
  async startCheckout(planCode: string): Promise<CheckoutOut> {
    return request<CheckoutOut>("/v1/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan_code: planCode }),
    });
  },
  async startPortal(): Promise<PortalOut> {
    return request<PortalOut>("/v1/billing/portal", {
      method: "POST",
      body: JSON.stringify({}),
    });
  },
  portalRedirectUrl(token: string): string {
    const base = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
    return `${base}/v1/billing/portal/redirect?token=${encodeURIComponent(token)}`;
  },

  // -- ICPs --
  async listIcps(): Promise<IcpOut[]> {
    return request<IcpOut[]>("/v1/icps");
  },
  async createIcp(input: IcpInput): Promise<IcpOut> {
    return request<IcpOut>("/v1/icps", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async getIcp(id: string): Promise<IcpOut> {
    return request<IcpOut>(`/v1/icps/${id}`);
  },
  async updateIcp(id: string, input: Partial<IcpInput>): Promise<IcpOut> {
    return request<IcpOut>(`/v1/icps/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },
  async deleteIcp(id: string): Promise<void> {
    return request<void>(`/v1/icps/${id}`, { method: "DELETE" });
  },
  async launchScrape(icpId: string, input: Omit<ScrapingJobInput, "icp_id">): Promise<ScrapingJobOut> {
    return request<ScrapingJobOut>(`/v1/icps/${icpId}/scrape`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  // -- lead sources --
  async listLeadSources(): Promise<LeadSourceOut[]> {
    return request<LeadSourceOut[]>("/v1/lead-sources");
  },
  async updateLeadSource(
    source: string,
    input: LeadSourceUpdate
  ): Promise<LeadSourceOut> {
    return request<LeadSourceOut>(`/v1/lead-sources/${source}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },

  // -- leads --
  async listLeads(params: {
    source?: string;
    job_id?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<LeadPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
    return request<LeadPage>(`/v1/leads?${usp.toString()}`);
  },
  async deleteLead(id: string): Promise<void> {
    return request<void>(`/v1/leads/${id}`, { method: "DELETE" });
  },

  // -- scraping jobs --
  async listScrapingJobs(params: {
    icp_id?: string;
    status?: ScrapingJobStatus;
    limit?: number;
    offset?: number;
  } = {}): Promise<{ items: ScrapingJobOut[]; total: number; limit: number; offset: number }> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
    return request(`/v1/scraping-jobs?${usp.toString()}`);
  },
  async getScrapingJob(id: string): Promise<ScrapingJobOut> {
    return request<ScrapingJobOut>(`/v1/scraping-jobs/${id}`);
  },

  // -- proxies --
  async listProxies(): Promise<ProxyOut[]> {
    return request<ProxyOut[]>("/v1/proxies");
  },
  async createProxy(input: ProxyInput): Promise<ProxyOut> {
    return request<ProxyOut>("/v1/proxies", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async deleteProxy(id: string): Promise<void> {
    return request<void>(`/v1/proxies/${id}`, { method: "DELETE" });
  },

  // -- campaigns --
  async listCampaigns(): Promise<CampaignOut[]> {
    return request<CampaignOut[]>("/v1/campaigns");
  },
  async getCampaign(id: string): Promise<CampaignOut> {
    return request<CampaignOut>(`/v1/campaigns/${id}`);
  },
  async createCampaign(input: CampaignInput): Promise<CampaignOut> {
    return request<CampaignOut>("/v1/campaigns", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async updateCampaign(id: string, input: CampaignUpdate): Promise<CampaignOut> {
    return request<CampaignOut>(`/v1/campaigns/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },
  async deleteCampaign(id: string): Promise<void> {
    return request<void>(`/v1/campaigns/${id}`, { method: "DELETE" });
  },
  async replaceCampaignSteps(
    id: string,
    steps: CampaignStepInput[]
  ): Promise<CampaignOut> {
    return request<CampaignOut>(`/v1/campaigns/${id}/steps`, {
      method: "PUT",
      body: JSON.stringify(steps),
    });
  },

  // -- knowledge --
  async listKnowledge(params: {
    source?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<KnowledgePage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
    return request<KnowledgePage>(`/v1/knowledge?${usp.toString()}`);
  },
  async getKnowledge(id: string): Promise<KnowledgeItemOut> {
    return request<KnowledgeItemOut>(`/v1/knowledge/${id}`);
  },
  async createKnowledge(input: KnowledgeItemCreate): Promise<KnowledgeItemOut> {
    return request<KnowledgeItemOut>("/v1/knowledge", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async deleteKnowledge(id: string): Promise<void> {
    return request<void>(`/v1/knowledge/${id}`, { method: "DELETE" });
  },

  // -- drafts --
  async listDrafts(params: {
    campaign_id?: string;
    status?: DraftStatus;
    limit?: number;
    offset?: number;
  } = {}): Promise<DraftPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
    return request<DraftPage>(`/v1/drafts?${usp.toString()}`);
  },
  async getDraft(
    id: string,
    opts: { include_body?: boolean } = {}
  ): Promise<DraftOut> {
    const usp = new URLSearchParams();
    if (opts.include_body) usp.append("include_body", "true");
    const qs = usp.toString();
    return request<DraftOut>(`/v1/drafts/${id}${qs ? `?${qs}` : ""}`);
  },
  async updateDraft(id: string, input: DraftUpdate): Promise<DraftOut> {
    return request<DraftOut>(`/v1/drafts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },
  async generateDraft(input: {
    lead_id: string;
    step_id: string;
    force_regenerate?: boolean;
  }): Promise<DraftOut> {
    return request<DraftOut>("/v1/drafts/generate", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  // -- agent runs --
  async listAgentRuns(params: { campaign_id?: string; limit?: number } = {}): Promise<AgentRunOut[]> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
    return request<AgentRunOut[]>(`/v1/agent-runs?${usp.toString()}`);
  },

  // -- sequences --
  async listSequences(params: { limit?: number; offset?: number } = {}): Promise<SequenceRunOut[]> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) usp.append(k, String(v));
    });
    return request<SequenceRunOut[]>(`/v1/sequences?${usp.toString()}`);
  },
  async getSequence(id: string): Promise<SequenceRunOut> {
    return request<SequenceRunOut>(`/v1/sequences/${id}`);
  },
  async startSequence(input: SequenceRunStartIn): Promise<SequenceRunOut> {
    return request<SequenceRunOut>("/v1/sequences", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async stopSequence(id: string): Promise<SequenceRunOut> {
    return request<SequenceRunOut>(`/v1/sequences/${id}/stop`, {
      method: "POST",
    });
  },

  // -- sends --
  async listSends(params: {
    run_id?: string;
    step_id?: string;
    status?: SendStatus;
    limit?: number;
    offset?: number;
  } = {}): Promise<SendPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
    return request<SendPage>(`/v1/sends?${usp.toString()}`);
  },
  async getSend(id: string): Promise<SendOut> {
    return request<SendOut>(`/v1/sends/${id}`);
  },

  // -- replies --
  async listReplies(params: {
    run_id?: string;
    classification?: ReplyClassification;
    limit?: number;
    offset?: number;
  } = {}): Promise<ReplyPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") usp.append(k, String(v));
    });
    return request<ReplyPage>(`/v1/replies?${usp.toString()}`);
  },

  // -- suppressions --
  async listSuppressions(params: { limit?: number; offset?: number } = {}): Promise<SuppressionPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) usp.append(k, String(v));
    });
    return request<SuppressionPage>(`/v1/suppressions?${usp.toString()}`);
  },
  async addSuppression(input: SuppressionCreateIn): Promise<SuppressionOut> {
    return request<SuppressionOut>("/v1/suppressions", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async removeSuppression(email: string): Promise<void> {
    return request<void>(`/v1/suppressions/${encodeURIComponent(email)}`, {
      method: "DELETE",
    });
  },

  // --- Phase 5: meetings ---

  async listMeetings(params: {
    status?: string;
    lead_id?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<MeetingPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) usp.append(k, String(v));
    });
    const q = usp.toString();
    return request<MeetingPage>(`/v1/meetings${q ? `?${q}` : ""}`);
  },
  async getMeeting(id: string): Promise<MeetingOut> {
    return request<MeetingOut>(`/v1/meetings/${id}`);
  },
  async confirmMeeting(id: string, slot_index: number): Promise<MeetingOut> {
    return request<MeetingOut>(`/v1/meetings/${id}/confirm`, {
      method: "POST",
      body: JSON.stringify({ slot_index }),
    });
  },
  async declineMeeting(id: string): Promise<MeetingOut> {
    return request<MeetingOut>(`/v1/meetings/${id}/decline`, {
      method: "POST",
    });
  },
  async cancelMeeting(id: string): Promise<MeetingOut> {
    return request<MeetingOut>(`/v1/meetings/${id}/cancel`, {
      method: "POST",
    });
  },

  // --- Phase 5: CRM connections ---

  async listCrmConnections(params: {
    status?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<CrmConnectionPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) usp.append(k, String(v));
    });
    const q = usp.toString();
    return request<CrmConnectionPage>(
      `/v1/crm/connections${q ? `?${q}` : ""}`
    );
  },
  async createCrmConnection(input: CrmConnectionCreateIn): Promise<CrmConnectionOut> {
    return request<CrmConnectionOut>("/v1/crm/connections", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
  async updateCrmConnection(
    id: string,
    input: CrmConnectionUpdateIn
  ): Promise<CrmConnectionOut> {
    return request<CrmConnectionOut>(`/v1/crm/connections/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },
  async deleteCrmConnection(id: string): Promise<void> {
    return request<void>(`/v1/crm/connections/${id}`, {
      method: "DELETE",
    });
  },
  async syncCrmConnection(
    connectionId: string,
    meetingId: string
  ): Promise<CrmSyncEventPage> {
    const usp = new URLSearchParams({ meeting_id: meetingId });
    return request<CrmSyncEventPage>(
      `/v1/crm/connections/${connectionId}/sync?${usp.toString()}`,
      { method: "POST" }
    );
  },
  async listCrmSyncEvents(params: {
    connection_id?: string;
    meeting_id?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<CrmSyncEventPage> {
    const usp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) usp.append(k, String(v));
    });
    const q = usp.toString();
    return request<CrmSyncEventPage>(
      `/v1/crm/sync-events${q ? `?${q}` : ""}`
    );
  },
};

export { ApiError };

/** Bridge the api-client's in-memory token to the AuthProvider on mount. */
export function useApiAuthBridge(): void {
  const { accessToken } = useAuth();
  useEffect(() => {
    api.setAccessToken(accessToken);
  }, [accessToken]);
}
