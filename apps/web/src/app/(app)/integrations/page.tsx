"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, FlaskConical } from "lucide-react";
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

const KIND_OPTIONS = [
  "llm_openai",
  "llm_anthropic",
  "llm_gemini",
  "serper",
  "proxycurl",
  "rapidapi",
  "scrapingbee",
];

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState(KIND_OPTIONS[0]);
  const [label, setLabel] = useState("");
  const [apiKey, setApiKey] = useState("");

  const list = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api.listCredentials(),
  });

  const create = useMutation({
    mutationFn: () =>
      api.createCredential({
        kind,
        label,
        secret_payload: { api_key: apiKey },
      }),
    onSuccess: () => {
      toast.success("Credential added");
      setOpen(false);
      setLabel("");
      setApiKey("");
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteCredential(id),
    onSuccess: () => {
      toast.success("Credential removed");
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const test = useMutation({
    mutationFn: (id: string) => api.testCredential(id),
    onSuccess: (res) => {
      toast[res.ok ? "success" : "error"](res.message);
    },
    onError: (err: Error) => toast.error(err.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
          <p className="text-muted-foreground">
            API keys for LLM providers and scraping services. Stored encrypted with a per-tenant key.
          </p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              Add credential
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add credential</DialogTitle>
              <DialogDescription>
                The secret is encrypted on the way in. You can re-test or delete at any time.
              </DialogDescription>
            </DialogHeader>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate();
              }}
              className="space-y-4"
            >
              <div className="space-y-1.5">
                <Label htmlFor="kind">Kind</Label>
                <select
                  id="kind"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  {KIND_OPTIONS.map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="label">Label</Label>
                <Input
                  id="label"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="e.g. OpenAI prod"
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="api_key">API key</Label>
                <Input
                  id="api_key"
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  required
                />
              </div>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setOpen(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={create.isPending}>
                  {create.isPending ? "Saving…" : "Save"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Configured credentials</CardTitle>
          <CardDescription>
            Secrets never leave the server after creation. Use &ldquo;Test&rdquo; to verify the stored value.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {list.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {list.data && list.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No credentials yet. Add one to enable the campaign engine in Phase 3.
            </p>
          )}
          {list.data && list.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Kind</TableHead>
                  <TableHead>Label</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-32 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.data.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell>
                      <Badge variant="secondary">{c.kind}</Badge>
                    </TableCell>
                    <TableCell>{c.label}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(c.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => test.mutate(c.id)}
                          disabled={test.isPending}
                        >
                          <FlaskConical className="mr-1 h-3 w-3" />
                          Test
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => remove.mutate(c.id)}
                          disabled={remove.isPending}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
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
