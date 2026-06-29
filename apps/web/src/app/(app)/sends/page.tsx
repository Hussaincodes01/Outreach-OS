"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { api, type SendOut, type SendStatus } from "@/lib/api-client";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

const STATUS_COLORS: Record<
  SendStatus,
  "default" | "secondary" | "outline" | "destructive"
> = {
  queued: "outline",
  sent: "default",
  bounced: "destructive",
  failed: "destructive",
  unsubscribed: "secondary",
  skipped: "secondary",
};

const STATUSES: Array<{ value: "" | SendStatus; label: string }> = [
  { value: "", label: "All" },
  { value: "queued", label: "Queued" },
  { value: "sent", label: "Sent" },
  { value: "bounced", label: "Bounced" },
  { value: "failed", label: "Failed" },
  { value: "unsubscribed", label: "Unsubscribed" },
  { value: "skipped", label: "Skipped" },
];

function SendPanel({
  send,
  open,
  onOpenChange,
}: {
  send: SendOut | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const detail = useQuery({
    queryKey: ["send", send?.id],
    queryFn: () => api.getSend(send!.id),
    enabled: open && !!send,
  });
  const current = detail.data ?? send;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Send className="h-4 w-4" />
            {current?.subject ?? "Send"}
          </DialogTitle>
          <DialogDescription>
            {current
              ? `To: ${current.to_email} • From: ${current.from_email} • Status: ${current.status}`
              : "Loading…"}
          </DialogDescription>
        </DialogHeader>

        {detail.isLoading && !detail.data && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}

        {current && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={STATUS_COLORS[current.status]}>{current.status}</Badge>
              {current.sent_at && (
                <Badge variant="outline">sent {formatDate(current.sent_at)}</Badge>
              )}
              {current.opened_at && (
                <Badge variant="outline">opened {formatDate(current.opened_at)}</Badge>
              )}
              {current.clicked_at && (
                <Badge variant="outline">clicked {formatDate(current.clicked_at)}</Badge>
              )}
            </div>

            {current.error && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
                <strong>Error:</strong> {current.error}
              </div>
            )}

            <div className="space-y-1.5">
              <Label>Message-ID</Label>
              <div className="break-all rounded-md border bg-muted/30 p-3 font-mono text-xs">
                {current.message_id_header ?? "—"}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Subject</Label>
              <div className="rounded-md border bg-muted/30 p-3 text-sm">
                {current.subject ?? "—"}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Body</Label>
              <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-4 text-sm">
                {current.body_text ?? "—"}
              </pre>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground md:grid-cols-4">
              <div>
                <strong className="text-foreground">Queued:</strong>{" "}
                {formatDate(current.queued_at)}
              </div>
              <div>
                <strong className="text-foreground">Sent:</strong>{" "}
                {current.sent_at ? formatDate(current.sent_at) : "—"}
              </div>
              <div>
                <strong className="text-foreground">Opened:</strong>{" "}
                {current.opened_at ? formatDate(current.opened_at) : "—"}
              </div>
              <div>
                <strong className="text-foreground">Clicked:</strong>{" "}
                {current.clicked_at ? formatDate(current.clicked_at) : "—"}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function SendsPage() {
  const [runId, setRunId] = useState("");
  const [status, setStatus] = useState<"" | SendStatus>("");
  const [viewing, setViewing] = useState<SendOut | null>(null);

  const list = useQuery({
    queryKey: ["sends", { runId, status }],
    queryFn: () =>
      api.listSends({
        run_id: runId || undefined,
        status: status || undefined,
        limit: 200,
      }),
    refetchInterval: 10_000,
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Sends</h1>
        <p className="text-muted-foreground">
          Every email that the sequencer has queued or dispatched. Click a row to inspect the
          full body, Message-ID header, and engagement events.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>
            {list.isLoading ? "Loading…" : `${total} send${total === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Run ID</Label>
              <input
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                placeholder="Filter by sequence run id…"
              />
            </div>
            <div className="space-y-1.5">
              <Label>Status</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={status}
                onChange={(e) => setStatus(e.target.value as "" | SendStatus)}
              >
                {STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Send className="h-4 w-4" />
            Outbox
          </CardTitle>
        </CardHeader>
        <CardContent>
          {list.error && (
            <p className="text-sm text-destructive">{(list.error as Error).message}</p>
          )}
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No sends match these filters. Start a sequence to populate the outbox.
            </p>
          )}
          {items.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>To</TableHead>
                  <TableHead>From</TableHead>
                  <TableHead>Subject</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Queued</TableHead>
                  <TableHead>Sent</TableHead>
                  <TableHead>Opened</TableHead>
                  <TableHead>Clicked</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((s) => (
                  <TableRow
                    key={s.id}
                    className="cursor-pointer"
                    onClick={() => setViewing(s)}
                  >
                    <TableCell className="font-mono text-xs">{s.to_email}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {s.from_email}
                    </TableCell>
                    <TableCell className="max-w-xs">
                      <div className="truncate font-medium">
                        {s.subject ?? <span className="text-muted-foreground">—</span>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_COLORS[s.status]}>{s.status}</Badge>
                      {s.status === "failed" && s.error && (
                        <p className="mt-1 max-w-xs truncate text-xs text-destructive">
                          {s.error}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(s.queued_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {s.sent_at ? formatDate(s.sent_at) : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {s.opened_at ? formatDate(s.opened_at) : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {s.clicked_at ? formatDate(s.clicked_at) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <SendPanel
        send={viewing}
        open={viewing !== null}
        onOpenChange={(o) => !o && setViewing(null)}
      />
    </div>
  );
}
