"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Mail, Pause, Play, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type CampaignInput,
  type CampaignOut,
  type CampaignStatus,
  type CampaignStepInput,
} from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

const STATUS_COLORS: Record<
  CampaignStatus,
  "default" | "secondary" | "outline" | "destructive"
> = {
  draft: "outline",
  active: "default",
  paused: "secondary",
  archived: "destructive",
};

function StepRow({
  step,
  index,
  onChange,
  onRemove,
}: {
  step: CampaignStepInput;
  index: number;
  onChange: (patch: Partial<CampaignStepInput>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="rounded-md border p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Step {index + 1}</span>
        <Button type="button" size="sm" variant="ghost" onClick={onRemove}>
          <Trash2 className="h-3 w-3" />
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        <div className="space-y-1">
          <Label className="text-xs">Delay (days)</Label>
          <Input
            type="number"
            min={0}
            value={step.delay_days}
            onChange={(e) =>
              onChange({ delay_days: parseInt(e.target.value, 10) || 0 })
            }
          />
        </div>
        <div className="space-y-1 md:col-span-2">
          <Label className="text-xs">Subject template</Label>
          <Input
            value={step.subject_template}
            onChange={(e) => onChange({ subject_template: e.target.value })}
            placeholder="e.g. Quick question for {{first_name}}"
          />
        </div>
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Goal</Label>
        <Input
          value={step.goal ?? ""}
          onChange={(e) => onChange({ goal: e.target.value || null })}
          placeholder="e.g. Get a reply confirming interest"
        />
      </div>
    </div>
  );
}

function CampaignForm({
  initial,
  onSubmit,
  submitLabel,
  onCancel,
}: {
  initial?: Partial<CampaignInput>;
  onSubmit: (values: CampaignInput) => void;
  submitLabel: string;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [llmModel, setLlmModel] = useState(initial?.llm_model ?? "");
  const [sampleEmails, setSampleEmails] = useState(
    (initial?.style_sample_emails ?? []).join("\n")
  );
  const [styleNotes, setStyleNotes] = useState(initial?.style_notes ?? "");
  const [steps, setSteps] = useState<CampaignStepInput[]>(
    initial?.steps && initial.steps.length > 0
      ? initial.steps.map((s) => ({ ...s }))
      : [{ step_number: 1, delay_days: 0, subject_template: "", goal: null }]
  );

  function updateStep(i: number, patch: Partial<CampaignStepInput>) {
    setSteps((prev) =>
      prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s))
    );
  }
  function addStep() {
    setSteps((prev) => [
      ...prev,
      {
        step_number: prev.length + 1,
        delay_days: prev.length * 3,
        subject_template: "",
        goal: null,
      },
    ]);
  }
  function removeStep(i: number) {
    setSteps((prev) =>
      prev
        .filter((_, idx) => idx !== i)
        .map((s, idx) => ({ ...s, step_number: idx + 1 }))
    );
  }

  function handleSubmit() {
    const emails = sampleEmails
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
      .slice(0, 3);
    onSubmit({
      name,
      description: description || null,
      llm_model: llmModel || null,
      style_sample_emails: emails,
      style_notes: styleNotes || null,
      steps: steps.map((s, i) => ({
        step_number: i + 1,
        delay_days: s.delay_days,
        subject_template: s.subject_template,
        goal: s.goal ?? null,
      })),
    });
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        handleSubmit();
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="camp_name">Name</Label>
        <Input
          id="camp_name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          placeholder="e.g. Q3 SaaS founders outreach"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="camp_desc">Description</Label>
        <Textarea
          id="camp_desc"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          placeholder="Optional — what is this campaign trying to do?"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="camp_model">LLM model</Label>
        <Input
          id="camp_model"
          value={llmModel}
          onChange={(e) => setLlmModel(e.target.value)}
          placeholder="e.g. gpt-4o-mini (optional)"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="camp_samples">Style sample emails (max 3, one per line)</Label>
        <Textarea
          id="camp_samples"
          value={sampleEmails}
          onChange={(e) => setSampleEmails(e.target.value)}
          rows={4}
          placeholder={"Hi {{first_name}},\n\nLoved your post on..."}
        />
        <p className="text-[10px] text-muted-foreground">
          Pasted once per line. Used by the writer agent to mimic tone.
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="camp_notes">Style notes</Label>
        <Textarea
          id="camp_notes"
          value={styleNotes}
          onChange={(e) => setStyleNotes(e.target.value)}
          rows={3}
          placeholder="Optional — extra instructions for tone, length, etc."
        />
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>Steps</Label>
          <Button type="button" size="sm" variant="outline" onClick={addStep}>
            <Plus className="mr-1 h-3 w-3" />
            Add step
          </Button>
        </div>
        <div className="space-y-2">
          {steps.map((s, i) => (
            <StepRow
              key={i}
              step={s}
              index={i}
              onChange={(patch) => updateStep(i, patch)}
              onRemove={() => removeStep(i)}
            />
          ))}
        </div>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit">{submitLabel}</Button>
      </DialogFooter>
    </form>
  );
}

export default function CampaignsPage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.listCampaigns(),
  });

  const create = useMutation({
    mutationFn: (values: CampaignInput) => api.createCampaign(values),
    onSuccess: () => {
      toast.success("Campaign created");
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const setStatus = useMutation({
    mutationFn: (vars: { id: string; status: CampaignStatus }) =>
      api.updateCampaign(vars.id, { status: vars.status }),
    onSuccess: (_data, vars) => {
      toast.success(`Campaign ${vars.status}`);
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteCampaign(id),
    onSuccess: () => {
      toast.success("Campaign deleted");
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  function confirmDelete(c: CampaignOut) {
    if (window.confirm(`Delete campaign "${c.name}"? This cannot be undone.`)) {
      remove.mutate(c.id);
    }
  }

  const items = list.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Campaigns</h1>
          <p className="text-muted-foreground">
            Multi-step outreach sequences. Each step has a delay, a subject template, and an
            LLM-generated body tailored to the lead.
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              New campaign
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>New campaign</DialogTitle>
              <DialogDescription>
                Define the steps and writing style. You can add more steps later.
              </DialogDescription>
            </DialogHeader>
            <CampaignForm
              submitLabel="Create"
              onCancel={() => setCreateOpen(false)}
              onSubmit={(values) => create.mutate(values)}
            />
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Mail className="h-4 w-4" />
            Your campaigns
          </CardTitle>
          <CardDescription>
            {list.isLoading
              ? "Loading…"
              : `${items.length} campaign${items.length === 1 ? "" : "s"}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No campaigns yet. Create one to start generating personalized drafts.
            </p>
          )}
          {items.length > 0 && (
            <div className="space-y-2">
              {items.map((c) => {
                const expanded = expandedId === c.id;
                return (
                  <div key={c.id} className="rounded-md border">
                    <button
                      type="button"
                      onClick={() => setExpandedId(expanded ? null : c.id)}
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
                            <span className="font-medium">{c.name}</span>
                            <Badge variant={STATUS_COLORS[c.status]}>{c.status}</Badge>
                          </div>
                          {c.description && (
                            <p className="mt-0.5 truncate text-sm text-muted-foreground">
                              {c.description}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-3 text-right text-xs text-muted-foreground">
                        <div>
                          <div>{c.steps.length} step{c.steps.length === 1 ? "" : "s"}</div>
                          <div>Updated {formatDate(c.updated_at)}</div>
                        </div>
                      </div>
                    </button>
                    {expanded && (
                      <div className="border-t bg-muted/20 p-4 space-y-3">
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                          {c.llm_model && (
                            <div className="text-xs text-muted-foreground">
                              <strong>Model:</strong> {c.llm_model}
                            </div>
                          )}
                          {c.style_notes && (
                            <div className="text-xs text-muted-foreground md:col-span-2">
                              <strong>Style notes:</strong> {c.style_notes}
                            </div>
                          )}
                        </div>
                        {c.steps.length > 0 && (
                          <div className="space-y-2">
                            <p className="text-xs font-medium text-muted-foreground">Steps</p>
                            {c.steps.map((s) => (
                              <div
                                key={s.id}
                                className="rounded-md border bg-background p-3 text-sm"
                              >
                                <div className="flex items-center justify-between">
                                  <span className="font-medium">
                                    Step {s.step_number}
                                  </span>
                                  <span className="text-xs text-muted-foreground">
                                    +{s.delay_days}d
                                  </span>
                                </div>
                                <p className="mt-1 text-xs text-muted-foreground">
                                  Subject: <span className="font-mono">{s.subject_template}</span>
                                </p>
                                {s.goal && (
                                  <p className="mt-1 text-xs text-muted-foreground">
                                    Goal: {s.goal}
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
                          {c.status === "active" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                setStatus.mutate({ id: c.id, status: "paused" })
                              }
                              disabled={setStatus.isPending}
                            >
                              <Pause className="mr-1 h-3 w-3" />
                              Pause
                            </Button>
                          )}
                          {c.status === "paused" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                setStatus.mutate({ id: c.id, status: "active" })
                              }
                              disabled={setStatus.isPending}
                            >
                              <Play className="mr-1 h-3 w-3" />
                              Resume
                            </Button>
                          )}
                          {c.status === "draft" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                setStatus.mutate({ id: c.id, status: "active" })
                              }
                              disabled={setStatus.isPending}
                            >
                              <Play className="mr-1 h-3 w-3" />
                              Activate
                            </Button>
                          )}
                          {c.status !== "archived" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                setStatus.mutate({ id: c.id, status: "archived" })
                              }
                              disabled={setStatus.isPending}
                            >
                              Archive
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => confirmDelete(c)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
