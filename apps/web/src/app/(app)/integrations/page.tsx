"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, FlaskConical } from "lucide-react";
import { toast } from "sonner";
import { api, type ProviderOut, type ScrapingKeyOut } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/** Coarse relative-time label for "Verified …". Nothing in the codebase has
 *  a shared formatter for this yet, so this stays local and small. */
function relativeTime(value: string): string {
  const then = new Date(value).getTime();
  const diffMs = Date.now() - then;
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin} minute${diffMin === 1 ? "" : "s"} ago`;
  const diffHour = Math.round(diffMin / 60);
  if (diffHour < 24) return `${diffHour} hour${diffHour === 1 ? "" : "s"} ago`;
  const diffDay = Math.round(diffHour / 24);
  if (diffDay < 30) return `${diffDay} day${diffDay === 1 ? "" : "s"} ago`;
  const diffMonth = Math.round(diffDay / 30);
  if (diffMonth < 12) return `${diffMonth} month${diffMonth === 1 ? "" : "s"} ago`;
  const diffYear = Math.round(diffMonth / 12);
  return `${diffYear} year${diffYear === 1 ? "" : "s"} ago`;
}

export default function IntegrationsPage() {
  const queryClient = useQueryClient();

  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.listProviders(),
  });
  const scraping = useQuery({
    queryKey: ["scraping-keys"],
    queryFn: () => api.scrapingKeys(),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["providers"] });
    queryClient.invalidateQueries({ queryKey: ["onboarding"] });
  };

  const test = useMutation({
    mutationFn: (provider: string) => api.testProvider(provider),
    onSuccess: (r) => {
      if (r.ok) toast.success(r.message);
      else toast.error(r.message);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
        <p className="text-sm text-muted-foreground">
          Every key lives in <code>.env</code> on the server — nothing is
          entered or stored through the app. Set the variables below, then
          restart the stack for them to take effect.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">AI providers</CardTitle>
          <CardDescription>
            Connect at least one to generate drafts. Choose which model to use
            in{" "}
            <a href="/settings" className="underline">
              Settings
            </a>
            .
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {providers.isLoading && (
            <p className="text-sm text-muted-foreground">Loading providers…</p>
          )}
          {providers.isError && (
            <p className="text-sm text-destructive">
              Couldn&apos;t load providers.
            </p>
          )}
          {providers.data?.map((p) => (
            <ProviderRow
              key={p.provider}
              provider={p}
              onTest={() => test.mutate(p.provider)}
              testPending={test.isPending && test.variables === p.provider}
            />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Lead data sources</CardTitle>
          <CardDescription>
            Optional. Without these, lead discovery and the agent&apos;s
            web-search tool are unavailable.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {scraping.isLoading && (
            <p className="text-sm text-muted-foreground">Loading…</p>
          )}
          {scraping.isError && (
            <p className="text-sm text-destructive">
              Couldn&apos;t load lead data sources.
            </p>
          )}
          {scraping.data?.map((s) => (
            <ScrapingRow key={s.kind} item={s} />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function ProviderRow({
  provider,
  onTest,
  testPending,
}: {
  provider: ProviderOut;
  onTest: () => void;
  testPending: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border px-3 py-2">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{provider.label}</span>
          <Badge
            variant={provider.connected ? "default" : "secondary"}
            className="gap-1"
          >
            {provider.connected && (
              <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
            )}
            {provider.connected ? "Configured" : "Not configured"}
          </Badge>
          {provider.supports_embeddings && (
            <Badge variant="outline" className="text-xs">
              embeddings
            </Badge>
          )}
          {provider.requires_api_key === false && (
            <Badge variant="outline" className="text-xs">
              no key needed
            </Badge>
          )}
          <span className="text-xs text-muted-foreground">
            {provider.model_count} models
          </span>
        </div>
        {provider.description && (
          <p className="text-xs text-muted-foreground">{provider.description}</p>
        )}
        <p className="text-xs text-muted-foreground">
          Set <code>{provider.env_var}</code>
          {provider.requires_api_base && (
            <>
              {" "}
              and <code>{provider.env_base_var}</code>
            </>
          )}{" "}
          in <code>.env</code>, then restart the stack.
        </p>
        {provider.last_verified_at && (
          <p className="text-xs text-muted-foreground">
            Verified {relativeTime(provider.last_verified_at)}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <a
          href={provider.console_url}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1 text-xs text-muted-foreground underline"
        >
          Get a key
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </a>
        <Button
          size="sm"
          variant="outline"
          onClick={onTest}
          disabled={!provider.connected || testPending}
          title="Make a live call to the provider"
        >
          <FlaskConical className="mr-1 h-3 w-3" aria-hidden="true" />
          {testPending ? "Testing…" : "Test"}
        </Button>
      </div>
    </div>
  );
}

function ScrapingRow({ item }: { item: ScrapingKeyOut }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border px-3 py-2">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{item.kind}</span>
          <Badge variant={item.configured ? "default" : "secondary"} className="gap-1">
            {item.configured && <CheckCircle2 className="h-3 w-3" aria-hidden="true" />}
            {item.configured ? "Configured" : "Not configured"}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Set <code>{item.env_var}</code> in <code>.env</code>, then restart the
          stack.
        </p>
      </div>
    </div>
  );
}
