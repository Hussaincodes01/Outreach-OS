"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronRight, Circle, X } from "lucide-react";
import { api, type OnboardingStepOut } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * First-run checklist.
 *
 * The server derives every step from live workspace state, so this stays
 * truthful if the user later removes their API key. It hides itself once the
 * workspace is ready, or if the user dismisses it.
 */
export function SetupChecklist({ compact = false }: { compact?: boolean }) {
  const queryClient = useQueryClient();

  const status = useQuery({
    queryKey: ["onboarding"],
    queryFn: () => api.getOnboarding(),
  });

  const dismiss = useMutation({
    mutationFn: () => api.dismissOnboarding(true),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["onboarding"] }),
  });

  const data = status.data;
  if (!data || data.ready || data.dismissed) return null;

  const required = data.steps.filter((s) => s.required);
  const doneCount = required.filter((s) => s.done).length;

  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="text-base">Finish setting up your workspace</CardTitle>
          <CardDescription>
            {doneCount} of {required.length} required steps done. You bring your own
            AI provider key — drafts are billed to your account, never ours.
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => dismiss.mutate()}
          disabled={dismiss.isPending}
          aria-label="Dismiss setup checklist"
        >
          <X className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-1">
        {data.steps
          .filter((s) => (compact ? s.required : true))
          .map((step) => (
            <StepRow key={step.key} step={step} isNext={step.key === data.next_step_key} />
          ))}
      </CardContent>
    </Card>
  );
}

function StepRow({ step, isNext }: { step: OnboardingStepOut; isNext: boolean }) {
  return (
    <Link
      href={step.href}
      className={`flex items-center gap-3 rounded-md px-3 py-2 transition-colors hover:bg-muted ${
        isNext ? "bg-background ring-1 ring-primary/40" : ""
      }`}
    >
      {step.done ? (
        <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
      ) : (
        <Circle className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={`text-sm font-medium ${
              step.done ? "text-muted-foreground line-through" : ""
            }`}
          >
            {step.title}
          </span>
          {!step.required && (
            <span className="text-xs text-muted-foreground">(optional)</span>
          )}
        </div>
        {!step.done && (
          <p className="text-xs text-muted-foreground">{step.description}</p>
        )}
      </div>
      {step.detail && (
        <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">
          {step.detail}
        </span>
      )}
      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    </Link>
  );
}
