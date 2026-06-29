"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CalendarClock, ChevronDown, ChevronRight, X } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type MeetingOut,
  type MeetingStatus,
} from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

const STATUS_COLORS: Record<
  MeetingStatus,
  "default" | "secondary" | "outline" | "destructive"
> = {
  proposed: "secondary",
  confirmed: "default",
  declined: "outline",
  cancelled: "destructive",
  completed: "outline",
  no_show: "destructive",
};

const STATUS_FILTERS: Array<{ value: "" | MeetingStatus; label: string }> = [
  { value: "", label: "All" },
  { value: "proposed", label: "Proposed" },
  { value: "confirmed", label: "Confirmed" },
  { value: "declined", label: "Declined" },
  { value: "cancelled", label: "Cancelled" },
  { value: "completed", label: "Completed" },
];

function MeetingRow({
  meeting,
  expanded,
  onToggle,
  onConfirm,
  onDecline,
  onCancel,
  busy,
}: {
  meeting: MeetingOut;
  expanded: boolean;
  onToggle: () => void;
  onConfirm: (slot_index: number) => void;
  onDecline: () => void;
  onCancel: () => void;
  busy: boolean;
}) {
  return (
    <div className="rounded-md border">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-muted/30"
      >
        <div className="flex min-w-0 flex-1 items-center gap-3">
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium">{meeting.subject}</span>
              <Badge variant={STATUS_COLORS[meeting.status]}>
                {meeting.status}
              </Badge>
            </div>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {meeting.attendee_email} ·{" "}
              {meeting.chosen_slot
                ? formatDate(meeting.chosen_slot)
                : "no time chosen"}
            </p>
          </div>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          {meeting.provider_event_id ? (
            <span className="font-mono text-[10px]">
              {meeting.provider_event_id.slice(0, 12)}…
            </span>
          ) : (
            <span>no calendar event</span>
          )}
        </div>
      </button>
      {expanded && (
        <div className="space-y-4 border-t bg-muted/20 p-4">
          <div className="grid grid-cols-2 gap-3 text-xs text-muted-foreground md:grid-cols-4">
            <div>
              <strong className="text-foreground">Lead:</strong>{" "}
              {meeting.attendee_email}
            </div>
            <div>
              <strong className="text-foreground">Duration:</strong>{" "}
              {meeting.duration_minutes} min
            </div>
            <div>
              <strong className="text-foreground">Organiser:</strong>{" "}
              {meeting.organizer_email}
            </div>
            <div>
              <strong className="text-foreground">ICS UID:</strong>{" "}
              <span className="font-mono text-[10px]">
                {meeting.ics_uid}
              </span>
            </div>
            {meeting.agenda && (
              <div className="md:col-span-4">
                <strong className="text-foreground">Agenda:</strong>{" "}
                {meeting.agenda}
              </div>
            )}
            {meeting.location && (
              <div className="md:col-span-2">
                <strong className="text-foreground">Location:</strong>{" "}
                {meeting.location}
              </div>
            )}
          </div>
          {meeting.proposed_slots.length > 0 && meeting.status === "proposed" && (
            <div className="space-y-2 border-t pt-3">
              <p className="text-xs font-medium text-foreground">
                Proposed times (pick one to confirm):
              </p>
              <div className="grid gap-2 md:grid-cols-3">
                {meeting.proposed_slots.map((slot) => (
                  <button
                    key={slot.index}
                    type="button"
                    disabled={busy}
                    onClick={() => onConfirm(slot.index)}
                    className="rounded-md border p-3 text-left text-xs hover:border-primary disabled:opacity-50"
                  >
                    <div className="font-medium">
                      Option {slot.index + 1}
                    </div>
                    <div className="text-muted-foreground">
                      {formatDate(slot.start)}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            {meeting.status === "proposed" && (
              <Button
                size="sm"
                variant="outline"
                onClick={onDecline}
                disabled={busy}
              >
                <X className="mr-1 h-3 w-3" />
                Decline
              </Button>
            )}
            {meeting.status === "confirmed" && (
              <Button
                size="sm"
                variant="outline"
                onClick={onCancel}
                disabled={busy}
              >
                <X className="mr-1 h-3 w-3" />
                Cancel
              </Button>
            )}
            {meeting.confirmed_at && (
              <span className="text-xs text-muted-foreground">
                Confirmed {formatDate(meeting.confirmed_at)}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function MeetingsPage() {
  const queryClient = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"" | MeetingStatus>("");

  const list = useQuery({
    queryKey: ["meetings", { status: statusFilter }],
    queryFn: () =>
      api.listMeetings({
        status: statusFilter || undefined,
        limit: 100,
      }),
  });

  const confirm = useMutation({
    mutationFn: (args: { id: string; slot_index: number }) =>
      api.confirmMeeting(args.id, args.slot_index),
    onSuccess: () => {
      toast.success("Meeting confirmed and calendar event created");
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const decline = useMutation({
    mutationFn: (id: string) => api.declineMeeting(id),
    onSuccess: () => {
      toast.success("Meeting declined");
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelMeeting(id),
    onSuccess: () => {
      toast.success("Meeting cancelled");
      queryClient.invalidateQueries({ queryKey: ["meetings"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Meetings</h1>
        <p className="text-muted-foreground">
          Proposed and confirmed meetings from positive replies. Confirm a
          slot to create the calendar event (and trigger a CRM sync if
          any connections are active).
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarClock className="h-4 w-4" />
            All meetings
          </CardTitle>
          <CardDescription>
            {list.isLoading
              ? "Loading…"
              : `${total} meeting${total === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Status:</span>
            {STATUS_FILTERS.map((f) => (
              <Button
                key={f.value}
                size="sm"
                variant={statusFilter === f.value ? "default" : "outline"}
                onClick={() => setStatusFilter(f.value)}
              >
                {f.label}
              </Button>
            ))}
          </div>
          {list.error && (
            <p className="text-sm text-destructive">
              {(list.error as Error).message}
            </p>
          )}
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No meetings yet. Positive replies on outbound emails will
              auto-create proposals here.
            </p>
          )}
          {items.length > 0 && (
            <div className="space-y-2">
              {items.map((m) => (
                <MeetingRow
                  key={m.id}
                  meeting={m}
                  expanded={expandedId === m.id}
                  onToggle={() =>
                    setExpandedId(expandedId === m.id ? null : m.id)
                  }
                  onConfirm={(slot_index) =>
                    confirm.mutate({ id: m.id, slot_index })
                  }
                  onDecline={() => {
                    if (window.confirm("Decline this meeting?")) {
                      decline.mutate(m.id);
                    }
                  }}
                  onCancel={() => {
                    if (window.confirm("Cancel this meeting?"))
                      cancel.mutate(m.id);
                  }}
                  busy={confirm.isPending || decline.isPending || cancel.isPending}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
