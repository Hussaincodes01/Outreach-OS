"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { api, type LeadSourceOut } from "@/lib/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/utils";

const SOURCE_META: Record<string, { name: string; desc: string; needs: string; url: string }> = {
  serper: {
    name: "Serper (Google Search)",
    desc: "Searches Google for people matching your ICP. Returns names, titles, companies, and sometimes emails.",
    needs: "Serper API key (add via Integrations)",
    url: "https://serper.dev",
  },
  company_site: {
    name: "Company site crawl",
    desc: "Visits each target company's site (homepage, /team, /about, /contact) and extracts emails that match the domain.",
    needs: "No credentials — uses your outbound HTTP",
    url: "",
  },
  linkedin_proxycurl: {
    name: "LinkedIn (via Proxycurl)",
    desc: "Enriches leads with LinkedIn profile data (title, company, location). Requires a Proxycurl API key.",
    needs: "Proxycurl API key (add via Integrations)",
    url: "https://nubela.co/proxycurl",
  },
};

export default function LeadSourcesPage() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["lead-sources"],
    queryFn: () => api.listLeadSources(),
  });

  const toggle = useMutation({
    mutationFn: (vars: { source: string; enabled: boolean }) =>
      api.updateLeadSource(vars.source, { is_enabled: vars.enabled }),
    onSuccess: (_data, vars) => {
      toast.success(`${vars.source} ${vars.enabled ? "enabled" : "disabled"}`);
      queryClient.invalidateQueries({ queryKey: ["lead-sources"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const sources: LeadSourceOut[] = list.data ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Lead sources</h1>
        <p className="text-muted-foreground">
          Each tenant keeps its own on/off switch per source. When you launch a scrape, only enabled
          sources are queried.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {list.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {sources.map((s) => {
          const meta = SOURCE_META[s.source];
          return (
            <Card key={s.id}>
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <CardTitle className="text-base">
                      <Database className="mr-2 inline h-4 w-4" />
                      {meta?.name ?? s.source}
                    </CardTitle>
                    <CardDescription className="mt-1">{meta?.desc}</CardDescription>
                  </div>
                  <Badge variant={s.is_enabled ? "default" : "secondary"}>
                    {s.is_enabled ? "On" : "Off"}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-muted-foreground">
                  <strong>Requires:</strong> {meta?.needs}
                </p>
                {s.last_run_at && (
                  <p className="text-xs text-muted-foreground">
                    Last run: {formatDate(s.last_run_at)}
                  </p>
                )}
                {meta?.url && (
                  <a
                    href={meta.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center text-xs text-muted-foreground hover:text-foreground"
                  >
                    Get API key
                    <ExternalLink className="ml-1 h-3 w-3" />
                  </a>
                )}
                <Button
                  variant={s.is_enabled ? "outline" : "default"}
                  className="w-full"
                  onClick={() =>
                    toggle.mutate({ source: s.source, enabled: !s.is_enabled })
                  }
                  disabled={toggle.isPending}
                >
                  {s.is_enabled ? "Disable" : "Enable"}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
