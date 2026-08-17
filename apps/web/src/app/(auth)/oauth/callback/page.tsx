"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

/**
 * Lands here after a social sign-in.
 *
 * Tokens arrive in the URL *fragment*: browsers never transmit it to a server,
 * so it stays out of access logs, proxy logs and the Referer header — unlike a
 * query string. We consume it and immediately clear it from history so the
 * credentials aren't left sitting in the address bar.
 */
function OAuthCallback() {
  const router = useRouter();
  const { adoptSession } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const accessToken = params.get("access_token");
    const refreshToken = params.get("refresh_token");

    // Drop the tokens from the address bar and from history.
    window.history.replaceState(null, "", window.location.pathname);

    if (!accessToken || !refreshToken) {
      setError("Sign-in didn't complete. Please try again.");
      return;
    }

    adoptSession(accessToken, refreshToken)
      .then(() => router.replace("/dashboard"))
      .catch((e: Error) => setError(e.message));
  }, [adoptSession, router]);

  return (
    <div className="text-center text-sm">
      {error ? (
        <>
          <p className="text-destructive">{error}</p>
          <a href="/login" className="underline">
            Back to sign in
          </a>
        </>
      ) : (
        <p className="text-muted-foreground">Signing you in…</p>
      )}
    </div>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={null}>
      <OAuthCallback />
    </Suspense>
  );
}
