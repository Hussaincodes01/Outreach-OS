"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { Button } from "@/components/ui/button";

/** Inline marks so no external asset request is needed (the CSP blocks those). */
function GoogleMark() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.9 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.0 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.6-.4-3.9z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.0 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.3 0-9.7-3.1-11.3-7.9l-6.5 5C9.6 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C36.9 40.2 44 35 44 24c0-1.3-.1-2.6-.4-3.9z" />
    </svg>
  );
}

function MicrosoftMark() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 23 23" aria-hidden="true">
      <path fill="#f25022" d="M1 1h10v10H1z" />
      <path fill="#7fba00" d="M12 1h10v10H12z" />
      <path fill="#00a4ef" d="M1 12h10v10H1z" />
      <path fill="#ffb900" d="M12 12h10v10H12z" />
    </svg>
  );
}

const MARKS: Record<string, () => JSX.Element> = {
  google: GoogleMark,
  microsoft: MicrosoftMark,
};

/**
 * Sign-in buttons for whichever providers the server has credentials for.
 *
 * The list comes from the API rather than being hard-coded, so a deployment
 * that hasn't configured Microsoft never shows a button that would dead-end.
 * Renders nothing when no provider is set up.
 */
export function SocialButtons({ action = "Continue" }: { action?: string }) {
  const providers = useQuery({
    queryKey: ["social-providers"],
    queryFn: () => api.socialProviders(),
    staleTime: 5 * 60_000,
  });

  if (!providers.data?.length) return null;

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        {providers.data.map((p) => {
          const Mark = MARKS[p.provider];
          return (
            <Button
              key={p.provider}
              type="button"
              variant="outline"
              className="w-full"
              // Full navigation, not fetch: the consent screen is a page.
              onClick={() => {
                window.location.href = api.socialLoginUrl(p.provider);
              }}
            >
              {Mark ? <span className="mr-2"><Mark /></span> : null}
              {action} with {p.label}
            </Button>
          );
        })}
      </div>
      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-border" />
        <span className="text-xs text-muted-foreground">or</span>
        <span className="h-px flex-1 bg-border" />
      </div>
    </div>
  );
}
