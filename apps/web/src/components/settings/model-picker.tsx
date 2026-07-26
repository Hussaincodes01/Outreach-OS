"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, isSetupRequired } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";

/**
 * Choose which model this workspace drafts with.
 *
 * Only models whose provider has a connected key are selectable — the API
 * rejects the rest with 428, and letting a user pick one anyway would turn a
 * setup mistake into a failed campaign discovered days later.
 */
export function ModelPicker() {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string>("");

  const settings = useQuery({
    queryKey: ["llm-settings"],
    queryFn: () => api.getLlmSettings(),
  });
  const providers = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.listProviders(),
  });

  useEffect(() => {
    if (settings.data) setSelected(settings.data.default_llm_model ?? "");
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => api.updateLlmSettings(selected || null),
    onSuccess: () => {
      toast.success("Model updated");
      queryClient.invalidateQueries({ queryKey: ["llm-settings"] });
    },
    onError: (e: Error) => {
      toast.error(
        isSetupRequired(e)
          ? `${e.message} Connect it under Integrations first.`
          : e.message
      );
    },
  });

  const connected = new Set(
    (providers.data ?? []).filter((p) => p.connected).map((p) => p.provider)
  );
  const models = settings.data?.available_models ?? [];
  const hasAnyKey = connected.size > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI model</CardTitle>
        <CardDescription>
          Drafting runs on your own API key, so the choice is yours — and so is
          the bill. Campaigns can override this individually.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!hasAnyKey && (
          <p className="text-sm text-muted-foreground">
            No AI provider connected yet.{" "}
            <a href="/integrations" className="underline">
              Connect one
            </a>{" "}
            to pick a model.
          </p>
        )}
        <div className="space-y-1">
          <Label htmlFor="model">Default model</Label>
          <select
            id="model"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            disabled={!hasAnyKey}
          >
            <option value="">Server default</option>
            {models.map((m) => {
              const provider = m.split("/")[0];
              const usable = connected.has(provider);
              return (
                <option key={m} value={m} disabled={!usable}>
                  {m}
                  {usable ? "" : " — no key connected"}
                </option>
              );
            })}
          </select>
        </div>
        <Button
          onClick={() => save.mutate()}
          disabled={save.isPending || !hasAnyKey}
          size="sm"
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </CardContent>
    </Card>
  );
}
