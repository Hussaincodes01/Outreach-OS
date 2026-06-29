"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type ProxyInput } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

const PROTOCOLS: Array<{ value: "http" | "https" | "socks5"; label: string }> = [
  { value: "http", label: "HTTP" },
  { value: "https", label: "HTTPS" },
  { value: "socks5", label: "SOCKS5" },
];

export default function ProxiesPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [protocol, setProtocol] = useState<"http" | "https" | "socks5">("http");
  const [host, setHost] = useState("");
  const [port, setPort] = useState(8080);
  const [url, setUrl] = useState("");

  const list = useQuery({
    queryKey: ["proxies"],
    queryFn: () => api.listProxies(),
  });

  const create = useMutation({
    mutationFn: (input: ProxyInput) => api.createProxy(input),
    onSuccess: () => {
      toast.success("Proxy added");
      setCreateOpen(false);
      setLabel("");
      setHost("");
      setPort(8080);
      setUrl("");
      queryClient.invalidateQueries({ queryKey: ["proxies"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteProxy(id),
    onSuccess: () => {
      toast.success("Proxy removed");
      queryClient.invalidateQueries({ queryKey: ["proxies"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Proxies</h1>
          <p className="text-muted-foreground">
            Optional outbound proxies used by the company-site crawler. URLs are encrypted with your
            tenant&apos;s DEK before storage.
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              Add proxy
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add proxy</DialogTitle>
              <DialogDescription>
                Use a full URL if your proxy needs authentication:{" "}
                <code>http://user:pass@host:port</code>.
              </DialogDescription>
            </DialogHeader>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate({
                  label,
                  protocol,
                  host,
                  port,
                  url: url || null,
                });
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="proxy_label">Label</Label>
                <Input
                  id="proxy_label"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  required
                  placeholder="e.g. US-residential-A"
                />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1.5">
                  <Label>Protocol</Label>
                  <select
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                    value={protocol}
                    onChange={(e) => setProtocol(e.target.value as "http" | "https" | "socks5")}
                  >
                    {PROTOCOLS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5 col-span-2">
                  <Label htmlFor="proxy_host">Host</Label>
                  <Input
                    id="proxy_host"
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    required
                    placeholder="proxy.example.com"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="proxy_port">Port</Label>
                <Input
                  id="proxy_port"
                  type="number"
                  min={1}
                  max={65535}
                  value={port}
                  onChange={(e) => setPort(parseInt(e.target.value, 10) || 8080)}
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="proxy_url">Full URL (optional)</Label>
                <Input
                  id="proxy_url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="http://user:pass@proxy.example.com:8080"
                />
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setCreateOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={create.isPending}>
                  {create.isPending ? "Adding…" : "Add proxy"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Configured proxies</CardTitle>
          <CardDescription>
            Stored encrypted per-tenant. The worker decrypts URLs on demand.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {list.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {list.data && list.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No proxies configured. The crawler will use your direct outbound connection.
            </p>
          )}
          {list.data && list.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Label</TableHead>
                  <TableHead>Protocol</TableHead>
                  <TableHead>Host</TableHead>
                  <TableHead>Port</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-12 text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.data.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">
                      <Globe className="mr-2 inline h-3 w-3 text-muted-foreground" />
                      {p.label}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{p.protocol}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{p.host}</TableCell>
                    <TableCell>{p.port}</TableCell>
                    <TableCell>
                      <Badge variant={p.is_active ? "default" : "secondary"}>
                        {p.is_active ? "active" : "inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => remove.mutate(p.id)}>
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
