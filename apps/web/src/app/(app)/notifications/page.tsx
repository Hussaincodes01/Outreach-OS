"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCheck, Filter } from "lucide-react";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

export default function NotificationsPage() {
  const [eventKey, setEventKey] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const qc = useQueryClient();

  const list = useQuery({
    queryKey: ["notifications", { eventKey, unreadOnly }],
    queryFn: () => api.listNotifications({ event_key: eventKey || undefined, unread_only: unreadOnly, limit: 100 }),
  });
  const events = useQuery({
    queryKey: ["notifications", "events"],
    queryFn: () => api.notificationEvents(),
  });

  // WebSocket live feed: connect when authenticated, push incoming events
  // into the same query so the user sees new notifications without reload.
  const [wsStatus, setWsStatus] = useState<"idle" | "open" | "closed" | "error">("idle");
  useEffect(() => {
    const token = typeof window !== "undefined" ? window.localStorage.getItem("outreach.access_token") : null;
    if (!token) return;
    const apiUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
      .replace(/^http/i, "ws");
    const url = `${apiUrl}/v1/notifications/ws?token=${encodeURIComponent(token)}`;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let active = true;
    function connect() {
      ws = new WebSocket(url);
      ws.onopen = () => setWsStatus("open");
      ws.onerror = () => setWsStatus("error");
      ws.onclose = () => {
        setWsStatus("closed");
        if (active) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };
      ws.onmessage = () => {
        // Any inbound event triggers a refetch.
        qc.invalidateQueries({ queryKey: ["notifications"] });
      };
    }
    connect();
    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [qc]);

  const markRead = useMutation({
    mutationFn: (ids: string[]) => api.markNotificationsRead(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Notifications</h1>
          <p className="text-muted-foreground">
            Live feed of events from your workspace.
            {wsStatus === "open" && <span className="ml-2 text-green-600">● live</span>}
            {wsStatus === "closed" && <span className="ml-2 text-muted-foreground">○ reconnecting…</span>}
            {wsStatus === "error" && <span className="ml-2 text-red-600">○ error</span>}
          </p>
        </div>
        <Button
          variant="outline"
          disabled={!list.data || list.data.unread === 0}
          onClick={() => {
            const ids = (list.data?.items ?? []).filter((n) => !n.read_at).map((n) => n.id);
            if (ids.length) markRead.mutate(ids);
          }}
        >
          <CheckCheck className="mr-2 h-4 w-4" />
          Mark all as read
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Events</CardTitle>
          <CardDescription>Most recent first.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Filter by event_key (e.g. reply.positive)"
              value={eventKey}
              onChange={(e) => setEventKey(e.target.value)}
              className="max-w-xs"
            />
            <label className="ml-2 flex items-center gap-1 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(e) => setUnreadOnly(e.target.checked)}
              />
              Unread only
            </label>
          </div>

          {list.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {list.data && list.data.items.length === 0 && (
            <p className="text-sm text-muted-foreground">No notifications yet.</p>
          )}

          {list.data && list.data.items.length > 0 && (
            <ul className="space-y-2">
              {list.data.items.map((n) => (
                <li
                  key={n.id}
                  className={
                    "rounded border p-3 text-sm " +
                    (n.read_at ? "opacity-70" : "border-l-4 border-l-blue-500")
                  }
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={
                          n.severity === "error"
                            ? "destructive"
                            : n.severity === "success"
                            ? "default"
                            : "secondary"
                        }
                      >
                        {n.severity}
                      </Badge>
                      <span className="font-medium">{n.title}</span>
                      {!n.read_at && <Badge variant="outline">new</Badge>}
                    </div>
                    <span className="text-xs text-muted-foreground">{formatDate(n.created_at)}</span>
                  </div>
                  {n.body && <p className="mt-1 text-muted-foreground">{n.body}</p>}
                  <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">{n.event_key}</span>
                    {n.target_type && (
                      <>
                        <span>·</span>
                        <span className="font-mono">
                          {n.target_type}:{n.target_id?.slice(0, 8)}
                        </span>
                      </>
                    )}
                    {(n.delivered_email || n.delivered_slack) && (
                      <>
                        <span>·</span>
                        <span>
                          {n.delivered_email && "email"}
                          {n.delivered_email && n.delivered_slack && " + "}
                          {n.delivered_slack && "slack"}
                        </span>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}

          {list.data && (
            <p className="mt-3 text-xs text-muted-foreground">
              {list.data.unread} unread of {list.data.total} total
              {events.data && events.data.events.length > 0 && (
                <>
                  {" "}
                  · {events.data.events.length} event types available
                </>
              )}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
