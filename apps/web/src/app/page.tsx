"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, KeyRound, ShieldCheck, Sparkles, Upload } from "lucide-react";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const FEATURES = [
  {
    icon: KeyRound,
    title: "Your own AI key",
    body: "Connect OpenAI, Anthropic, Gemini, or any of 13 providers — including Ollama on your own hardware. Usage is billed to your account, at cost, with no markup from us.",
  },
  {
    icon: Sparkles,
    title: "Research that isn't a template",
    body: "An agent reads the prospect's site, your knowledge base, and your previous emails to them, then writes in the voice of emails you've already sent.",
  },
  {
    icon: Upload,
    title: "Start with the list you have",
    body: "Import a CSV from your CRM, Apollo, or a spreadsheet. Columns are matched automatically and duplicates are skipped.",
  },
  {
    icon: ShieldCheck,
    title: "Isolation at the database",
    body: "Every table is protected by PostgreSQL row-level security, not application checks. Credentials are encrypted per workspace and never returned by the API.",
  },
];

function formatPrice(cents: number): string {
  return cents === 0 ? "Free" : `$${Math.round(cents / 100)}`;
}

export default function MarketingPage() {
  // Plans come from the billing API, so pricing on this page can never drift
  // from what checkout will actually charge.
  const plans = useQuery({
    queryKey: ["public-plans"],
    queryFn: () => api.listPublicPlans(),
    retry: false,
  });

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-16">
      <section className="flex flex-col items-center gap-6 text-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.svg" alt="Outreach OS" className="h-14 w-auto" />
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
          Cold outreach that reads like you wrote it
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Find leads, research each one properly, and send from your own mailbox
          — on your own AI key. Multi-tenant, auditable, and yours to run.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Button asChild size="lg">
            <Link href="/signup">
              Start free <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" />
            </Link>
          </Button>
          <Button variant="outline" size="lg" asChild>
            <Link href="/login">Sign in</Link>
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          No card required to start. Bring your own AI key — we never mark up tokens.
        </p>
      </section>

      <section className="mt-20 grid gap-6 sm:grid-cols-2">
        {FEATURES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="rounded-lg border p-5">
            <Icon className="mb-3 h-5 w-5" aria-hidden="true" />
            <h2 className="mb-1 font-medium">{title}</h2>
            <p className="text-sm text-muted-foreground">{body}</p>
          </div>
        ))}
      </section>

      <section id="pricing" className="mt-24">
        <div className="mb-8 text-center">
          <h2 className="text-3xl font-semibold tracking-tight">Pricing</h2>
          <p className="mt-2 text-muted-foreground">
            Plans cover the platform. AI usage goes directly to your own provider
            account.
          </p>
        </div>

        {plans.isLoading && (
          <p className="text-center text-sm text-muted-foreground">Loading plans…</p>
        )}
        {plans.isError && (
          <p className="text-center text-sm text-muted-foreground">
            Pricing is temporarily unavailable.{" "}
            <Link href="/signup" className="underline">
              Create an account
            </Link>{" "}
            to see current plans.
          </p>
        )}

        <div className="grid gap-6 md:grid-cols-3">
          {plans.data?.items.map((plan) => {
            const featured = plan.code === "growth";
            return (
              <div
                key={plan.code}
                className={`flex flex-col rounded-lg border p-6 ${
                  featured ? "border-primary shadow-sm" : ""
                }`}
              >
                <div className="mb-1 flex items-center gap-2">
                  <h3 className="font-medium">{plan.name}</h3>
                  {featured && <Badge>Most popular</Badge>}
                </div>
                <p className="mb-4">
                  <span className="text-3xl font-semibold">
                    {formatPrice(plan.monthly_price_cents)}
                  </span>
                  {plan.monthly_price_cents > 0 && (
                    <span className="text-muted-foreground"> /month</span>
                  )}
                </p>
                <ul className="mb-6 space-y-2 text-sm">
                  <li className="flex gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    {plan.monthly_send_cap.toLocaleString()} emails / month
                  </li>
                  <li className="flex gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    {plan.monthly_lead_cap.toLocaleString()} leads / month
                  </li>
                  <li className="flex gap-2">
                    <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    {plan.max_mailboxes} mailbox{plan.max_mailboxes === 1 ? "" : "es"},{" "}
                    {plan.max_team_seats} seat{plan.max_team_seats === 1 ? "" : "s"}
                  </li>
                  {plan.crm_sync_enabled && (
                    <li className="flex gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                      CRM sync
                    </li>
                  )}
                  {plan.slack_notifications_enabled && (
                    <li className="flex gap-2">
                      <Check className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                      Slack notifications
                    </li>
                  )}
                </ul>
                <Button
                  asChild
                  className="mt-auto w-full"
                  variant={featured ? "default" : "outline"}
                >
                  {/* Checkout needs an authenticated workspace, so send people
                      through signup; billing picks the plan back up. */}
                  <Link href={`/signup?plan=${plan.code}`}>
                    Get started
                  </Link>
                </Button>
              </div>
            );
          })}
        </div>
      </section>

      <footer className="mt-24 border-t pt-8 text-center text-sm text-muted-foreground">
        <p>
          Outreach OS ·{" "}
          <Link href="/login" className="underline">
            Sign in
          </Link>{" "}
          ·{" "}
          <a
            href="https://github.com/Hussaincodes01/Outreach-OS"
            className="underline"
            target="_blank"
            rel="noreferrer"
          >
            Source
          </a>
        </p>
      </footer>
    </main>
  );
}
