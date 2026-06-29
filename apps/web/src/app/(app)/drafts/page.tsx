"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, FileText, RefreshCw, X } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type CampaignOut,
  type DraftOut,
  type DraftStatus,
} from "@/lib/api-client";
import { Button } from "@/components/ui/button";
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
  DraftStatus,
  "default" | "secondary" | "outline" | "destructive"
> = {
  pending: "outline",
  ready: "default",
  approved: "secondary",
  rejected: "destructive",
  failed: "destructive",
};

const STATUSES: Array<{ value: "" | DraftStatus; label: string }> = [
  { value: "", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "ready", label: "Ready" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "failed", label: "Failed" },
];

function DraftPanel({
  draft,
  open,
  onOpenChange,
}: {
  draft: DraftOut | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["draft", draft?.id, { include_body: true }],
    queryFn: () => api.getDraft(draft!.id, { include_body: true }),
    enabled: open && !!draft,
  });

  const setStatus = useMutation({
    mutationFn: (vars: { id: string; status: DraftStatus }) =>
      api.updateDraft(vars.id, { status: vars.status }),
    onSuccess: (_data, vars) => {
      toast.success(`Draft ${vars.status}`);
      queryClient.invalidateQueries({ queryKey: ["drafts"] });
      queryClient.invalidateQueries({ queryKey: ["draft"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const regenerate = useMutation({
    mutationFn: (vars: { lead_id: string; step_id: string }) =>
      api.generateDraft({ lead_id: vars.lead_id, step_id: vars.step_id, force_regenerate: true }),
    onSuccess: () => {
      toast.success("Draft regenerated");
      queryClient.invalidateQueries({ queryKey: ["drafts"] });
      queryClient.invalidateQueries({ queryKey: ["draft"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const current = detail.data ?? draft;
  const body = current?.body ?? current?.body_preview ?? "";
  const canReview = current?.status === "ready" || current?.status === "pending";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            {current?.subject ?? "Draft"}
          </DialogTitle>
          <DialogDescription>
            {current
              ? `Step ${current.step_number} • Status ${current.status} • ${current.model_used ?? "no model"} • Created ${formatDate(current.created_at)}`
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
              {current.model_used && (
                <Badge variant="outline">{current.model_used}</Badge>
              )}
              {current.body_url && (
                <a
                  href={current.body_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground"
                >
                  Open in S3
                  <ExternalLink className="ml-1 h-3 w-3" />
                </a>
              )}
            </div>

            {current.error && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
                <strong>Error:</strong> {current.error}
              </div>
            )}

            <div className="space-y-1.5">
              <Label>Subject</Label>
              <div className="rounded-md border bg-muted/30 p-3 text-sm">
                {current.subject ?? "—"}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Body</Label>
              <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-4 text-sm">
                {body || "—"}
              </pre>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t pt-3">
              <Button
                size="sm"
                onClick={() =>
                  setStatus.mutate({ id: current.id, status: "approved" })
                }
                disabled={!canReview || setStatus.isPending}
              >
                <Check className="mr-1 h-3 w-3" />
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setStatus.mutate({ id: current.id, status: "rejected" })
                }
                disabled={!canReview || setStatus.isPending}
              >
                <X className="mr-1 h-3 w-3" />
                Reject
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  regenerate.mutate({
                    lead_id: current.lead_id,
                    step_id: current.step_id,
                  })
                }
                disabled={regenerate.isPending}
              >
                <RefreshCw className="mr-1 h-3 w-3" />
                {regenerate.isPending ? "Regenerating…" : "Regenerate"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function DraftsPage() {
  const [campaignId, setCampaignId] = useState("");
  const [status, setStatus] = useState<"" | DraftStatus>("");
  const [viewing, setViewing] = useState<DraftOut | null>(null);

  const campaigns = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.listCampaigns(),
  });
  const campaignList: CampaignOut[] = campaigns.data ?? [];

  const list = useQuery({
    queryKey: ["drafts", { campaignId, status }],
    queryFn: () =>
      api.listDrafts({
        campaign_id: campaignId || undefined,
        status: status || undefined,
        limit: 200,
      }),
    refetchInterval: 5_000,
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Drafts</h1>
        <p className="text-muted-foreground">
          AI-generated email drafts queued for review. Approve to release for sending, reject to
          discard, regenerate to re-run the writer agent.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>
            {list.isLoading ? "Loading…" : `${total} draft${total === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Campaign</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={campaignId}
                onChange={(e) => setCampaignId(e.target.value)}
              >
                <option value="">All campaigns</option>
                {campaignList.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label>Status</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={status}
                onChange={(e) => setStatus(e.target.value as "" | DraftStatus)}
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
            <FileText className="h-4 w-4" />
            Queue
          </CardTitle>
        </CardHeader>
        <CardContent>
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No drafts match these filters. Generate drafts from a campaign to populate the queue.
            </p>
          )}
          {items.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Subject</TableHead>
                  <TableHead>Lead</TableHead>
                  <TableHead>Step</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((d) => (
                  <TableRow
                    key={d.id}
                    className="cursor-pointer"
                    onClick={() => setViewing(d)}
                  >
                    <TableCell className="max-w-xs">
                      <div className="truncate font-medium">
                        {d.subject ?? <span className="text-muted-foreground">—</span>}
                      </div>
                      {d.body_preview && (
                        <div className="truncate text-xs text-muted-foreground">
                          {d.body_preview}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {d.lead_id.slice(0, 8)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      Step {d.step_number}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_COLORS[d.status]}>{d.status}</Badge>
                      {d.status === "failed" && d.error && (
                        <p className="mt-1 max-w-xs truncate text-xs text-destructive">
                          {d.error}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      {d.model_used ? (
                        <Badge variant="outline">{d.model_used}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(d.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <DraftPanel
        draft={viewing}
        open={viewing !== null}
        onOpenChange={(o) => !o && setViewing(null)}
      />
    </div>
  );
}
