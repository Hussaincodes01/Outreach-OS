import Link from "next/link";
import { Toaster } from "sonner";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-muted/30 p-6">
      <Link href="/" aria-label="Outreach OS home">
        <img src="/logo.svg" alt="Outreach OS" className="h-10 w-auto" />
      </Link>
      <div className="w-full max-w-md">
        {children}
        <Toaster richColors position="top-right" />
      </div>
    </div>
  );
}
