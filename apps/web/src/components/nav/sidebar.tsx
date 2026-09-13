"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  KeyRound,
  Mail,
  ScrollText,
  Settings,
  Target,
  Users,
  Database,
  History,
  Globe,
  Inbox,
  BookOpen,
  Bell,
  FileText,
  Play,
  Send,
  Ban,
  CalendarCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api-client";
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
  { href: "/notifications", label: "Notifications", icon: Bell },
  { href: "/audit", label: "Audit", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

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
      </nav>
      <div className="border-t p-3">
        <div className="truncate px-1 text-xs text-muted-foreground">
          Local workspace
        </div>
      </div>
    </aside>
  );
}

function UnreadBadge() {
  const { data } = useQuery({
    queryKey: ["notifications", "unread_count"],
    queryFn: () => api.unreadCount(),
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
