"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload } from "lucide-react";
import { api, type ImportPreviewOut, type ImportResultOut } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

const FIELD_LABELS: Record<string, string> = {
  email: "Email",
  first_name: "First name",
  last_name: "Last name",
  full_name: "Full name",
  company_name: "Company",
  title: "Job title",
  domain: "Website / domain",
  linkedin_url: "LinkedIn URL",
  country: "Country",
  industry: "Industry",
  company_size: "Company size",
};

/**
 * Two-step CSV import: upload, then confirm the column mapping.
 *
 * The confirmation step is deliberate. Guessing wrong across thousands of rows
 * is far more expensive to undo than one extra click, so we show what we think
 * each column means and let the user correct it before anything is written.
 */
export function LeadImportDialog() {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreviewOut | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ImportResultOut | null>(null);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setMapping({});
    setResult(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const close = () => {
    setOpen(false);
    reset();
  };

  const doPreview = useMutation({
    mutationFn: (f: File) => api.previewLeadImport(f),
    onSuccess: (data) => {
      setPreview(data);
      setMapping(data.suggested_mapping);
    },
    onError: (e: Error) => {
      toast.error(e.message);
      reset();
    },
  });

  const doImport = useMutation({
    mutationFn: () => api.importLeads(file!, mapping),
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      queryClient.invalidateQueries({ queryKey: ["onboarding"] });
      if (data.imported > 0) {
        toast.success(`Imported ${data.imported} lead${data.imported === 1 ? "" : "s"}`);
      } else {
        toast.info("Nothing new to import");
      }
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    setResult(null);
    doPreview.mutate(f);
  };

  const mappedFields = new Set(Object.values(mapping).filter(Boolean));
  const canImport = mappedFields.has("email") || mappedFields.has("domain");

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Upload className="mr-2 h-4 w-4" aria-hidden="true" />
        Import CSV
      </Button>

      <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : close())}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Import leads</DialogTitle>
            <DialogDescription>
              Upload a CSV export from your CRM, Apollo, Sales Navigator, or a
              plain spreadsheet. We&apos;ll match the columns and you can correct
              anything we get wrong.
            </DialogDescription>
          </DialogHeader>

          {/* Step 3: outcome */}
          {result ? (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Badge>{result.imported} imported</Badge>
                {result.duplicates > 0 && (
                  <Badge variant="secondary">{result.duplicates} already existed</Badge>
                )}
                {result.skipped > 0 && (
                  <Badge variant="outline">{result.skipped} skipped</Badge>
                )}
              </div>
              {result.problems.length > 0 && (
                <div className="max-h-48 overflow-y-auto rounded-md border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="px-3 py-1 text-left font-medium">Row</th>
                        <th className="px-3 py-1 text-left font-medium">Why it was skipped</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.problems.map((p) => (
                        <tr key={p.row_number} className="border-t">
                          <td className="px-3 py-1 text-muted-foreground">{p.row_number}</td>
                          <td className="px-3 py-1">{p.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <DialogFooter>
                <Button variant="outline" onClick={reset}>
                  Import another file
                </Button>
                <Button onClick={close}>Done</Button>
              </DialogFooter>
            </div>
          ) : preview ? (
            /* Step 2: confirm the mapping */
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {preview.total_rows.toLocaleString()} rows found
                {preview.truncated &&
                  ` — only the first ${preview.max_rows.toLocaleString()} will be imported`}
                .
              </p>
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {preview.headers.map((header) => (
                  <div key={header} className="grid grid-cols-2 items-center gap-2">
                    <div className="min-w-0">
                      <Label className="block truncate" title={header}>
                        {header}
                      </Label>
                      <p
                        className="truncate text-xs text-muted-foreground"
                        title={preview.sample_rows[0]?.[header] ?? ""}
                      >
                        {preview.sample_rows[0]?.[header] || "—"}
                      </p>
                    </div>
                    <select
                      className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm"
                      value={mapping[header] ?? ""}
                      onChange={(e) =>
                        setMapping((m) => {
                          const next = { ...m };
                          if (e.target.value) next[header] = e.target.value;
                          else delete next[header];
                          return next;
                        })
                      }
                    >
                      <option value="">Don&apos;t import</option>
                      {preview.importable_fields.map((f) => (
                        <option
                          key={f}
                          value={f}
                          // A field can only come from one column.
                          disabled={mapping[header] !== f && mappedFields.has(f)}
                        >
                          {FIELD_LABELS[f] ?? f}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
              {!canImport && (
                <p className="text-sm text-destructive">
                  Map a column to Email or Website — without one, a lead
                  can&apos;t be contacted or enriched.
                </p>
              )}
              <DialogFooter>
                <Button variant="outline" onClick={reset}>
                  Choose a different file
                </Button>
                <Button
                  onClick={() => doImport.mutate()}
                  disabled={!canImport || doImport.isPending}
                >
                  {doImport.isPending
                    ? "Importing…"
                    : `Import ${preview.total_rows.toLocaleString()} rows`}
                </Button>
              </DialogFooter>
            </div>
          ) : (
            /* Step 1: pick a file */
            <div className="space-y-3">
              <Label htmlFor="lead-csv">CSV file</Label>
              <input
                id="lead-csv"
                ref={fileRef}
                type="file"
                accept=".csv,text/csv"
                onChange={onPick}
                className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:text-primary-foreground"
              />
              {doPreview.isPending && (
                <p className="text-sm text-muted-foreground">Reading file…</p>
              )}
              <p className="text-xs text-muted-foreground">
                Needs a header row and at least an email or website column.
                Duplicates of leads you already have are skipped automatically.
              </p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
