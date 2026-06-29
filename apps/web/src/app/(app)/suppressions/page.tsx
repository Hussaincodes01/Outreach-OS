"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type SuppressionCreateIn,
  type SuppressionOut,
  type SuppressionReason,
} from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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

const REASON_COLORS: Record<
  SuppressionReason,
  "default" | "secondary" | "outline" | "destructive"
> = {
  unsubscribe: "secondary",
  bounce: "destructive",
  complaint: "destructive",
  manual: "outline",
};

const REASONS: Array<{ value: SuppressionReason; label: string }> = [
  { value: "unsubscribe", label: "Unsubscribe" },
  { value: "bounce", label: "Bounce" },
  { value: "complaint", label: "Complaint" },
  { value: "manual", label: "Manual" },
];

function SuppressionForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (values: SuppressionCreateIn) => void;
  onCancel: () => void;
}) {
  const [email, setEmail] = useState("");
  const [reason, setReason] = useState<SuppressionReason>("manual");
  const [source, setSource] = useState("");
  const [notes, setNotes] = useState("");

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          email: email.trim().toLowerCase(),
          reason,
          source: source.trim() || null,
          notes: notes.trim() || null,
        });
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="sup_email">Email</Label>
        <Input
          id="sup_email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          placeholder="blocked@example.com"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="sup_reason">Reason</Label>
        <select
          id="sup_reason"
          required
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
          value={reason}
          onChange={(e) => setReason(e.target.value as SuppressionReason)}
        >
          {REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="sup_source">Source (optional)</Label>
        <Input
          id="sup_source"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="e.g. reply, manual, list-cleanup"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="sup_notes">Notes (optional)</Label>
        <Textarea
          id="sup_notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="Why is this address being suppressed?"
        />
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit">
          <Ban className="mr-1 h-3 w-3" />
          Suppress
        </Button>
      </DialogFooter>
    </form>
  );
}

export default function SuppressionsPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);

  const list = useQuery({
    queryKey: ["suppressions"],
    queryFn: () => api.listSuppressions({ limit: 200 }),
  });

  const create = useMutation({
    mutationFn: (input: SuppressionCreateIn) => api.addSuppression(input),
    onSuccess: () => {
      toast.success("Suppression added");
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["suppressions"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: (email: string) => api.removeSuppression(email),
    onSuccess: () => {
      toast.success("Suppression removed");
      queryClient.invalidateQueries({ queryKey: ["suppressions"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  function confirmRemove(s: SuppressionOut) {
    if (window.confirm(`Remove suppression for ${s.email}? Future sends will be allowed.`)) {
      remove.mutate(s.email);
    }
  }

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Suppressions</h1>
          <p className="text-muted-foreground">
            Email addresses the sequencer must never mail. Suppressions are checked before every
            send and added automatically on unsubscribe, bounce, or complaint.
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              Add suppression
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add suppression</DialogTitle>
              <DialogDescription>
                Manually block an address. All future sends to this email will be skipped.
              </DialogDescription>
            </DialogHeader>
            <SuppressionForm
              onCancel={() => setCreateOpen(false)}
              onSubmit={(values) => create.mutate(values)}
            />
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Ban className="h-4 w-4" />
            Blocklist
          </CardTitle>
          <CardDescription>
            {list.isLoading ? "Loading…" : `${total} suppressed`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {list.error && (
            <p className="text-sm text-destructive">{(list.error as Error).message}</p>
          )}
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No suppressions yet. Unsubscribe links, bounces, and complaints are added
              automatically as they happen.
            </p>
          )}
          {items.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Notes</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-12 text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-mono text-xs">{s.email}</TableCell>
                    <TableCell>
                      <Badge variant={REASON_COLORS[s.reason]}>{s.reason}</Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {s.source ?? "—"}
                    </TableCell>
                    <TableCell className="max-w-xs truncate text-xs text-muted-foreground">
                      {s.notes ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(s.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => confirmRemove(s)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
