"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, Search, Users } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { LeadImportDialog } from "@/components/leads/import-dialog";
import { formatDate } from "@/lib/utils";

const SOURCES = [
  { value: "", label: "All sources" },
  { value: "serper", label: "Serper" },
  { value: "company_site", label: "Company site" },
  { value: "linkedin_proxycurl", label: "LinkedIn (Proxycurl)" },
];

export default function LeadsPage() {
  const queryClient = useQueryClient();
  const [source, setSource] = useState<string>("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const list = useQuery({
    queryKey: ["leads", { source, offset }],
    queryFn: () => api.listLeads({ source: source || undefined, limit, offset }),
    refetchInterval: 5_000,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteLead(id),
    onSuccess: () => {
      toast.success("Lead deleted");
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const filtered = q
    ? items.filter(
        (l) =>
          (l.email ?? "").toLowerCase().includes(q.toLowerCase()) ||
          (l.full_name ?? "").toLowerCase().includes(q.toLowerCase()) ||
          (l.company_name ?? "").toLowerCase().includes(q.toLowerCase())
      )
    : items;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Leads</h1>
          <p className="text-muted-foreground">
            Imported from your own list or harvested from your lead sources.
            Deduplicated by email — multiple contacts per company are kept.
          </p>
        </div>
        <LeadImportDialog />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>
            {list.isLoading ? "Loading…" : `${total} total lead${total === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Source</Label>
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={source}
                onChange={(e) => {
                  setSource(e.target.value);
                  setOffset(0);
                }}
              >
                {SOURCES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label>Search (this page)</Label>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-8"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Email, name, or company"
                />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-4 w-4" />
            Results
          </CardTitle>
        </CardHeader>
        <CardContent>
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No leads yet. Create an ICP and launch a scrape from the ICPs page.
            </p>
          )}
          {filtered.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Company</TableHead>
                  <TableHead>Title</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-12 text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((l) => (
                  <TableRow key={l.id}>
                    <TableCell className="font-medium">{l.full_name || l.first_name || "—"}</TableCell>
                    <TableCell className="font-mono text-xs">{l.email ?? "—"}</TableCell>
                    <TableCell>{l.company_name ?? l.domain ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground">{l.title ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {l.source}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(l.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => remove.mutate(l.id)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {total > limit && (
            <div className="mt-4 flex items-center justify-between">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setOffset(Math.max(0, offset - limit))}
                disabled={offset === 0}
              >
                Previous
              </Button>
              <span className="text-xs text-muted-foreground">
                {offset + 1}–{Math.min(offset + limit, total)} of {total}
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setOffset(offset + limit)}
                disabled={offset + limit >= total}
              >
                Next
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
