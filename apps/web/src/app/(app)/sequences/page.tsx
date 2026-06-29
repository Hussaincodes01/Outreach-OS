"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Pause, Play, Plus, Send } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type CampaignOut,
  type LeadOut,
  type SequenceRunOut,
  type SequenceRunStartIn,
  type SequenceStatus,
} from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

const STATUS_COLORS: Record<
  SequenceStatus,
  "default" | "secondary" | "outline" | "destructive"
> = {
  running: "default",
  paused: "secondary",
  stopped: "destructive",
  completed: "outline",
};

function NewSequenceForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (values: SequenceRunStartIn) => void;
  onCancel: () => void;
}) {
  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.listCampaigns(),
  });
  const leads = useQuery({
    queryKey: ["leads", { for_sequence: true }],
    queryFn: () => api.listLeads({ limit: 200 }),
  });

  const [name, setName] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [startAt, setStartAt] = useState("");
  const [ignoreCaps, setIgnoreCaps] = useState(false);
  const [leadFilter, setLeadFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const campaignList: CampaignOut[] = campaigns.data ?? [];
  const leadList: LeadOut[] = useMemo(
    () => leads.data?.items ?? [],
    [leads.data]
  );

  const filteredLeads = useMemo(() => {
    const q = leadFilter.trim().toLowerCase();
    if (!q) return leadList;
    return leadList.filter((l) => {
      const email = l.email ?? "";
      const name = `${l.first_name ?? ""} ${l.last_name ?? ""} ${l.full_name ?? ""}`.trim();
      const company = l.company_name ?? "";
      return (
        email.toLowerCase().includes(q) ||
        name.toLowerCase().includes(q) ||
        company.toLowerCase().includes(q)
      );
    });
  }, [leadList, leadFilter]);

  function toggleLead(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllVisible() {
    const visibleIds = filteredLeads.map((l) => l.id);
    const allSelected = visibleIds.every((id) => selected.has(id));
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        visibleIds.forEach((id) => next.delete(id));
      } else {
        visibleIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  function handleSubmit() {
    if (!campaignId) {
      toast.error("Pick a campaign");
      return;
    }
    if (selected.size === 0) {
      toast.error("Select at least one lead");
      return;
    }
    onSubmit({
      campaign_id: campaignId,
      name,
      lead_ids: Array.from(selected),
      start_at: startAt ? new Date(startAt).toISOString() : null,
      ignore_caps: ignoreCaps,
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
        <Label htmlFor="seq_name">Name</Label>
        <Input
          id="seq_name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="e.g. Acme Q4 founders"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="seq_campaign">Campaign</Label>
        <select
          id="seq_campaign"
          required
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
          value={campaignId}
          onChange={(e) => setCampaignId(e.target.value)}
        >
          <option value="">Pick a campaign…</option>
          {campaignList.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="seq_start">Start at (optional)</Label>
        <Input
          id="seq_start"
          type="datetime-local"
          value={startAt}
          onChange={(e) => setStartAt(e.target.value)}
        />
        <p className="text-[10px] text-muted-foreground">
          Leave blank to start immediately.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <input
          id="seq_caps"
          type="checkbox"
          checked={ignoreCaps}
          onChange={(e) => setIgnoreCaps(e.target.checked)}
          className="h-4 w-4 rounded border-input"
        />
        <Label htmlFor="seq_caps" className="cursor-pointer text-xs font-normal">
          Ignore mailbox daily caps (not recommended)
        </Label>
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label>Leads ({selected.size} selected)</Label>
          <div className="flex items-center gap-2">
            <Input
              value={leadFilter}
              onChange={(e) => setLeadFilter(e.target.value)}
              placeholder="Filter…"
              className="h-8 w-40 text-xs"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={toggleAllVisible}
            >
              {filteredLeads.every((l) => selected.has(l.id)) ? "Clear" : "All"}
            </Button>
          </div>
        </div>
        <div className="max-h-64 space-y-1 overflow-auto rounded-md border p-2">
          {leads.isLoading && (
            <p className="p-2 text-xs text-muted-foreground">Loading leads…</p>
          )}
          {leads.data && filteredLeads.length === 0 && (
            <p className="p-2 text-xs text-muted-foreground">
              {leadList.length === 0
                ? "No leads in the workspace yet."
                : "No leads match this filter."}
            </p>
          )}
          {filteredLeads.map((l) => {
            const display = l.full_name || `${l.first_name ?? ""} ${l.last_name ?? ""}`.trim();
            return (
              <label
                key={l.id}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs hover:bg-muted/50"
              >
                <input
                  type="checkbox"
                  checked={selected.has(l.id)}
                  onChange={() => toggleLead(l.id)}
                  className="h-3.5 w-3.5 rounded border-input"
                />
                <span className="flex-1 truncate">
                  <span className="font-mono">{l.email ?? `(${l.id.slice(0, 8)})`}</span>
                  {display && (
                    <span className="ml-2 text-muted-foreground">{display}</span>
                  )}
                  {l.company_name && (
                    <span className="ml-2 text-muted-foreground">· {l.company_name}</span>
                  )}
                </span>
              </label>
            );
          })}
        </div>
        <p className="text-[10px] text-muted-foreground">
          Pulls the first 200 leads from your workspace.
        </p>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit">
          <Send className="mr-1 h-3 w-3" />
          Start sequence
        </Button>
      </DialogFooter>
    </form>
  );
}

function SequenceRow({
  seq,
  expanded,
  onToggle,
  onStop,
  stopping,
  campaignName,
}: {
  seq: SequenceRunOut;
  expanded: boolean;
  onToggle: () => void;
  onStop: () => void;
  stopping: boolean;
  campaignName: string;
}) {
  return (
    <div className="rounded-md border">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-muted/30"
      >
        <div className="flex min-w-0 flex-1 items-center gap-3">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium">{seq.name}</span>
              <Badge variant={STATUS_COLORS[seq.status]}>{seq.status}</Badge>
            </div>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {campaignName}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-right text-xs text-muted-foreground">
          <div>
            <div>{seq.step_count} step{seq.step_count === 1 ? "" : "s"}</div>
            <div>{seq.pending_count} pending</div>
          </div>
          <div>
            <div>{seq.sent_count} sent</div>
            <div>{seq.replied_count} replied</div>
          </div>
          <div>
            <div>{seq.stopped_count} stopped</div>
            <div>Started {formatDate(seq.started_at ?? seq.created_at)}</div>
          </div>
        </div>
      </button>
      {expanded && (
        <div className="border-t bg-muted/20 p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground md:grid-cols-4">
            <div>
              <strong className="text-foreground">Status:</strong> {seq.status}
            </div>
            <div>
              <strong className="text-foreground">Created:</strong> {formatDate(seq.created_at)}
            </div>
            <div>
              <strong className="text-foreground">Started:</strong>{" "}
              {seq.started_at ? formatDate(seq.started_at) : "—"}
            </div>
            <div>
              <strong className="text-foreground">Stopped:</strong>{" "}
              {seq.stopped_at ? formatDate(seq.stopped_at) : "—"}
            </div>
            {seq.stopped_reason && (
              <div className="md:col-span-2">
                <strong className="text-foreground">Stop reason:</strong> {seq.stopped_reason}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            {(seq.status === "running" || seq.status === "paused") && (
              <Button
                size="sm"
                variant="outline"
                onClick={onStop}
                disabled={stopping}
              >
                <Pause className="mr-1 h-3 w-3" />
                {stopping ? "Stopping…" : "Stop sequence"}
              </Button>
            )}
            {seq.status === "stopped" && (
              <span className="text-xs text-muted-foreground">
                This sequence has been stopped and cannot be resumed.
              </span>
            )}
            {seq.status === "completed" && (
              <span className="text-xs text-muted-foreground">
                All leads have been processed.
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function SequencesPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["sequences"],
    queryFn: () => api.listSequences({ limit: 200 }),
  });
  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.listCampaigns(),
  });

  const campaignById = useMemo(() => {
    const map = new Map<string, CampaignOut>();
    (campaigns.data ?? []).forEach((c) => map.set(c.id, c));
    return map;
  }, [campaigns.data]);

  const start = useMutation({
    mutationFn: (input: SequenceRunStartIn) => api.startSequence(input),
    onSuccess: () => {
      toast.success("Sequence started");
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["sequences"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const stop = useMutation({
    mutationFn: (id: string) => api.stopSequence(id),
    onSuccess: () => {
      toast.success("Sequence stopped");
      queryClient.invalidateQueries({ queryKey: ["sequences"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  function confirmStop(seq: SequenceRunOut) {
    if (window.confirm(`Stop sequence "${seq.name}"? Pending sends will be cancelled.`)) {
      stop.mutate(seq.id);
    }
  }

  const items = list.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Sequences</h1>
          <p className="text-muted-foreground">
            Live outreach runs. Each run walks a set of leads through the steps of a campaign,
            sending on the schedule and stopping automatically on reply, bounce, or unsubscribe.
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              New sequence
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>New sequence</DialogTitle>
              <DialogDescription>
                Pick a campaign, choose the leads, and optionally schedule a start time. The
                worker will begin queueing sends at the first step&apos;s send time.
              </DialogDescription>
            </DialogHeader>
            <NewSequenceForm
              onCancel={() => setCreateOpen(false)}
              onSubmit={(values) => start.mutate(values)}
            />
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Play className="h-4 w-4" />
            Your sequences
          </CardTitle>
          <CardDescription>
            {list.isLoading
              ? "Loading…"
              : `${items.length} sequence${items.length === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {list.error && (
            <p className="text-sm text-destructive">
              {(list.error as Error).message}
            </p>
          )}
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No sequences running yet. Start one to begin sending.
            </p>
          )}
          {items.length > 0 && (
            <div className="space-y-2">
              {items.map((s) => (
                <SequenceRow
                  key={s.id}
                  seq={s}
                  expanded={expandedId === s.id}
                  onToggle={() => setExpandedId(expandedId === s.id ? null : s.id)}
                  onStop={() => confirmStop(s)}
                  stopping={stop.isPending}
                  campaignName={campaignById.get(s.campaign_id)?.name ?? "(deleted campaign)"}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
