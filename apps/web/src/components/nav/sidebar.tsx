"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import {
  LayoutDashboard,
  KeyRound,
  Mail,
  ScrollText,
  Settings,
  LogOut,
  Target,
  Users,
  Database,
  History,
  Globe,
  Inbox,
  BookOpen,
  Bell,
  CreditCard,
  FileText,
  Play,
  Send,
  Ban,
  CalendarCheck,
  Link2,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { useApiAuthBridge, api } from "@/lib/api-client";
import { useQuery } from "@tanstack/react-query";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/icps", label: "ICPs", icon: Target },
  { href: "/leads", label: "Leads", icon: Users },
  { href: "/lead-sources", label: "Lead sources", icon: Database },
  { href: "/scraping-jobs", label: "Scraping jobs", icon: History },
  { href: "/proxies", label: "Proxies", icon: Globe },
  { href: "/integrations", label: "Integrations", icon: KeyRound },
  { href: "/mailboxes", label: "Mailboxes", icon: Inbox },
  { href: "/campaigns", label: "Campaigns", icon: Mail },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/drafts", label: "Drafts", icon: FileText },
  { href: "/sequences", label: "Sequences", icon: Play },
  { href: "/sends", label: "Sends", icon: Send },
  { href: "/replies", label: "Replies", icon: Inbox },
  { href: "/suppressions", label: "Suppressions", icon: Ban },
  { href: "/meetings", label: "Meetings", icon: CalendarCheck },
  { href: "/crm", label: "CRM sync", icon: Link2 },
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/audit", label: "Audit", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
];

// Platform staff only. Separate from NAV so a customer never renders it,
// and the API returns 404 to non-staff regardless of what the UI shows.
const ADMIN_NAV = { href: "/admin", label: "Admin", icon: ShieldCheck };

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, signOut, loading } = useAuth();
  useApiAuthBridge();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  return (
    <aside className="flex h-screen w-60 flex-col border-r bg-muted/30">
      <Link
        href="/dashboard"
        className="flex h-16 items-center gap-3 border-b px-4 font-semibold text-foreground hover:text-primary"
      >
        {/* Static SVG logo: next/image would need `dangerouslyAllowSVG`, which we
            deliberately keep off. There is nothing to optimize here. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo.svg" alt="" className="h-9 w-9 shrink-0" aria-hidden="true" />
        <span className="text-lg tracking-tight">Outreach OS</span>
      </Link>
      <nav className="flex-1 space-y-1 p-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname?.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              <span className="flex-1">{label}</span>
              {href === "/notifications" ? <UnreadBadge /> : null}
            </Link>
          );
        })}
        <AdminLink />
      </nav>
      <div className="border-t p-3">
        {user && (
          <div className="mb-2 truncate px-1 text-xs text-muted-foreground">
            {user.email}
          </div>
        )}
        <button
          onClick={() => {
            signOut();
            router.push("/login");
          }}
          className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </div>
    </aside>
  );
}

function UnreadBadge() {
  const { user } = useAuth();
  const { data } = useQuery({
    queryKey: ["notifications", "unread_count"],
    queryFn: () => api.unreadCount(),
    enabled: !!user,
    refetchInterval: 30_000,
  });
  const n = data?.unread ?? 0;
  if (!n) return null;
  return (
    <span className="rounded-full bg-red-600 px-2 py-0.5 text-xs font-semibold leading-none text-white">
      {n > 99 ? "99+" : n}
    </span>
  );
}


/** Renders the admin console link only for platform staff. */
function AdminLink() {
  const pathname = usePathname();
  const { data } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
    staleTime: 5 * 60_000,
  });
  if (!data?.is_platform_admin) return null;
  const { href, label, icon: Icon } = ADMIN_NAV;
  const active = pathname === href || pathname?.startsWith(href + "/");
  return (
    <Link
      href={href}
      className={cn(
        "mt-2 flex items-center gap-3 rounded-md border-t border-dashed px-3 py-2 pt-3 text-sm font-medium",
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      <span className="flex-1">{label}</span>
    </Link>
  );
}
