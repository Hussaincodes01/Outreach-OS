"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check, Slack, Trash2, Webhook } from "lucide-react";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

export default function SettingsPage() {
  const tenant = useQuery({
    queryKey: ["tenant", "me"],
    queryFn: () => api.getMyTenant(),
  });
  const events = useQuery({
    queryKey: ["notifications", "events"],
    queryFn: () => api.notificationEvents(),
  });
  const prefs = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: () => api.listPreferences(),
  });
  const webhooks = useQuery({
    queryKey: ["slack-webhooks"],
    queryFn: () => api.listSlackWebhooks(),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Workspace, notification channels, integrations.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Workspace</CardTitle>
          <CardDescription>
            Plan and billing management land in Phase 7. Until then, plan is read-only.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {tenant.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {tenant.data && (
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-muted-foreground">Name</dt>
                <dd className="font-medium">{tenant.data.name}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Slug</dt>
                <dd className="font-mono">{tenant.data.slug}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <Badge variant="secondary">{tenant.data.status}</Badge>
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Plan</dt>
                <dd>
                  <Badge variant="outline">{tenant.data.plan}</Badge>
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-muted-foreground">Created</dt>
                <dd>{formatDate(tenant.data.created_at)}</dd>
              </div>
            </dl>
          )}
        </CardContent>
      </Card>

      <NotificationPreferencesCard
        eventsLoading={events.isLoading}
        events={events.data?.events ?? []}
        prefsLoading={prefs.isLoading}
        prefs={prefs.data?.items ?? []}
        refetchPrefs={prefs.refetch}
      />

      <SlackWebhooksCard
        webhooks={webhooks.data ?? []}
        webhooksLoading={webhooks.isLoading}
        refetch={webhooks.refetch}
      />
    </div>
  );
}

function NotificationPreferencesCard(props: {
  eventsLoading: boolean;
  events: string[];
  prefsLoading: boolean;
  prefs: { event_key: string; channel_in_app: boolean; channel_email_digest: boolean; channel_slack: boolean }[];
  refetchPrefs: () => void;
}) {
  const qc = useQueryClient();
  const upsert = useMutation({
    mutationFn: (input: {
      event_key: string;
      channel_in_app: boolean;
      channel_email_digest: boolean;
      channel_slack: boolean;
    }) => api.upsertPreference(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notification-preferences"] });
    },
  });

  const current = useMemo(() => {
    const m: Record<string, { channel_in_app: boolean; channel_email_digest: boolean; channel_slack: boolean }> = {};
    for (const p of props.prefs) m[p.event_key] = p;
    return m;
  }, [props.prefs]);

  function getOrDefault(event: string) {
    return (
      current[event] ?? {
        channel_in_app: true,
        channel_email_digest: false,
        channel_slack: false,
      }
    );
  }

  function toggle(event: string, channel: "channel_in_app" | "channel_email_digest" | "channel_slack", value: boolean) {
    const cur = getOrDefault(event);
    upsert.mutate({ event_key: event, ...cur, [channel]: value });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="h-4 w-4" /> Notification channels
        </CardTitle>
        <CardDescription>
          Choose which events fire on which channels. In-app is on by default.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {props.eventsLoading || props.prefsLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="py-2 font-medium">Event</th>
                  <th className="px-2 font-medium">In-app</th>
                  <th className="px-2 font-medium">Email digest</th>
                  <th className="px-2 font-medium">Slack</th>
                </tr>
              </thead>
              <tbody>
                {props.events.map((ev) => {
                  const cur = getOrDefault(ev);
                  return (
                    <tr key={ev} className="border-t">
                      <td className="py-2 font-mono text-xs">{ev}</td>
                      <td className="px-2">
                        <input
                          type="checkbox"
                          checked={cur.channel_in_app}
                          onChange={(e) => toggle(ev, "channel_in_app", e.target.checked)}
                        />
                      </td>
                      <td className="px-2">
                        <input
                          type="checkbox"
                          checked={cur.channel_email_digest}
                          onChange={(e) => toggle(ev, "channel_email_digest", e.target.checked)}
                        />
                      </td>
                      <td className="px-2">
                        <input
                          type="checkbox"
                          checked={cur.channel_slack}
                          onChange={(e) => toggle(ev, "channel_slack", e.target.checked)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SlackWebhooksCard(props: {
  webhooks: { id: string; name: string; channel: string | null; status: string; last_error: string | null; last_delivered_at: string | null }[];
  webhooksLoading: boolean;
  refetch: () => void;
}) {
  const qc = useQueryClient();
  const [url, setUrl] = useState("");
  const [channel, setChannel] = useState("");
  const create = useMutation({
    mutationFn: (input: { webhook_url: string; channel?: string }) => api.createSlackWebhook(input),
    onSuccess: () => {
      setUrl("");
      setChannel("");
      qc.invalidateQueries({ queryKey: ["slack-webhooks"] });
    },
  });
  const pause = useMutation({
    mutationFn: (id: string) => api.pauseSlackWebhook(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["slack-webhooks"] }),
  });
  const resume = useMutation({
    mutationFn: (id: string) => api.resumeSlackWebhook(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["slack-webhooks"] }),
  });
  const del = useMutation({
    mutationFn: (id: string) => api.deleteSlackWebhook(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["slack-webhooks"] }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Slack className="h-4 w-4" /> Slack webhooks
        </CardTitle>
        <CardDescription>
          Get a webhook URL from Slack (incoming webhooks app) and paste it here. Channels can be
          overridden per webhook.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {props.webhooksLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ul className="space-y-2">
            {props.webhooks.map((h) => (
              <li key={h.id} className="flex items-center justify-between rounded border p-3 text-sm">
                <div className="space-y-1">
                  <div className="font-medium">
                    {h.name}{" "}
                    <Badge variant={h.status === "active" ? "default" : "destructive"}>{h.status}</Badge>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    channel: <span className="font-mono">{h.channel ?? "(default)"}</span>
                    {h.last_delivered_at && (
                      <> · last delivered: {formatDate(h.last_delivered_at)}</>
                    )}
                    {h.last_error && (
                      <> · last error: <span className="text-red-600">{h.last_error}</span></>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {h.status === "active" ? (
                    <Button variant="ghost" size="sm" onClick={() => pause.mutate(h.id)}>
                      Pause
                    </Button>
                  ) : (
                    <Button variant="ghost" size="sm" onClick={() => resume.mutate(h.id)}>
                      <Check className="mr-1 h-4 w-4" /> Resume
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => del.mutate(h.id)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </li>
            ))}
            {props.webhooks.length === 0 && (
              <li className="text-sm text-muted-foreground">No Slack webhooks configured.</li>
            )}
          </ul>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!url) return;
            create.mutate({ webhook_url: url, channel: channel || undefined });
          }}
          className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_180px_auto]"
        >
          <Input
            placeholder="https://hooks.slack.com/services/T0/B0/XXX"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            type="url"
            required
          />
          <Input
            placeholder="#channel (optional)"
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
          />
          <Button type="submit" disabled={create.isPending}>
            <Webhook className="mr-2 h-4 w-4" />
            Add webhook
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
