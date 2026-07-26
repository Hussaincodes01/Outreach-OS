import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function MarketingPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 px-6 py-24">
      <div className="flex flex-col items-center gap-4">
        {/* Static SVG logo: next/image would need `dangerouslyAllowSVG`, which we
            deliberately keep off. There is nothing to optimize here. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.svg" alt="Outreach OS" className="h-16 w-auto" />
        <h1 className="text-4xl font-semibold tracking-tight">
          Outreach OS
        </h1>
      </div>
      <p className="max-w-2xl text-center text-lg text-muted-foreground">
        Multi-tenant AI cold sales outreach. Find leads, write on-tone
        emails in your voice, send through your own mailbox, book meetings
        on your calendar — auditable end to end.
      </p>
      <div className="flex gap-3">
        <Button asChild>
          <Link href="/signup">Create account</Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/login">Sign in</Link>
        </Button>
      </div>
    </main>
  );
}
