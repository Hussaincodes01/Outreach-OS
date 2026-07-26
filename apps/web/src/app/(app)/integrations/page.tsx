"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ExternalLink,
  FlaskConical,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { api, type ProviderOut } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

/** Non-LLM integrations. The LLM providers come from the API so the list
 *  cannot drift from what the backend actually supports. */
const OTHER_KINDS = [
  { kind: "serper", label: "Serper (web search)", console: "https://serper.dev/api-key" },
  { kind: "proxycurl", label: "Proxycurl (LinkedIn)", console: "https://nubela.co/proxycurl" },
  { kind: "rapidapi", label: "RapidAPI", console: "https://rapidapi.com/developer" },
  { kind: "scrapingbee", label: "ScrapingBee", console: "https://app.scrapingbee.com/account" },
];

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const [dialogKind, setDialogKind] = useState<string | null>(null);
  const [dialogLabel, setDialogLabel] = useState("");
  const [apiKey, setApiKey] = useState("");

  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.listProviders(),
  });
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api.listCredentials(),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["credentials"] });
    queryClient.invalidateQueries({ queryKey: ["providers"] });
    queryClient.invalidateQueries({ queryKey: ["onboarding"] });
  };

  const create = useMutation({
    mutationFn: () =>
      api.createCredential({
        kind: dialogKind!,
        label: dialogLabel.trim() || dialogKind!,
        secret_payload: { api_key: apiKey.trim() },
      }),
    onSuccess: () => {
      toast.success("Key saved and encrypted");
      setDialogKind(null);
      setDialogLabel("");
      setApiKey("");
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteCredential(id),
    onSuccess: () => {
      toast.success("Key removed");
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const test = useMutation({
    mutationFn: (id: string) => api.testCredential(id),
    onSuccess: (r) => {
      if (r.ok) toast.success(r.message);
      else toast.error(r.message);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const openDialog = (kind: string, label: string) => {
    setDialogKind(kind);
    setDialogLabel(label);
    setApiKey("");
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
        <p className="text-sm text-muted-foreground">
          Bring your own keys. Everything is encrypted with a key unique to your
          workspace, and AI usage is billed to your own provider account — we
          never proxy through a shared key.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            AI providers
          </CardTitle>
          <CardDescription>
            Connect at least one to generate drafts. Choose which model to use in{" "}
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
          {providers.data?.map((p) => (
            <ProviderRow key={p.provider} provider={p} onConnect={openDialog} />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Lead data providers</CardTitle>
          <CardDescription>
            Optional. Without these, lead discovery and the agent&apos;s web-search
            tool are unavailable.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {OTHER_KINDS.map((o) => {
            const connected = credentials.data?.some((c) => c.kind === o.kind);
            return (
              <div
                key={o.kind}
                className="flex items-center justify-between rounded-md border px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{o.label}</span>
                  {connected && (
                    <Badge variant="secondary" className="gap-1">
                      <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
                      Connected
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={o.console}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-muted-foreground underline"
                  >
                    Get a key
                  </a>
                  <Button
                    size="sm"
                    variant={connected ? "outline" : "default"}
                    onClick={() => openDialog(o.kind, o.label)}
                  >
                    <Plus className="mr-1 h-3 w-3" aria-hidden="true" />
                    {connected ? "Replace" : "Connect"}
                  </Button>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Stored keys</CardTitle>
          <CardDescription>
            Secrets are never returned by the API — not even to you. Replace a key
            by connecting a new one.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Label</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Added</TableHead>
                <TableHead>Verified</TableHead>
                <TableHead className="w-[140px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {credentials.data?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-sm text-muted-foreground">
                    No keys stored yet.
                  </TableCell>
                </TableRow>
              )}
              {credentials.data?.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">{c.label}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{c.kind}</Badge>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDate(c.created_at)}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {c.last_verified_at ? formatDate(c.last_verified_at) : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => test.mutate(c.id)}
                      disabled={test.isPending}
                      title="Make a live call to the provider"
                    >
                      <FlaskConical className="h-4 w-4" aria-hidden="true" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => remove.mutate(c.id)}
                      disabled={remove.isPending}
                    >
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={dialogKind !== null} onOpenChange={(o) => !o && setDialogKind(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Connect {dialogLabel}</DialogTitle>
            <DialogDescription>
              Pasted keys are encrypted immediately with your workspace key. They
              are never written to logs and never returned by the API.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="cred-label">Label</Label>
              <Input
                id="cred-label"
                value={dialogLabel}
                onChange={(e) => setDialogLabel(e.target.value)}
                placeholder="e.g. Production key"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="cred-key">API key</Label>
              <Input
                id="cred-key"
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-…"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogKind(null)}>
              Cancel
            </Button>
            <Button
              onClick={() => create.mutate()}
              disabled={!apiKey.trim() || create.isPending}
            >
              {create.isPending ? "Saving…" : "Save key"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProviderRow({
  provider,
  onConnect,
}: {
  provider: ProviderOut;
  onConnect: (kind: string, label: string) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-md border px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{provider.label}</span>
        {provider.connected ? (
          <Badge variant={provider.last_verified_at ? "default" : "secondary"} className="gap-1">
            <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
            {provider.last_verified_at ? "Verified" : "Connected"}
          </Badge>
        ) : null}
        {provider.supports_embeddings && (
          <Badge variant="outline" className="text-xs">
            supports embeddings
          </Badge>
        )}
      </div>
      <div className="flex items-center gap-2">
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
          variant={provider.connected ? "outline" : "default"}
          onClick={() => onConnect(provider.credential_kind, provider.label)}
        >
          <Plus className="mr-1 h-3 w-3" aria-hidden="true" />
          {provider.connected ? "Replace" : "Connect"}
        </Button>
      </div>
    </div>
  );
}
