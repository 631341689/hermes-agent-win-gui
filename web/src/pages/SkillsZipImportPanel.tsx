import { useEffect, useState } from "react";
import { FileArchive } from "lucide-react";
import { api } from "@/lib/api";
import type { SkillZipInstallResponse } from "@/lib/api";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

const MCP_MOCK = import.meta.env.VITE_MCP_MOCK === "1";

const CATEGORY_ROOT = "";
const CATEGORY_CUSTOM = "__custom__";

export interface SkillsZipImportPanelProps {
  showToast: (message: string, type: "success" | "error") => void;
  onSkillsChanged?: () => void;
}

/** Standalone Skills page section: ZIP → ``POST /api/skills/install-zip``. */
export function SkillsZipImportPanel({ showToast, onSkillsChanged }: SkillsZipImportPanelProps) {
  const { t } = useI18n();
  const m = t.skillsMcp;
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [categoryChoice, setCategoryChoice] = useState(CATEGORY_ROOT);
  const [categoryCustom, setCategoryCustom] = useState("");
  const [knownCategories, setKnownCategories] = useState<string[]>([]);
  const [nameOverride, setNameOverride] = useState("");
  const [force, setForce] = useState(false);
  const [invalidateCache, setInvalidateCache] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [lastResult, setLastResult] = useState<SkillZipInstallResponse | null>(null);

  useEffect(() => {
    void api
      .getSkillCategories()
      .then((r) => setKnownCategories(Array.isArray(r.categories) ? r.categories : []))
      .catch(() => setKnownCategories([]));
  }, []);

  const resolvedCategory = () => {
    if (categoryChoice === CATEGORY_CUSTOM) return categoryCustom.trim();
    return categoryChoice.trim();
  };

  const submit = async () => {
    if (!zipFile) {
      showToast(m.skillZipNeedFile, "error");
      return;
    }
    setUploading(true);
    setLastResult(null);
    try {
      const fd = new FormData();
      fd.append("file", zipFile);
      fd.append("category", resolvedCategory());
      fd.append("name", nameOverride.trim());
      fd.append("force", force ? "true" : "false");
      fd.append("invalidate_cache", invalidateCache ? "true" : "false");
      const res = await api.installSkillZip(fd);
      setLastResult(res);
      if (!res.ok) {
        showToast(res.detail ?? res.blocked_reason ?? "ZIP install failed", "error");
        return;
      }
      showToast(m.skillZipSuccess, "success");
      onSkillsChanged?.();
    } catch (e) {
      showToast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Card>
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-sm flex items-center gap-2">
          <FileArchive className="h-4 w-4" />
          {m.skillZipTitle}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4 space-y-3">
        {MCP_MOCK && (
          <p className="text-xs text-amber-200/90 border border-amber-500/30 bg-amber-500/10 px-3 py-2 rounded-md">
            {m.skillZipMockNote}
          </p>
        )}
        <p className="text-xs text-muted-foreground leading-relaxed">{m.skillZipHint}</p>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">{m.skillZipPick}</label>
          <Input
            type="file"
            accept=".zip,application/zip"
            className="h-9 text-xs cursor-pointer"
            disabled={uploading}
            onChange={(e) => {
              const f = e.target.files?.[0];
              setZipFile(f ?? null);
              setLastResult(null);
            }}
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">{m.skillZipCategory}</label>
          <select
            className={cn(
              "flex h-9 w-full border border-border bg-background/40 px-3 py-1 font-courier text-xs transition-colors",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30 focus-visible:border-foreground/25",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
            value={categoryChoice}
            onChange={(e) => setCategoryChoice(e.target.value)}
            disabled={uploading}
            aria-label={m.skillZipCategory}
          >
            <option value={CATEGORY_ROOT}>{m.skillZipCategoryRoot}</option>
            {knownCategories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
            <option value={CATEGORY_CUSTOM}>{m.skillZipCategoryOther}</option>
          </select>
          {categoryChoice === CATEGORY_CUSTOM && (
            <Input
              className="h-8 text-xs font-mono mt-1.5"
              placeholder={m.skillZipCategoryCustomPh}
              value={categoryCustom}
              onChange={(e) => setCategoryCustom(e.target.value)}
              disabled={uploading}
            />
          )}
          <p className="text-[10px] text-muted-foreground leading-snug pt-0.5">{m.skillZipCategoryHint}</p>
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">{m.skillZipName}</label>
          <Input
            className="h-8 text-xs font-mono"
            placeholder="my-skill"
            value={nameOverride}
            onChange={(e) => setNameOverride(e.target.value)}
            disabled={uploading}
          />
        </div>
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            disabled={uploading}
            className="rounded border-border"
          />
          {m.skillZipForce}
        </label>
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <input
            type="checkbox"
            checked={invalidateCache}
            onChange={(e) => setInvalidateCache(e.target.checked)}
            disabled={uploading}
            className="rounded border-border"
          />
          {m.skillZipInvalidateCache}
        </label>
        <Button
          size="sm"
          type="button"
          disabled={uploading || !zipFile}
          onClick={() => void submit()}
          className="!inline-flex !flex-row items-center justify-center gap-2"
        >
          {uploading ? m.skillZipUploading : m.skillZipSubmit}
        </Button>
        {lastResult && (
          <div className="rounded-md border border-border/70 bg-muted/15 px-3 py-2 text-xs space-y-2 font-mono-ui">
            <p className="text-muted-foreground font-medium">{m.skillZipScanTitle}</p>
            {lastResult.installed_path && (
              <p>
                <span className="text-muted-foreground">path:</span> {lastResult.installed_path}
              </p>
            )}
            {lastResult.scan && (
              <>
                <p>
                  verdict: {lastResult.scan.verdict} · findings: {lastResult.scan.findings_count}
                </p>
                {lastResult.scan.report_lines && lastResult.scan.report_lines.length > 0 && (
                  <pre className="whitespace-pre-wrap text-[10px] max-h-40 overflow-y-auto opacity-90">
                    {lastResult.scan.report_lines.slice(0, 40).join("\n")}
                  </pre>
                )}
              </>
            )}
            {lastResult.reload_hint && (
              <p className="text-muted-foreground whitespace-pre-wrap">{lastResult.reload_hint}</p>
            )}
            {!lastResult.ok && lastResult.blocked_reason && (
              <p className="text-destructive/90">{lastResult.blocked_reason}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
