"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, isSetupRequired, type ModelOut } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

const TIER_LABEL: Record<string, string> = {
  fast: "fast · low cost",
  balanced: "balanced",
  frontier: "highest quality",
};

/**
 * Choose the chat and embedding models this workspace uses.
 *
 * Models whose provider has no connected key are shown but disabled, so the
 * catalogue doubles as a discovery surface: you can see what connecting
 * another provider would unlock.
 */
export function ModelPicker() {
  const queryClient = useQueryClient();
  const [chat, setChat] = useState<string>("");
  const [embedding, setEmbedding] = useState<string>("");

  const settings = useQuery({
    queryKey: ["llm-settings"],
    queryFn: () => api.getLlmSettings(),
  });

  useEffect(() => {
    if (settings.data) {
      setChat(settings.data.default_llm_model ?? "");
      setEmbedding(settings.data.embedding_llm_model ?? "");
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      api.updateLlmSettings({
        default_llm_model: chat || null,
        embedding_llm_model: embedding || null,
      }),
    onSuccess: () => {
      toast.success("Model settings saved");
      queryClient.invalidateQueries({ queryKey: ["llm-settings"] });
    },
    onError: (e: Error) =>
      toast.error(
        isSetupRequired(e) ? `${e.message} Connect it under Integrations first.` : e.message
      ),
  });

  // Derive from `settings.data` rather than an intermediate `?? []`, which
  // would be a fresh array on every render and defeat the memo.
  const models = useMemo<ModelOut[]>(
    () => settings.data?.models ?? [],
    [settings.data]
  );
  const embeddings = settings.data?.embedding_models ?? [];
  const anyAvailable = models.some((m) => m.available);
  const customProviders = settings.data?.custom_model_providers ?? [];
  // A gateway or self-hosted endpoint serves whatever its operator deployed,
  // so the catalogue can only suggest — the user must be able to type a name.
  const canTypeModel = customProviders.length > 0;
  const isCustom = Boolean(chat) && !models.some((m) => m.id === chat);

  /** Group by provider so a long catalogue stays scannable. */
  const grouped = useMemo(() => {
    const out = new Map<string, ModelOut[]>();
    for (const m of models) {
      const list = out.get(m.provider_label) ?? [];
      list.push(m);
      out.set(m.provider_label, list);
    }
    return [...out.entries()];
  }, [models]);

  const selected = models.find((m) => m.id === chat);

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI models</CardTitle>
        <CardDescription>
          Drafting runs on your own API key, so the choice — and the bill — is
          yours. Individual campaigns can override the chat model.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!anyAvailable && (
          <p className="text-sm text-muted-foreground">
            No AI provider connected yet.{" "}
            <a href="/integrations" className="underline">
              Connect one
            </a>{" "}
            to pick a model.
          </p>
        )}

        <div className="space-y-1">
          <Label htmlFor="chat-model">Drafting model</Label>
          <select
            id="chat-model"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
            value={chat}
            onChange={(e) => setChat(e.target.value)}
            disabled={!anyAvailable}
          >
            <option value="">Server default</option>
            {grouped.map(([providerLabel, list]) => (
              <optgroup key={providerLabel} label={providerLabel}>
                {list.map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.available}>
                    {m.label}
                    {m.available ? ` — ${TIER_LABEL[m.tier] ?? m.tier}` : " — no key connected"}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {canTypeModel && (
            <div className="space-y-1 pt-2">
              <Label htmlFor="custom-model" className="text-xs font-normal">
                …or type a model your endpoint serves
              </Label>
              <input
                id="custom-model"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                placeholder={`${customProviders[0]}/your-model-name`}
                value={isCustom ? chat : ""}
                onChange={(e) => setChat(e.target.value.trim())}
              />
              <p className="text-xs text-muted-foreground">
                Must start with a connected provider, e.g.{" "}
                <code>{customProviders[0]}/malibu</code>.
              </p>
            </div>
          )}
          {selected && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Badge variant="outline" className="text-xs">
                {(selected.context_window / 1000).toLocaleString()}k context
              </Badge>
              <Badge
                variant={selected.supports_tools ? "secondary" : "outline"}
                className="text-xs"
              >
                {selected.supports_tools
                  ? "supports the research agent"
                  : "no tool calling — basic research only"}
              </Badge>
            </div>
          )}
        </div>

        <div className="space-y-1">
          <Label htmlFor="embedding-model">Knowledge base embeddings</Label>
          <select
            id="embedding-model"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
            value={embedding}
            onChange={(e) => setEmbedding(e.target.value)}
          >
            <option value="">Server default</option>
            {embeddings.map((e) => (
              <option key={e.id} value={e.id} disabled={!e.available}>
                {e.provider_label} · {e.label}
                {e.available ? "" : " — no key connected"}
              </option>
            ))}
          </select>
          <p className="pt-1 text-xs text-muted-foreground">
            Embeddings are a separate choice because most providers don&apos;t offer
            them — you can draft on one provider and embed on another. Only
            1536-dimension models are listed, to match the knowledge-base index.
          </p>
        </div>

        <Button onClick={() => save.mutate()} disabled={save.isPending} size="sm">
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </CardContent>
    </Card>
  );
}
