"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Play, Target, Pencil } from "lucide-react";
import { toast } from "sonner";
import { api, type IcpInput, type IcpOut, type ScrapingJobOut } from "@/lib/api-client";
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
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

const FIELD_LABELS: Record<string, string> = {
  industries: "Industries",
  company_sizes: "Company sizes",
  geos: "Geographies",
  titles: "Job titles",
  signals: "Buying signals",
};

function TagList({
  values,
  onChange,
  placeholder,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");
  function add() {
    const v = draft.trim();
    if (!v) return;
    if (values.includes(v)) return;
    onChange([...values, v]);
    setDraft("");
  }
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {values.length === 0 && (
          <span className="text-xs text-muted-foreground">No values yet.</span>
        )}
        {values.map((v) => (
          <Badge key={v} variant="secondary" className="gap-1">
            {v}
            <button
              type="button"
              className="ml-1 text-muted-foreground hover:text-foreground"
              onClick={() => onChange(values.filter((x) => x !== v))}
              aria-label={`Remove ${v}`}
            >
              &times;
            </button>
          </Badge>
        ))}
      </div>
      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}

function IcpForm({
  initial,
  onSubmit,
  submitLabel,
  onCancel,
}: {
  initial: Partial<IcpInput>;
  onSubmit: (values: IcpInput) => void;
  submitLabel: string;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial.name ?? "");
  const [description, setDescription] = useState(initial.description ?? "");
  const [industries, setIndustries] = useState<string[]>(initial.industries ?? []);
  const [companySizes, setCompanySizes] = useState<string[]>(initial.company_sizes ?? []);
  const [geos, setGeos] = useState<string[]>(initial.geos ?? []);
  const [titles, setTitles] = useState<string[]>(initial.titles ?? []);
  const [signals, setSignals] = useState<string[]>(initial.signals ?? []);
  const [isActive, setIsActive] = useState(initial.is_active ?? true);

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          name,
          description: description || null,
          industries,
          company_sizes: companySizes,
          geos,
          titles,
          signals,
          is_active: isActive,
        });
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="icp_name">Name</Label>
        <Input
          id="icp_name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="e.g. Mid-market SaaS in NA"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="icp_desc">Description</Label>
        <Textarea
          id="icp_desc"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          placeholder="Optional — what makes a great-fit lead for this ICP?"
        />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {(
          [
            ["industries", industries, setIndustries, "SaaS, Fintech, eCommerce"],
            ["company_sizes", companySizes, setCompanySizes, "11-50, 51-200"],
            ["geos", geos, setGeos, "US, CA, UK"],
            ["titles", titles, setTitles, "VP Sales, Head of Marketing"],
            ["signals", signals, setSignals, "hiring SDRs, raised Series A"],
          ] as const
        ).map(([key, values, setValues, placeholder]) => (
          <div key={key} className="space-y-1.5">
            <Label>{FIELD_LABELS[key]}</Label>
            <TagList
              values={values}
              onChange={setValues}
              placeholder={`Add ${FIELD_LABELS[key].toLowerCase()}…`}
              {...{}}
            />
            <input type="hidden" name={key} />
            <span className="text-[10px] text-muted-foreground">{placeholder}</span>
          </div>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isActive}
          onChange={(e) => setIsActive(e.target.checked)}
        />
        Active
      </label>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit">{submitLabel}</Button>
      </DialogFooter>
    </form>
  );
}

export default function IcpsPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<IcpOut | null>(null);
  const [scrapeOpen, setScrapeOpen] = useState<IcpOut | null>(null);
  const [scrapeCount, setScrapeCount] = useState(25);

  const list = useQuery({
    queryKey: ["icps"],
    queryFn: () => api.listIcps(),
  });

  const create = useMutation({
    mutationFn: (values: IcpInput) => api.createIcp(values),
    onSuccess: () => {
      toast.success("ICP created");
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["icps"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const update = useMutation({
    mutationFn: (vars: { id: string; values: IcpInput }) =>
      api.updateIcp(vars.id, vars.values),
    onSuccess: () => {
      toast.success("ICP updated");
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ["icps"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteIcp(id),
    onSuccess: () => {
      toast.success("ICP deleted");
      queryClient.invalidateQueries({ queryKey: ["icps"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const scrape = useMutation({
    mutationFn: (vars: { id: string; count: number }) =>
      api.launchScrape(vars.id, { sources: ["serper", "company_site", "linkedin_proxycurl"], requested_count: vars.count }),
    onSuccess: (job: ScrapingJobOut) => {
      toast.success(`Scrape job ${job.id.slice(0, 8)} queued`);
      setScrapeOpen(null);
      queryClient.invalidateQueries({ queryKey: ["scraping-jobs"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ideal Customer Profiles</h1>
          <p className="text-muted-foreground">
            Define the companies and people you want to reach. ICPs drive lead generation in Phase 2.
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              New ICP
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>New ICP</DialogTitle>
              <DialogDescription>
                Describe the kind of companies and contacts you want Outreach OS to find.
              </DialogDescription>
            </DialogHeader>
            <IcpForm
              initial={{}}
              submitLabel="Create"
              onCancel={() => setCreateOpen(false)}
              onSubmit={(values) => create.mutate(values)}
            />
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Your ICPs</CardTitle>
          <CardDescription>
            Enable a lead source on the <strong>Lead Sources</strong> page before launching a scrape.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {list.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {list.data && list.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No ICPs yet. Create one to start finding leads.
            </p>
          )}
          {list.data && list.data.length > 0 && (
            <div className="space-y-3">
              {list.data.map((icp) => (
                <div
                  key={icp.id}
                  className="flex items-start justify-between gap-4 rounded-md border p-4"
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <Target className="h-4 w-4 text-muted-foreground" />
                      <span className="font-medium">{icp.name}</span>
                      {!icp.is_active && (
                        <Badge variant="outline" className="text-xs">
                          inactive
                        </Badge>
                      )}
                    </div>
                    {icp.description && (
                      <p className="text-sm text-muted-foreground">{icp.description}</p>
                    )}
                    <div className="flex flex-wrap gap-1.5 text-xs">
                      {icp.industries.slice(0, 3).map((v) => (
                        <Badge key={v} variant="secondary">
                          {v}
                        </Badge>
                      ))}
                      {icp.titles.slice(0, 2).map((v) => (
                        <Badge key={v} variant="outline">
                          {v}
                        </Badge>
                      ))}
                      {icp.company_sizes.length > 0 && (
                        <span className="text-muted-foreground">
                          {icp.company_sizes.length} size{icp.company_sizes.length === 1 ? "" : "s"}
                        </span>
                      )}
                      {icp.geos.length > 0 && (
                        <span className="text-muted-foreground">
                          {icp.geos.length} geo{icp.geos.length === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Updated {formatDate(icp.updated_at)}
                    </p>
                  </div>
                  <div className="flex flex-col gap-2">
                    <Button size="sm" onClick={() => setScrapeOpen(icp)}>
                      <Play className="mr-1 h-3 w-3" />
                      Scrape
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditing(icp)}>
                      <Pencil className="mr-1 h-3 w-3" />
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => remove.mutate(icp.id)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit ICP</DialogTitle>
            <DialogDescription>Update the targeting criteria for this ICP.</DialogDescription>
          </DialogHeader>
          {editing && (
            <IcpForm
              initial={editing}
              submitLabel="Save"
              onCancel={() => setEditing(null)}
              onSubmit={(values) => update.mutate({ id: editing.id, values })}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={scrapeOpen !== null} onOpenChange={(o) => !o && setScrapeOpen(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Launch scrape</DialogTitle>
            <DialogDescription>
              This will run all enabled lead sources against this ICP and store results in your
              leads pool. Deduplication is per-email.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (scrapeOpen) scrape.mutate({ id: scrapeOpen.id, count: scrapeCount });
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="count">Requested count</Label>
              <Input
                id="count"
                type="number"
                min={1}
                max={500}
                value={scrapeCount}
                onChange={(e) => setScrapeCount(parseInt(e.target.value, 10) || 25)}
                required
              />
              <p className="text-xs text-muted-foreground">
                1 to 500. Sources stop early once they hit their per-tenant rate limit.
              </p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setScrapeOpen(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={scrape.isPending}>
                {scrape.isPending ? "Launching…" : "Launch"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
