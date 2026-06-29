"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Filter } from "lucide-react";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [limit] = useState(100);

  const audit = useQuery({
    queryKey: ["audit", { action, limit }],
    queryFn: () => api.listAudit({ action: action || undefined, limit }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
          <p className="text-muted-foreground">
            Every state-changing action in your workspace. Hash-chained and append-only.
          </p>
        </div>
        <Button asChild variant="outline">
          <a href={api.auditCsvUrl()} target="_blank" rel="noreferrer">
            <Download className="mr-2 h-4 w-4" />
            Export CSV
          </a>
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Events</CardTitle>
          <CardDescription>Most recent first.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Filter by action (e.g. credential.created)"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="max-w-sm"
            />
          </div>
          {audit.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {audit.data && audit.data.items.length === 0 && (
            <p className="text-sm text-muted-foreground">No events yet.</p>
          )}
          {audit.data && audit.data.items.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Target</TableHead>
                  <TableHead>Payload</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {audit.data.items.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="text-muted-foreground">
                      {formatDate(e.created_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{e.actor_kind}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{e.action}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {e.target_type ? `${e.target_type}:${(e.target_id ?? "").slice(0, 8)}` : "—"}
                    </TableCell>
                    <TableCell className="max-w-xs truncate font-mono text-xs text-muted-foreground">
                      {JSON.stringify(e.payload)}
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
