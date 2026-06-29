"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  api,
  type KnowledgeItemCreate,
  type KnowledgeItemOut,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";

function KnowledgeForm({
  onSubmit,
  onCancel,
  submitLabel,
}: {
  onSubmit: (values: KnowledgeItemCreate) => void;
  onCancel: () => void;
  submitLabel: string;
}) {
  const [title, setTitle] = useState("");
  const [source, setSource] = useState("case_studies");
  const [body, setBody] = useState("");

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ title, body, source: source || undefined });
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="k_title">Title</Label>
        <Input
          id="k_title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          placeholder="e.g. Acme Inc — 3x reply rate in 6 weeks"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="k_source">Source</Label>
        <Input
          id="k_source"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="case_studies"
        />
        <p className="text-[10px] text-muted-foreground">
          Free-form tag used to group items. Defaults to <code>case_studies</code>.
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="k_body">Body</Label>
        <Textarea
          id="k_body"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          required
          rows={12}
          placeholder="Paste the full case study, testimonial, or reference material. The writer agent will chunk and index it."
        />
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

function ViewDialog({
  item,
  open,
  onOpenChange,
}: {
  item: KnowledgeItemOut | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const detail = useQuery({
    queryKey: ["knowledge", item?.id],
    queryFn: () => api.getKnowledge(item!.id),
    enabled: open && !!item,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{item?.title ?? "Knowledge item"}</DialogTitle>
          <DialogDescription>
            {item
              ? `Source: ${item.source} • ${item.chunk_count} chunk${
                  item.chunk_count === 1 ? "" : "s"
                } • Created ${formatDate(item.created_at)}`
              : "Loading…"}
          </DialogDescription>
        </DialogHeader>
        {detail.isLoading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {detail.data?.body !== undefined && (
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-4 text-xs">
            {detail.data.body}
          </pre>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function KnowledgePage() {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [viewing, setViewing] = useState<KnowledgeItemOut | null>(null);

  const list = useQuery({
    queryKey: ["knowledge"],
    queryFn: () => api.listKnowledge({ limit: 200 }),
  });

  const create = useMutation({
    mutationFn: (values: KnowledgeItemCreate) => api.createKnowledge(values),
    onSuccess: () => {
      toast.success("Knowledge item added");
      setCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteKnowledge(id),
    onSuccess: () => {
      toast.success("Knowledge item deleted");
      queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  function confirmDelete(item: KnowledgeItemOut) {
    if (window.confirm(`Delete "${item.title}"? This cannot be undone.`)) {
      remove.mutate(item.id);
    }
  }

  const items = list.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Knowledge base</h1>
          <p className="text-muted-foreground">
            Reference material the writer agent retrieves from when personalizing drafts. Case
            studies, testimonials, and product proof points.
          </p>
        </div>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              Add item
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>Add knowledge item</DialogTitle>
              <DialogDescription>
                The item is chunked and embedded so the writer agent can pull the most relevant
                snippets for each lead.
              </DialogDescription>
            </DialogHeader>
            <KnowledgeForm
              submitLabel="Add"
              onCancel={() => setCreateOpen(false)}
              onSubmit={(values) => create.mutate(values)}
            />
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-4 w-4" />
            Items
          </CardTitle>
          <CardDescription>
            {list.isLoading
              ? "Loading…"
              : `${list.data?.total ?? items.length} item${
                  (list.data?.total ?? items.length) === 1 ? "" : "s"
                }`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No knowledge items yet. Add case studies to ground the writer agent.
            </p>
          )}
          {items.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Chunks</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="w-24 text-right" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((k) => (
                  <TableRow
                    key={k.id}
                    className="cursor-pointer"
                    onClick={() => setViewing(k)}
                  >
                    <TableCell className="font-medium">{k.title}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{k.source}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {k.chunk_count}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(k.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          confirmDelete(k);
                        }}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ViewDialog
        item={viewing}
        open={viewing !== null}
        onOpenChange={(o) => !o && setViewing(null)}
      />
    </div>
  );
}
