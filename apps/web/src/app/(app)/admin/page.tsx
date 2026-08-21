"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Ban, CheckCircle2, Search, Users } from "lucide-react";
import { api, type AdminCustomerOut } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { formatDate } from "@/lib/utils";

const money = (cents: number) =>
  `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="text-2xl font-semibold tracking-tight">{value}</p>
        {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

/**
 * Operator console: every customer workspace, their plan and their usage.
 *
 * Reachable only by platform staff — the API returns 404 (not 403) to anyone
 * else, so its existence isn't advertised to a probing tenant owner.
 */
export default function AdminPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");

  const stats = useQuery({ queryKey: ["admin-stats"], queryFn: () => api.adminStats() });
  const customers = useQuery({
    queryKey: ["admin-customers", query],
    queryFn: () => api.adminCustomers({ q: query || undefined }),
  });

  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.adminSetCustomerStatus(id, status),
    onSuccess: (c) => {
      toast.success(`${c.name} is now ${c.status}`);
      queryClient.invalidateQueries({ queryKey: ["admin-customers"] });
      queryClient.invalidateQueries({ queryKey: ["admin-stats"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const rows = customers.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
        <p className="text-muted-foreground">
          Every customer workspace, their subscription and their usage this month.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat
          label="Customers"
          value={stats.data ? String(stats.data.total_customers) : "—"}
          hint={stats.data ? `${stats.data.signups_last_30d} new in 30 days` : undefined}
        />
        <Stat
          label="Paying"
          value={stats.data ? String(stats.data.paying_customers) : "—"}
          hint={stats.data ? `${stats.data.active_customers} active workspaces` : undefined}
        />
        <Stat
          label="MRR"
          value={stats.data ? money(stats.data.mrr_cents) : "—"}
          hint="List price of live subscriptions"
        />
        <Stat
          label="Sends this month"
          value={stats.data ? stats.data.total_sends_this_month.toLocaleString() : "—"}
          hint={stats.data ? `${stats.data.suspended_customers} suspended` : undefined}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-4 w-4" aria-hidden="true" /> Customers
          </CardTitle>
          <CardDescription>
            {customers.isLoading
              ? "Loading…"
              : `${customers.data?.total ?? 0} workspace${
                  customers.data?.total === 1 ? "" : "s"
                }`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setQuery(search.trim());
            }}
          >
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or slug"
            />
            <Button type="submit" variant="outline" size="icon" aria-label="Search">
              <Search className="h-4 w-4" aria-hidden="true" />
            </Button>
          </form>

          {rows.length === 0 && !customers.isLoading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No customers match.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b text-left text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-3 font-medium">Workspace</th>
                    <th className="py-2 pr-3 font-medium">Plan</th>
                    <th className="py-2 pr-3 font-medium">Subscription</th>
                    <th className="py-2 pr-3 text-right font-medium">Users</th>
                    <th className="py-2 pr-3 text-right font-medium">Leads</th>
                    <th className="py-2 pr-3 text-right font-medium">Sends</th>
                    <th className="py-2 pr-3 font-medium">Joined</th>
                    <th className="py-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c: AdminCustomerOut) => {
                    const suspended = c.status === "suspended";
                    return (
                      <tr key={c.tenant_id} className="border-b last:border-0">
                        <td className="py-2 pr-3">
                          <div className="font-medium">{c.name}</div>
                          <div className="text-xs text-muted-foreground">{c.slug}</div>
                        </td>
                        <td className="py-2 pr-3">
                          <Badge variant="outline">{c.plan}</Badge>
                        </td>
                        <td className="py-2 pr-3">
                          {c.subscription_status ? (
                            <div className="flex flex-col gap-0.5">
                              <Badge
                                variant={
                                  c.subscription_status === "active"
                                    ? "default"
                                    : "secondary"
                                }
                                className="w-fit"
                              >
                                {c.subscription_status}
                              </Badge>
                              <span className="text-xs text-muted-foreground">
                                {money(c.monthly_price_cents)}/mo
                                {c.cancel_at_period_end ? " · cancelling" : ""}
                              </span>
                            </div>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              not subscribed
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right">{c.user_count}</td>
                        <td className="py-2 pr-3 text-right">
                          {c.lead_count.toLocaleString()}
                        </td>
                        <td className="py-2 pr-3 text-right">
                          {c.month_usage_sends.toLocaleString()}
                        </td>
                        <td className="py-2 pr-3 text-xs text-muted-foreground">
                          {formatDate(c.created_at)}
                        </td>
                        <td className="py-2 text-right">
                          <Button
                            size="sm"
                            variant={suspended ? "outline" : "ghost"}
                            disabled={setStatus.isPending}
                            onClick={() =>
                              setStatus.mutate({
                                id: c.tenant_id,
                                status: suspended ? "active" : "suspended",
                              })
                            }
                          >
                            {suspended ? (
                              <>
                                <CheckCircle2 className="mr-1 h-3 w-3" aria-hidden="true" />
                                Reactivate
                              </>
                            ) : (
                              <>
                                <Ban className="mr-1 h-3 w-3" aria-hidden="true" />
                                Suspend
                              </>
                            )}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
