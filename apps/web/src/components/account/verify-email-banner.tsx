"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { MailWarning, X } from "lucide-react";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";

/**
 * Prompts an unverified user to confirm their address.
 *
 * Deliberately a nudge, not a wall: access is never gated on verification.
 * Locking someone out of a workspace they are already paying for, because a
 * confirmation email went to spam, costs more than it protects.
 */
export function VerifyEmailBanner() {
  const [dismissed, setDismissed] = useState(false);

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
    staleTime: 60_000,
  });

  const resend = useMutation({
    mutationFn: () => api.resendVerification(),
    onSuccess: (r) => toast.success(r.message),
    onError: (e: Error) => toast.error(e.message),
  });

  if (dismissed || !me.data || me.data.email_verified_at) return null;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b bg-amber-500/10 px-4 py-2 text-sm">
      <MailWarning className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1">
        Confirm <strong>{me.data.email}</strong> to secure your account.
      </span>
      <Button
        size="sm"
        variant="outline"
        onClick={() => resend.mutate()}
        disabled={resend.isPending}
      >
        {resend.isPending ? "Sending…" : "Resend email"}
      </Button>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        className="rounded p-1 hover:bg-black/5"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
