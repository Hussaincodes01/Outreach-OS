"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type CrmConnectionOut,
  type CrmSyncEventOut,
} from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

const STATUS_COLORS: Record<
  "active" | "paused" | "error",
  "default" | "secondary" | "destructive" | "outline"
> = {
  active: "default",
  paused: "secondary",
  error: "destructive",
};

function NewConnectionForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (input: {
    name: string;
    spreadsheet_id: string;
    sheet_range: string;
    column_mapping: Record<string, string>;
  }) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [spreadsheetId, setSpreadsheetId] = useState("");
  const [sheetRange, setSheetRange] = useState("Leads!A:E");
  const [firstNameCol, setFirstNameCol] = useState("A");
  const [emailCol, setEmailCol] = useState("B");
  const [companyCol, setCompanyCol] = useState("C");
  const [meetingStartCol, setMeetingStartCol] = useState("D");
  const [meetingStatusCol, setMeetingStatusCol] = useState("E");

  function handleSubmit() {
    if (!name || !spreadsheetId) {
      toast.error("Name and spreadsheet_id are required");
      return;
    }
    onSubmit({
      name,
      spreadsheet_id: spreadsheetId,
      sheet_range: sheetRange,
      column_mapping: {
        first_name: firstNameCol,
        email: emailCol,
        company_name: companyCol,
        meeting_start: meetingStartCol,
        meeting_status: meetingStatusCol,
      },
    });
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        handleSubmit();
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="crm_name">Name</Label>
        <Input
          id="crm_name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="e.g. Acme Q4 sales"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="crm_sheet">Google Sheets ID</Label>
        <Input
          id="crm_sheet"
          value={spreadsheetId}
          onChange={(e) => setSpreadsheetId(e.target.value)}
          required
          placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        />
        <p className="text-[10px] text-muted-foreground">
          The long ID from the sheet URL.
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="crm_range">Sheet range</Label>
        <Input
          id="crm_range"
          value={sheetRange}
          onChange={(e) => setSheetRange(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label>Column mapping</Label>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          {[
            ["first_name", firstNameCol, setFirstNameCol],
            ["email", emailCol, setEmailCol],
            ["company_name", companyCol, setCompanyCol],
            ["meeting_start", meetingStartCol, setMeetingStartCol],
            ["meeting_status", meetingStatusCol, setMeetingStatusCol],
          ].map(([field, val, setter]) => (
            <div key={field as string} className="space-y-1">
              <span className="text-[10px] text-muted-foreground">
                {field as string}
              </span>
              <Input
                value={val as string}
                onChange={(e) => (setter as (v: string) => void)(e.target.value.toUpperCase())}
                className="h-8 font-mono"
                maxLength={3}
              />
            </div>
          ))}
        </div>
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit">
          <Plus className="mr-1 h-3 w-3" />
          Create
        </Button>
      </div>
    </form>
  );
}

function SyncEventList({ connectionId }: { connectionId: string }) {
  const events = useQuery({
    queryKey: ["crm-sync-events", { connection_id: connectionId }],
    queryFn: () =>
      api.listCrmSyncEvents({ connection_id: connectionId, limit: 20 }),
  });
  const items: CrmSyncEventOut[] = events.data?.items ?? [];
  if (events.isLoading) {
    return <p className="text-xs text-muted-foreground">Loading…</p>;
  }
  if (items.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No syncs yet. Confirmed meetings will appear here.
      </p>
    );
  }
  return (
    <div className="space-y-1 text-xs">
      {items.map((e) => (
        <div
          key={e.id}
          className="flex items-center justify-between rounded border p-2"
        >
          <div>
            <Badge
              variant={e.status === "success" ? "default" : "destructive"}
            >
              {e.status}
            </Badge>{" "}
            <span className="font-mono text-[10px] text-muted-foreground">
              {e.meeting_id?.slice(0, 8) ?? "(no meeting)"}…
            </span>
            {e.error && (
              <span className="ml-2 text-destructive">{e.error}</span>
            )}
          </div>
          <span className="text-muted-foreground">
            {formatDate(e.synced_at)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function CrmPage() {
  const queryClient = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const list = useQuery({
    queryKey: ["crm-connections"],
    queryFn: () => api.listCrmConnections({ limit: 100 }),
  });

  const create = useMutation({
    mutationFn: api.createCrmConnection,
    onSuccess: () => {
      toast.success("Connection created");
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["crm-connections"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const updateStatus = useMutation({
    mutationFn: (args: { id: string; status: "active" | "paused" }) =>
      api.updateCrmConnection(args.id, { status: args.status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["crm-connections"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteCrmConnection(id),
    onSuccess: () => {
      toast.success("Connection removed");
      queryClient.invalidateQueries({ queryKey: ["crm-connections"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">CRM sync</h1>
          <p className="text-muted-foreground">
            Connect your CRM (Google Sheets in v1) to receive a new row for
            every confirmed meeting. Each connection is tenant-scoped and
            RLS-isolated.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New connection
        </Button>
      </div>

      {createOpen && (
        <Card>
          <CardHeader>
            <CardTitle>New CRM connection</CardTitle>
            <CardDescription>
              Pick a Google Sheet and map Outreach OS fields to columns.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <NewConnectionForm
              onCancel={() => setCreateOpen(false)}
              onSubmit={(input) => create.mutate(input)}
            />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            Your connections
          </CardTitle>
          <CardDescription>
            {list.isLoading
              ? "Loading…"
              : `${total} connection${total === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {list.error && (
            <p className="text-sm text-destructive">
              {(list.error as Error).message}
            </p>
          )}
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No CRM connections yet. Add one to start pushing confirmed
              meetings to your sheet.
            </p>
          )}
          {items.map((c) => (
            <div key={c.id} className="rounded-md border">
              <div className="flex items-center justify-between gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{c.name}</span>
                    <Badge variant={STATUS_COLORS[c.status]}>
                      {c.status}
                    </Badge>
                    <Badge variant="outline">{c.provider}</Badge>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {c.spreadsheet_id ?? "(no spreadsheet)"} ·{" "}
                    {c.sheet_range ?? "A:Z"}
                  </p>
                  {c.last_sync_at && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Last sync {formatDate(c.last_sync_at)}
                      {c.last_sync_error && (
                        <span className="ml-2 text-destructive">
                          {c.last_sync_error}
                        </span>
                      )}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setExpandedId(expandedId === c.id ? null : c.id)
                    }
                  >
                    {expandedId === c.id ? "Hide" : "History"}
                  </Button>
                  {c.status === "active" ? (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        updateStatus.mutate({ id: c.id, status: "paused" })
                      }
                    >
                      Pause
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        updateStatus.mutate({ id: c.id, status: "active" })
                      }
                    >
                      Resume
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      if (window.confirm(`Delete "${c.name}"?`)) {
                        remove.mutate(c.id);
                      }
                    }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
              {expandedId === c.id && (
                <div className="space-y-2 border-t bg-muted/20 p-4">
                  <p className="text-xs font-medium">Recent sync events</p>
                  <SyncEventList connectionId={c.id} />
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
