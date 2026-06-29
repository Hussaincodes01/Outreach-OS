"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { api, type ScrapingJobStatus } from "@/lib/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

const STATUS_COLORS: Record<ScrapingJobStatus, "default" | "secondary" | "outline" | "destructive"> = {
  pending: "outline",
  running: "default",
  completed: "secondary",
  failed: "destructive",
};

const STATUSES: Array<{ value: "" | ScrapingJobStatus; label: string }> = [
  { value: "", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

export default function ScrapingJobsPage() {
  const [status, setStatus] = useState<"" | ScrapingJobStatus>("");
  const list = useQuery({
    queryKey: ["scraping-jobs", { status }],
    queryFn: () => api.listScrapingJobs({ status: status || undefined, limit: 100 }),
    refetchInterval: 3_000,
  });

  const items = list.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Scraping jobs</h1>
        <p className="text-muted-foreground">
          Every scrape you launch runs as a job. Open the Lead Sources page to enable sources, then
          launch from the ICPs page.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Status</CardTitle>
          <CardDescription>
            {list.isLoading ? "Loading…" : `${list.data?.total ?? 0} job${(list.data?.total ?? 0) === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex flex-wrap gap-1.5">
            {STATUSES.map((s) => (
              <button
                key={s.value}
                onClick={() => setStatus(s.value)}
                className={
                  "rounded-md border px-3 py-1 text-xs font-medium " +
                  (status === s.value
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-input bg-background text-muted-foreground hover:text-foreground")
                }
              >
                {s.label}
              </button>
            ))}
          </div>

          {items.length === 0 && !list.isLoading && (
            <p className="text-sm text-muted-foreground">No jobs match this filter.</p>
          )}

          {items.length > 0 && (
            <div className="space-y-2">
              {items.map((j) => (
                <div key={j.id} className="flex items-center justify-between gap-3 rounded-md border p-3">
                  <div className="flex items-start gap-3">
                    <History className="mt-0.5 h-4 w-4 text-muted-foreground" />
                    <div>
                      <div className="flex items-center gap-2">
                        <code className="text-xs text-muted-foreground">{j.id.slice(0, 8)}</code>
                        <Badge variant={STATUS_COLORS[j.status]}>
                          {j.status}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          ICP <code>{j.icp_id.slice(0, 8)}</code>
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Sources: {j.sources.join(", ")} • Requested {j.requested_count} • Found{" "}
                        {j.found_count}
                      </p>
                      {j.error && (
                        <p className="mt-1 text-xs text-destructive">{j.error}</p>
                      )}
                    </div>
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {j.completed_at ? (
                      <p>Completed {formatDate(j.completed_at)}</p>
                    ) : j.started_at ? (
                      <p>Started {formatDate(j.started_at)}</p>
                    ) : (
                      <p>Created {formatDate(j.created_at)}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
