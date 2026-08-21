"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CreditCard, ExternalLink, TrendingUp } from "lucide-react";
import { api } from "@/lib/api-client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { formatDate } from "@/lib/utils";

export default function BillingPage() {
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api.listPlans() });
  const sub = useQuery({ queryKey: ["subscription"], queryFn: () => api.getSubscription() });
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => api.getUsage() });
  // Only shown on demand once someone is already paying — see below.
  const [showUpgrades, setShowUpgrades] = useState(false);

  const activeCode = sub.data?.plan.code ?? "starter";

  // "Paying" means a live subscription, not merely a plan label: a tenant row
  // says 'starter' from signup, which is not the same as having bought it.
  const isSubscribed =
    !!sub.data && ["active", "trialing", "past_due"].includes(sub.data.status);
  const currentPrice = sub.data?.plan.monthly_price_cents ?? -1;

  const allPlans = plans.data?.items ?? [];
  // Once subscribed, the plan grid is not a shop front any more. Showing
  // "Choose a plan" to someone who already chose one is noise, and offering a
  // downgrade button next to their live plan invites accidental churn — so we
  // surface strictly higher tiers, and only when they ask.
  const upgrades = allPlans.filter((p) => p.monthly_price_cents > currentPrice);
  const visiblePlans = isSubscribed ? upgrades : allPlans;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Billing &amp; plans</h1>
        <p className="text-muted-foreground">
          Plan tier, monthly usage, and the in-app portal. V1 launch point \u2014 we stop here.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="h-4 w-4" /> Current plan
          </CardTitle>
          <CardDescription>
            {sub.isLoading
              ? "Loading\u2026"
              : sub.data
              ? `${sub.data.plan.name} \u00b7 ${sub.data.status}`
              : "Free tier"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sub.data && (
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-muted-foreground">Renews</p>
                <p className="font-medium">
                  {sub.data.current_period_end ? formatDate(sub.data.current_period_end) : "\u2014"}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Provider</p>
                <Badge variant="outline">{sub.data.provider}</Badge>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4" /> This month
          </CardTitle>
          <CardDescription>
            {usage.data
              ? `Resets on ${formatDate(usage.data.reset_at)}`
              : "Loading usage\u2026"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {usage.data && (
            <div className="space-y-4">
              <UsageRow
                label="Sends"
                used={usage.data.sends_used}
                cap={usage.data.sends_cap}
                over={usage.data.over_sends}
              />
              <UsageRow
                label="Leads scraped"
                used={usage.data.leads_used}
                cap={usage.data.leads_cap}
                over={usage.data.over_leads}
              />
              <UsageRow
                label="LLM tokens"
                used={usage.data.llm_tokens_used}
                cap={usage.data.llm_tokens_cap}
                over={usage.data.over_llm_tokens}
              />
            </div>
          )}
        </CardContent>
      </Card>

      {isSubscribed && !showUpgrades && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4" aria-hidden="true" />
              Need more headroom?
            </CardTitle>
            <CardDescription>
              {upgrades.length > 0
                ? `You're on ${sub.data?.plan.name}. Higher tiers raise your send, lead and token limits.`
                : `You're on ${sub.data?.plan.name} — our highest tier. Use the portal below to change or cancel.`}
            </CardDescription>
          </CardHeader>
          {upgrades.length > 0 && (
            <CardContent>
              <Button variant="outline" onClick={() => setShowUpgrades(true)}>
                View upgrade options
              </Button>
            </CardContent>
          )}
        </Card>
      )}

      {(!isSubscribed || showUpgrades) && visiblePlans.length > 0 && (
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            {isSubscribed ? "Upgrade your plan" : "Choose a plan"}
          </h2>
          {isSubscribed && (
            <Button variant="ghost" size="sm" onClick={() => setShowUpgrades(false)}>
              Cancel
            </Button>
          )}
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {visiblePlans.map((p) => {
            const isActive = p.code === activeCode;
            return (
              <Card key={p.id} className={isActive ? "border-primary" : ""}>
                <CardHeader>
                  <CardTitle className="flex items-center justify-between">
                    {p.name}
                    {isActive && <Badge>current</Badge>}
                  </CardTitle>
                  <CardDescription>
                    ${(p.monthly_price_cents / 100).toFixed(0)}/mo
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <ul className="space-y-1 text-muted-foreground">
                    <li>
                      {p.monthly_send_cap.toLocaleString()} sends / month
                    </li>
                    <li>
                      {p.monthly_lead_cap.toLocaleString()} leads / month
                    </li>
                    <li>
                      {p.monthly_llm_token_cap.toLocaleString()} LLM tokens
                    </li>
                    <li>{p.max_mailboxes} mailboxes \u00b7 {p.max_team_seats} seats</li>
                    <li>
                      CRM sync: {p.crm_sync_enabled ? "yes" : "no"} \u00b7 Slack:{" "}
                      {p.slack_notifications_enabled ? "yes" : "no"}
                    </li>
                  </ul>
                  <Button
                    className="w-full"
                    disabled={isActive}
                    onClick={async () => {
                      const r = await api.startCheckout(p.code);
                      window.location.href = r.checkout_url;
                    }}
                  >
                    {isActive
                      ? "Active"
                      : isSubscribed
                        ? `Upgrade to ${p.name}`
                        : `Choose ${p.name}`}
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Manage subscription</CardTitle>
          <CardDescription>
            Update card, change billing email, or cancel. Powered by Stripe (stub in dev).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            variant="outline"
            onClick={async () => {
              const r = await api.startPortal();
              const url = r.token ? api.portalRedirectUrl(r.token) : r.portal_url;
              window.location.href = url;
            }}
          >
            <ExternalLink className="mr-2 h-4 w-4" />
            Open billing portal
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function UsageRow({ label, used, cap, over }: { label: string; used: number; cap: number; over: boolean }) {
  const pct = cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span>{label}</span>
        <span className="text-muted-foreground">
          {used.toLocaleString()} / {cap.toLocaleString()}{" "}
          {over && <Badge variant="destructive" className="ml-2">over</Badge>}
        </span>
      </div>
      <Progress value={pct} />
    </div>
  );
}
