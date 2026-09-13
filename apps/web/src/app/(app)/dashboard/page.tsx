"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SetupChecklist } from "@/components/onboarding/setup-checklist";

export default function DashboardPage() {
  const tenantQuery = useQuery({
    queryKey: ["tenant", "me"],
    queryFn: () => api.getMyTenant(),
  });
  const credsQuery = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api.listCredentials(),
  });
  const mailboxesQuery = useQuery({
    queryKey: ["mailboxes"],
    queryFn: () => api.listMailboxes(),
  });
  const icpsQuery = useQuery({
    queryKey: ["icps"],
    queryFn: () => api.listIcps(),
  });
  const leadsQuery = useQuery({
    queryKey: ["leads", { source: undefined, offset: 0 }],
    queryFn: () => api.listLeads({ limit: 1 }),
  });
  const sourcesQuery = useQuery({
    queryKey: ["lead-sources"],
    queryFn: () => api.listLeadSources(),
  });
  const campaignsQuery = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.listCampaigns(),
  });
  const draftsQuery = useQuery({
    queryKey: ["drafts", { dashboard: true }],
    queryFn: () => api.listDrafts({ limit: 1 }),
  });
  const sequencesQuery = useQuery({
    queryKey: ["sequences", { dashboard: true }],
    queryFn: () => api.listSequences({ limit: 200 }),
  });
  const repliesQuery = useQuery({
    queryKey: ["replies", { dashboard: true }],
    queryFn: () => api.listReplies({ limit: 1 }),
  });
  const meetingsQuery = useQuery({
    queryKey: ["meetings", { dashboard: true }],
    queryFn: () => api.listMeetings({ status: undefined, limit: 100 }),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          {tenantQuery.data
            ? `Workspace: ${tenantQuery.data.name}`
            : "Loading workspace…"}
        </p>
      </div>

      {/* Hides itself once every required step is done. */}
      <SetupChecklist />

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle>ICPs</CardTitle>
            <CardDescription>Target customer profiles.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {icpsQuery.data?.length ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {(icpsQuery.data?.length ?? 0) === 0
                ? "Create one to start finding leads."
                : `${(icpsQuery.data ?? []).filter((i) => i.is_active).length} active`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Leads</CardTitle>
            <CardDescription>Deduplicated by email.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {leadsQuery.data?.total ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {(sourcesQuery.data ?? []).filter((s) => s.is_enabled).length} of{" "}
              {(sourcesQuery.data ?? []).length} sources enabled
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Credentials</CardTitle>
            <CardDescription>API keys for LLM and scraping providers.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {credsQuery.data?.length ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {(credsQuery.data?.length ?? 0) === 0
                ? "Add one in Integrations to enable AI features in Phase 3."
                : "configured"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Mailboxes</CardTitle>
            <CardDescription>Connected sending accounts.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {mailboxesQuery.data?.length ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {(mailboxesQuery.data?.length ?? 0) === 0
                ? "Connect Gmail, Outlook, or SMTP to start sending in Phase 4."
                : "configured"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Outreach</CardTitle>
            <CardDescription>Active campaigns and replies.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">0</p>
            <p className="text-xs text-muted-foreground">
              Campaign engine lands in Phase 3. Until then this stays at zero.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Campaigns</CardTitle>
            <CardDescription>Multi-step outreach sequences.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {campaignsQuery.data?.length ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {(campaignsQuery.data ?? []).filter((c) => c.status === "active").length} active •{" "}
              {(campaignsQuery.data ?? []).filter((c) => c.status === "paused").length} paused
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Drafts</CardTitle>
            <CardDescription>AI-generated emails in the review queue.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {draftsQuery.data?.total ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {draftsQuery.data
                ? `${(draftsQuery.data.items ?? []).filter((d) => d.status === "ready").length} ready for review`
                : "Waiting for data"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Active sequences</CardTitle>
            <CardDescription>Outreach runs currently sending.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {sequencesQuery.data
                ? (sequencesQuery.data ?? []).filter((s) => s.status === "running").length
                : "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {(sequencesQuery.data ?? []).length === 0
                ? "Start one from Sequences to begin sending."
                : `${(sequencesQuery.data ?? []).length} total runs`}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Replies</CardTitle>
            <CardDescription>Inbound responses from leads.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {repliesQuery.data?.total ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {repliesQuery.data
                ? `${(repliesQuery.data.items ?? []).filter((r) => r.classification === "positive").length} positive`
                : "Waiting for inbound mail"}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Meetings</CardTitle>
            <CardDescription>Booked and proposed from positive replies.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">
              {meetingsQuery.data?.total ?? "—"}
            </p>
            <p className="text-xs text-muted-foreground">
              {meetingsQuery.data
                ? `${(meetingsQuery.data.items ?? []).filter((m) => m.status === "confirmed").length} confirmed · ${(meetingsQuery.data.items ?? []).filter((m) => m.status === "proposed").length} proposed`
                : "Waiting for positive replies"}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
