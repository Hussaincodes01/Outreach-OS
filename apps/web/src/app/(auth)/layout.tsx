import Link from "next/link";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-muted/30 p-6">
      <Link href="/" aria-label="Outreach OS home">
        {/* Static SVG logo: next/image would need `dangerouslyAllowSVG`, which we
            deliberately keep off. There is nothing to optimize here. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.svg" alt="Outreach OS" className="h-10 w-auto" />
      </Link>
      <div className="w-full max-w-md">
        {children}
      </div>
    </div>
  );
}
