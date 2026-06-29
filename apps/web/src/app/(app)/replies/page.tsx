"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Inbox } from "lucide-react";
import { api, type ReplyClassification, type ReplyOut } from "@/lib/api-client";
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

const CLASSIFICATION_COLORS: Record<
  ReplyClassification,
  "default" | "secondary" | "outline" | "destructive"
> = {
  positive: "default",
  negative: "destructive",
  ooo: "secondary",
  question: "outline",
  unsubscribe: "destructive",
  bounce: "destructive",
  other: "outline",
};

const CLASSIFICATIONS: Array<{ value: "" | ReplyClassification; label: string }> = [
  { value: "", label: "All" },
  { value: "positive", label: "Positive" },
  { value: "negative", label: "Negative" },
  { value: "ooo", label: "Out of office" },
  { value: "question", label: "Question" },
  { value: "unsubscribe", label: "Unsubscribe" },
  { value: "bounce", label: "Bounce" },
  { value: "other", label: "Other" },
];

function ReplyPanel({
  reply,
  open,
  onOpenChange,
}: {
  reply: ReplyOut | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Inbox className="h-4 w-4" />
            {reply?.subject ?? "Reply"}
          </DialogTitle>
          <DialogDescription>
            {reply
              ? `From: ${reply.from_name ?? reply.from_email} <${reply.from_email}> • Received ${formatDate(reply.received_at)}`
              : "Loading…"}
          </DialogDescription>
        </DialogHeader>

        {reply && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={CLASSIFICATION_COLORS[reply.classification]}>
                {reply.classification}
              </Badge>
              {typeof reply.classification_confidence === "number" && (
                <Badge variant="outline">
                  {Math.round(reply.classification_confidence * 100)}% confidence
                </Badge>
              )}
              {reply.classified_at && (
                <Badge variant="outline">
                  classified {formatDate(reply.classified_at)}
                </Badge>
              )}
            </div>

            <div className="space-y-1.5">
              <Label>Send ID</Label>
              <div className="break-all rounded-md border bg-muted/30 p-3 font-mono text-xs">
                {reply.send_id}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Subject</Label>
              <div className="rounded-md border bg-muted/30 p-3 text-sm">
                {reply.subject ?? "—"}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label>Body</Label>
              <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-4 text-sm">
                {reply.body_text ?? "—"}
              </pre>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function RepliesPage() {
  const [classification, setClassification] = useState<"" | ReplyClassification>("");
  const [viewing, setViewing] = useState<ReplyOut | null>(null);

  const list = useQuery({
    queryKey: ["replies", { classification }],
    queryFn: () =>
      api.listReplies({
        classification: classification || undefined,
        limit: 200,
      }),
    refetchInterval: 10_000,
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Replies</h1>
        <p className="text-muted-foreground">
          Inbound responses to your sends, classified by the reply agent. Filter by
          classification to triage positives, OOO auto-responders, and unsubscribes.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>
            {list.isLoading ? "Loading…" : `${total} repl${total === 1 ? "y" : "ies"}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Classification</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={classification}
                onChange={(e) => setClassification(e.target.value as "" | ReplyClassification)}
              >
                {CLASSIFICATIONS.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
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
            <Inbox className="h-4 w-4" />
            Queue
          </CardTitle>
        </CardHeader>
        <CardContent>
          {list.error && (
            <p className="text-sm text-destructive">{(list.error as Error).message}</p>
          )}
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No replies match this filter. Once leads respond they will appear here.
            </p>
          )}
          {items.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>From</TableHead>
                  <TableHead>Subject</TableHead>
                  <TableHead>Classification</TableHead>
                  <TableHead>Received</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((r) => (
                  <TableRow
                    key={r.id}
                    className="cursor-pointer"
                    onClick={() => setViewing(r)}
                  >
                    <TableCell>
                      <div className="font-medium">
                        {r.from_name ?? r.from_email}
                      </div>
                      {r.from_name && (
                        <div className="font-mono text-xs text-muted-foreground">
                          {r.from_email}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="max-w-md">
                      <div className="truncate">
                        {r.subject ?? <span className="text-muted-foreground">—</span>}
                      </div>
                      {r.body_text && (
                        <div className="truncate text-xs text-muted-foreground">
                          {r.body_text}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col items-start gap-1">
                        <Badge variant={CLASSIFICATION_COLORS[r.classification]}>
                          {r.classification}
                        </Badge>
                        {typeof r.classification_confidence === "number" && (
                          <span className="text-[10px] text-muted-foreground">
                            {Math.round(r.classification_confidence * 100)}%
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(r.received_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ReplyPanel
        reply={viewing}
        open={viewing !== null}
        onOpenChange={(o) => !o && setViewing(null)}
      />
    </div>
  );
}
