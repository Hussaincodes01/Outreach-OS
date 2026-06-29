"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mail, Plus, Trash2, Send } from "lucide-react";
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

export default function MailboxesPage() {
  const queryClient = useQueryClient();
  const [smtpOpen, setSmtpOpen] = useState(false);
  const [testOpen, setTestOpen] = useState<string | null>(null);

  const [host, setHost] = useState("");
  const [port, setPort] = useState(587);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [useTls, setUseTls] = useState(true);

  const [testTo, setTestTo] = useState("");

  const list = useQuery({
    queryKey: ["mailboxes"],
    queryFn: () => api.listMailboxes(),
  });

  const addSmtp = useMutation({
    mutationFn: () =>
      api.createSmtpMailbox({
        host,
        port,
        username,
        password,
        email_address: email,
        use_tls: useTls,
        daily_send_cap: 50,
      }),
    onSuccess: () => {
      toast.success("SMTP mailbox connected");
      setSmtpOpen(false);
      queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const gmailStart = useMutation({
    mutationFn: () => api.gmailOAuthStart(),
    onSuccess: (res) => {
      window.location.href = res.auth_url;
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const outlookStart = useMutation({
    mutationFn: () => api.outlookOAuthStart(),
    onSuccess: (res) => {
      window.location.href = res.auth_url;
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteMailbox(id),
    onSuccess: () => {
      toast.success("Mailbox disconnected");
      queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const sendTest = useMutation({
    mutationFn: (vars: { id: string; to: string }) =>
      api.sendTest(vars.id, { to: vars.to, subject: "Outreach OS test", body: "Hello from Outreach OS." }),
    onSuccess: (res) => {
      toast[res.ok ? "success" : "error"](res.message);
      setTestOpen(null);
      setTestTo("");
    },
    onError: (err: Error) => toast.error(err.message),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Mailboxes</h1>
          <p className="text-muted-foreground">
            Connect a sending account. OAuth flows use your own mailbox — we never store your password.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => gmailStart.mutate()}
            disabled={gmailStart.isPending}
          >
            <Mail className="mr-2 h-4 w-4" />
            Connect Gmail
          </Button>
          <Button
            variant="outline"
            onClick={() => outlookStart.mutate()}
            disabled={outlookStart.isPending}
          >
            <Mail className="mr-2 h-4 w-4" />
            Connect Outlook
          </Button>
          <Dialog open={smtpOpen} onOpenChange={setSmtpOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" />
                Add SMTP
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add SMTP mailbox</DialogTitle>
                <DialogDescription>
                  Use this for any SMTP server. For MailHog locally, use
                  host <code>localhost</code> and port <code>1025</code>.
                </DialogDescription>
              </DialogHeader>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  addSmtp.mutate();
                }}
                className="space-y-4"
              >
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="host">Host</Label>
                    <Input id="host" value={host} onChange={(e) => setHost(e.target.value)} required />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="port">Port</Label>
                    <Input
                      id="port"
                      type="number"
                      value={port}
                      onChange={(e) => setPort(parseInt(e.target.value, 10))}
                      required
                    />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="smtp_email">Sending address</Label>
                  <Input
                    id="smtp_email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="smtp_user">Username</Label>
                    <Input
                      id="smtp_user"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      required
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="smtp_pass">Password</Label>
                    <Input
                      id="smtp_pass"
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                    />
                  </div>
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={useTls}
                    onChange={(e) => setUseTls(e.target.checked)}
                  />
                  Use STARTTLS
                </label>
                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setSmtpOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" disabled={addSmtp.isPending}>
                    {addSmtp.isPending ? "Connecting…" : "Connect"}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Connected mailboxes</CardTitle>
          <CardDescription>
            MailHog is running on <code>localhost:1025</code> for local dev — view captured mail at
            <code> localhost:8025</code>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {list.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {list.data && list.data.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No mailboxes yet. Connect one to start sending in Phase 4.
            </p>
          )}
          {list.data && list.data.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Provider</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Cap / day</TableHead>
                  <TableHead>Connected</TableHead>
                  <TableHead className="w-40 text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.data.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell>
                      <Badge variant="secondary">{m.provider}</Badge>
                    </TableCell>
                    <TableCell>{m.email_address}</TableCell>
                    <TableCell>{m.daily_send_cap}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(m.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setTestOpen(m.id)}
                        >
                          <Send className="mr-1 h-3 w-3" />
                          Test
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => remove.mutate(m.id)}
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

      <Dialog open={testOpen !== null} onOpenChange={(o) => !o && setTestOpen(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Send test email</DialogTitle>
            <DialogDescription>
              We&apos;ll send a short test message from this mailbox. For MailHog locally, view it at
              <code> localhost:8025</code>.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (testOpen) sendTest.mutate({ id: testOpen, to: testTo });
            }}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label htmlFor="to">Recipient</Label>
              <Input
                id="to"
                type="email"
                value={testTo}
                onChange={(e) => setTestTo(e.target.value)}
                required
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setTestOpen(null)}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={sendTest.isPending}>
                {sendTest.isPending ? "Sending…" : "Send"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
