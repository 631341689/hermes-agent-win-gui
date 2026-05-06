import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  ChevronDown,
  ChevronUp,
  Database,
  FileText,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { H2 } from "@/components/NouiTypography";
import {
  api,
  KnowledgeReindexUserCancelled,
  reindexKnowledgeBaseWithStream,
  uploadKnowledgeBaseFile,
  type KnowledgeUploadStreamEvent,
} from "@/lib/api";
import type {
  KnowledgeBase,
  KnowledgeChunkConfig,
  KnowledgeChunkStrategy,
  KnowledgeQueryHit,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { DeleteConfirmDialog } from "@/components/DeleteConfirmDialog";
import { useToast } from "@/hooks/useToast";
import { useConfirmDelete } from "@/hooks/useConfirmDelete";
import { Toast } from "@/components/Toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/i18n";
import type { Translations } from "@/i18n/types";
import { PluginSlot } from "@/plugins";
import { useKnowledgeTasks } from "@/contexts/KnowledgeTasksContext";
import { useKnowledgeProgressLabels } from "@/contexts/knowledgeProgressLabels";

type SummaryRoutingMode = "manual" | "auto";

function queryDebugKbLabel(b: KnowledgeBase, kp: Translations["knowledgePage"]): string {
  const kind = b.mode === "vector" ? kp.queryKbKindChunk : kp.queryKbKindGraphrag;
  return `${kind} · ${b.name}`;
}

function normalizeSummaryRoutingMode(m: string | undefined | null): SummaryRoutingMode {
  return m === "manual" ? "manual" : "auto";
}

type LocalChunkForm = {
  strategy: KnowledgeChunkStrategy;
  sizeTokens: number;
  overlapTokens: number;
  delimiterLines: string;
  mergeUnderChars: number;
  semanticMode: "pack" | "embedding";
  overlapSentences: number;
  similarityThreshold: number;
  maxChunkChars: string;
  smartOverlapChars: string;
};

const DEFAULT_DELIMITER_LINES = ["\\n\\n", "\\n", "。", ". "].join("\n");

/** Persist gentle UX hints per kb_id (upload / first successful index). */
const LS_KB_UPLOADED = "hermes.kb.uploaded.";
const LS_KB_INDEXED = "hermes.kb.indexedOnce.";
function lsMarkUploaded(kbId: string) {
  try {
    localStorage.setItem(LS_KB_UPLOADED + kbId, "1");
  } catch {
    /* ignore */
  }
}
function lsMarkIndexed(kbId: string) {
  try {
    localStorage.setItem(LS_KB_INDEXED + kbId, "1");
  } catch {
    /* ignore */
  }
}
function lsHasUploaded(kbId: string): boolean {
  try {
    return localStorage.getItem(LS_KB_UPLOADED + kbId) === "1";
  } catch {
    return false;
  }
}
function lsHasIndexedOnce(kbId: string): boolean {
  try {
    return localStorage.getItem(LS_KB_INDEXED + kbId) === "1";
  } catch {
    return false;
  }
}

function lsClearKbUploadIndexedHints(kbId: string) {
  try {
    localStorage.removeItem(LS_KB_UPLOADED + kbId);
    localStorage.removeItem(LS_KB_INDEXED + kbId);
  } catch {
    /* ignore */
  }
}

function kbToLocalForm(kb: KnowledgeBase): LocalChunkForm {
  const c = kb.chunk_config;
  const seps = c?.delimiter?.separators;
  const delimLines =
    seps && seps.length
      ? seps.map((s) => s.replace(/\n/g, "\\n").replace(/\t/g, "\\t")).join("\n")
      : DEFAULT_DELIMITER_LINES;
  const strat = (c?.strategy as KnowledgeChunkStrategy) ?? "window";
  const maxD = c?.delimiter?.max_chunk_chars;
  const maxS = c?.semantic?.max_chunk_chars;
  const maxSm = c?.smart?.max_chunk_chars;
  let maxStr = "";
  if (strat === "delimiter" && maxD != null && maxD !== undefined) maxStr = String(maxD);
  else if (strat === "semantic" && maxS != null && maxS !== undefined) maxStr = String(maxS);
  else if (strat === "smart" && maxSm != null && maxSm !== undefined) maxStr = String(maxSm);
  const soc = c?.smart?.overlap_chars;
  return {
    strategy: strat,
    sizeTokens: c?.size_tokens ?? 512,
    overlapTokens: c?.overlap_tokens ?? 64,
    delimiterLines: delimLines,
    mergeUnderChars: c?.delimiter?.merge_under_chars ?? 40,
    semanticMode: (c?.semantic?.mode as "pack" | "embedding") ?? "pack",
    overlapSentences: c?.semantic?.overlap_sentences ?? 0,
    similarityThreshold: c?.semantic?.similarity_threshold ?? 0.55,
    maxChunkChars: maxStr,
    smartOverlapChars: soc != null && soc !== undefined ? String(soc) : "",
  };
}

function localFormToPayload(f: LocalChunkForm): KnowledgeChunkConfig {
  const out: KnowledgeChunkConfig = {
    strategy: f.strategy,
    size_tokens: Math.max(1, Math.floor(Number(f.sizeTokens) || 512)),
    overlap_tokens: Math.max(0, Math.floor(Number(f.overlapTokens) || 0)),
  };
  if (f.strategy === "delimiter") {
    const separators = f.delimiterLines
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => line.replace(/\\n/g, "\n").replace(/\\t/g, "\t"));
    out.delimiter = {
      separators: separators.length ? separators : ["\n\n", "\n"],
      merge_under_chars: Math.max(0, Math.floor(Number(f.mergeUnderChars) || 0)),
    };
    const mc = f.maxChunkChars.trim();
    if (mc) out.delimiter!.max_chunk_chars = Math.max(64, Number(mc));
  }
  if (f.strategy === "semantic") {
    out.semantic = {
      mode: f.semanticMode,
      overlap_sentences: Math.max(0, Math.min(8, Math.floor(Number(f.overlapSentences) || 0))),
      similarity_threshold: Math.max(
        0,
        Math.min(1, Number(f.similarityThreshold) || 0),
      ),
    };
    const mc = f.maxChunkChars.trim();
    if (mc) out.semantic!.max_chunk_chars = Math.max(64, Number(mc));
  }
  if (f.strategy === "smart") {
    out.smart = {};
    const mc = f.maxChunkChars.trim();
    if (mc) out.smart.max_chunk_chars = Math.max(64, Number(mc));
    const oc = f.smartOverlapChars.trim();
    if (oc) out.smart.overlap_chars = Math.max(0, Math.floor(Number(oc)));
  }
  return out;
}

const STATUS_TONE: Record<
  KnowledgeBase["indexing_status"],
  "secondary" | "warning" | "success" | "destructive"
> = {
  idle: "secondary",
  indexing: "warning",
  ready: "success",
  error: "destructive",
};

function statusLabel(
  s: KnowledgeBase["indexing_status"],
  t: Translations,
): string {
  switch (s) {
    case "idle":
      return t.knowledgePage.statusIdle;
    case "indexing":
      return t.knowledgePage.statusIndexing;
    case "ready":
      return t.knowledgePage.statusReady;
    case "error":
      return t.knowledgePage.statusError;
    default:
      return s;
  }
}

export default function KnowledgePage() {
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [newBaseSummary, setNewBaseSummary] = useState("");
  const [summaryDialogKb, setSummaryDialogKb] = useState<KnowledgeBase | null>(null);
  const [summaryDialogMode, setSummaryDialogMode] = useState<SummaryRoutingMode>("auto");
  const [summaryDialogDraft, setSummaryDialogDraft] = useState("");
  const [summaryDialogSaving, setSummaryDialogSaving] = useState(false);
  const [mode, setMode] = useState<"vector" | "graphrag">("vector");
  const [createSummaryMode, setCreateSummaryMode] = useState<SummaryRoutingMode>("auto");
  const [creating, setCreating] = useState(false);
  const [embedInput, setEmbedInput] = useState("测试文本");
  const [embedResult, setEmbedResult] = useState("");
  const [queryKbId, setQueryKbId] = useState("");
  const [queryText, setQueryText] = useState("");
  const [queryGraphragMethod, setQueryGraphragMethod] = useState<"local" | "global" | "basic">("local");
  const [queryHits, setQueryHits] = useState<KnowledgeQueryHit[] | null>(null);
  const [kbUxHints, setKbUxHints] = useState<
    Record<string, { uploaded: boolean; indexedOnce: boolean }>
  >({});
  const [chunkForms, setChunkForms] = useState<Record<string, LocalChunkForm>>({});
  const [chunkPanelKbId, setChunkPanelKbId] = useState<string | null>(null);
  const [appendPanelKbId, setAppendPanelKbId] = useState<string | null>(null);
  const replaceFileRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const appendFileRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const { toast, showToast } = useToast();
  const { t } = useI18n();
  const {
    uploadOverlay,
    reindexOverlay,
    setUploadOverlay,
    setReindexOverlay,
    setQueryWait,
    reindexAbortRef,
    queryAbortRef,
    queryWait,
    registerTaskHooks,
  } = useKnowledgeTasks();
  const { reindexPhaseLabel } = useKnowledgeProgressLabels();

  /** Chunked (vector) bases first, then GraphRAG — `Select` labels must be plain strings (see UI Select). */
  const queryBasesOrdered = useMemo(() => {
    const v = bases.filter((b) => b.mode === "vector");
    const g = bases.filter((b) => b.mode === "graphrag");
    return [...v, ...g];
  }, [bases]);

  const loadBases = useCallback(() => {
    api
      .listKnowledgeBases()
      .then((r) => {
        setBases(r.bases);
        const hints: Record<string, { uploaded: boolean; indexedOnce: boolean }> = {};
        for (const b of r.bases) {
          if (b.indexing_status === "ready") {
            lsMarkIndexed(b.id);
          }
          hints[b.id] = {
            uploaded: lsHasUploaded(b.id),
            /** Server `ready` means at least one successful index — align button label immediately */
            indexedOnce: lsHasIndexedOnce(b.id) || b.indexing_status === "ready",
          };
        }
        setKbUxHints(hints);
        setSummaryDialogKb((cur) => {
          if (!cur) return null;
          return r.bases.find((b) => b.id === cur.id) ?? null;
        });
        const cf: Record<string, LocalChunkForm> = {};
        for (const b of r.bases) cf[b.id] = kbToLocalForm(b);
        setChunkForms(cf);
      })
      .catch(() => showToast(t.common.loading, "error"))
      .finally(() => setLoading(false));
  }, [showToast, t.common.loading]);

  useEffect(() => {
    loadBases();
  }, [loadBases]);

  useEffect(() => {
    registerTaskHooks(showToast, loadBases);
    return () => registerTaskHooks(null, null);
  }, [registerTaskHooks, showToast, loadBases]);

  useEffect(() => {
    const ids = new Set(bases.map((b) => b.id));
    if (queryKbId && ids.has(queryKbId)) return;
    const firstVec = bases.find((b) => b.mode === "vector");
    const firstGr = bases.find((b) => b.mode === "graphrag");
    setQueryKbId(firstVec?.id ?? firstGr?.id ?? "");
  }, [bases, queryKbId]);

  const handleCreate = async () => {
    if (!name.trim()) {
      showToast(t.knowledgePage.nameRequired, "error");
      return;
    }
    setCreating(true);
    try {
      const sum = createSummaryMode === "manual" ? newBaseSummary.trim() : "";
      await api.createKnowledgeBase({
        name: name.trim(),
        mode,
        agent_summary: sum.length ? sum : undefined,
        summary_routing_mode: createSummaryMode,
      });
      showToast(t.knowledgePage.created, "success");
      setName("");
      setNewBaseSummary("");
      setCreateSummaryMode("auto");
      setMode("vector");
      loadBases();
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  const handleUpload = async (kb: KnowledgeBase, fileList: FileList | null) => {
    const file = fileList?.[0];
    if (!file) return;
    const isPdf = file.name.toLowerCase().endsWith(".pdf");
    setUploadOverlay({
      kbId: kb.id,
      kbName: kb.name,
      fileName: file.name,
      isPdf,
      phase: "starting",
      startedAt: Date.now(),
      detail: null,
      minimized: false,
    });
    try {
      await uploadKnowledgeBaseFile(kb.id, file, (ev: KnowledgeUploadStreamEvent) => {
        if (ev.event === "saved") {
          setUploadOverlay((o) => (o ? { ...o, phase: "saved" } : null));
        }
        if (ev.event === "progress") {
          const err = typeof ev.error === "string" ? ev.error : null;
          setUploadOverlay((o) =>
            o
              ? {
                  ...o,
                  phase: ev.phase,
                  detail: err ?? o.detail,
                }
              : null,
          );
        }
        if (ev.event === "heartbeat") {
          setUploadOverlay((o) => {
            if (!o) return null;
            if (o.phase === "starting") return { ...o, phase: "working" };
            return o;
          });
        }
      });
      lsMarkUploaded(kb.id);
      setKbUxHints((prev) => ({
        ...prev,
        [kb.id]: { ...prev[kb.id], uploaded: true, indexedOnce: prev[kb.id]?.indexedOnce ?? false },
      }));
      showToast(t.knowledgePage.uploadOk, "success");
      loadBases();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    } finally {
      setUploadOverlay(null);
    }
  };

  const triggerReplaceUpload = useCallback(
    async (kb: KnowledgeBase, hasUploaded: boolean) => {
      if (hasUploaded) {
        try {
          await api.clearKnowledgeRaw(kb.id);
          lsClearKbUploadIndexedHints(kb.id);
          setKbUxHints((prev) => ({
            ...prev,
            [kb.id]: { uploaded: false, indexedOnce: false },
          }));
          loadBases();
          showToast(t.knowledgePage.rawClearedForReplace, "success");
        } catch (e) {
          showToast(`${t.status.error}: ${e}`, "error");
          return;
        }
      }
      replaceFileRefs.current[kb.id]?.click();
    },
    [loadBases, showToast, t.knowledgePage.rawClearedForReplace, t.status.error],
  );

  const handleReindex = async (
    kb: KnowledgeBase,
    opts?: { graphragForceFull?: boolean },
  ) => {
    const ac = new AbortController();
    reindexAbortRef.current = ac;
    setReindexOverlay({
      kbId: kb.id,
      kbName: kb.name,
      kbMode: kb.mode,
      phase: "starting",
      line: t.knowledgePage.reindexPhaseStarting,
      startedAt: Date.now(),
      minimized: false,
    });
    const streamOpts: { signal: AbortSignal; graphragForceFull?: boolean } = {
      signal: ac.signal,
    };
    if (kb.mode === "graphrag") {
      streamOpts.graphragForceFull = opts?.graphragForceFull ?? true;
    }
    try {
      const res = await reindexKnowledgeBaseWithStream(
        kb.id,
        (ev) => {
          if (ev.event === "progress") {
            const line = reindexPhaseLabel(ev);
            setReindexOverlay((o) => {
              if (!o) return null;
              let graphrag = o.graphrag;
              if (ev.phase === "graphrag") {
                const ge = ev.graphrag_event;
                if (ge === "pipeline_start" && ev.workflows && ev.workflows.length > 0) {
                  graphrag = {
                    steps: ev.workflows,
                    completedWorkflows: [],
                    activeWorkflow: null,
                    subLine: null,
                  };
                } else if (ge === "workflow_start" && graphrag) {
                  const active = ev.active_workflow ?? ev.workflow ?? null;
                  graphrag = {
                    ...graphrag,
                    activeWorkflow: active,
                    subLine: null,
                  };
                } else if (ge === "workflow_end" && graphrag) {
                  const cw =
                    ev.completed_workflows ??
                    (ev.workflow && !graphrag.completedWorkflows.includes(ev.workflow)
                      ? [...graphrag.completedWorkflows, ev.workflow]
                      : graphrag.completedWorkflows);
                  graphrag = {
                    ...graphrag,
                    completedWorkflows: cw,
                    activeWorkflow: null,
                  };
                } else if (ge === "subprogress" && graphrag) {
                  const d = ev.subprogress_description ?? "";
                  const c = ev.subprogress_current;
                  const tot = ev.subprogress_total;
                  let subLine: string | null = null;
                  if (d && c != null && tot != null) {
                    subLine = t.knowledgePage.reindexGraphragSubprogress.replace("{{desc}}", d).replace("{{cur}}", String(c)).replace("{{tot}}", String(tot));
                  } else if (d) {
                    subLine = d;
                  }
                  graphrag = { ...graphrag, subLine };
                } else if (ge === "pipeline_end" && graphrag) {
                  graphrag = {
                    ...graphrag,
                    completedWorkflows: ev.completed_workflows ?? graphrag.steps,
                    activeWorkflow: null,
                    subLine: null,
                  };
                }
              }
              return { ...o, phase: ev.phase, line: line || o.line, graphrag };
            });
          }
          if (ev.event === "heartbeat") {
            setReindexOverlay((o) => {
              if (!o || o.phase !== "starting") return o;
              return { ...o, line: t.knowledgePage.reindexWorking };
            });
          }
        },
        streamOpts,
      );
      const n = res.stats?.chunk_count;
      lsMarkIndexed(kb.id);
      setBases((prev) => prev.map((b) => (b.id === kb.id ? res.base : b)));
      setKbUxHints((prev) => ({
        ...prev,
        [kb.id]: {
          ...prev[kb.id],
          indexedOnce: true,
          uploaded: prev[kb.id]?.uploaded ?? lsHasUploaded(kb.id),
        },
      }));
      if (typeof n === "number") {
        showToast(`${t.common.refresh} — ${t.knowledgePage.reindexedChunks}: ${n}`, "success");
      } else {
        showToast(t.common.refresh, "success");
      }
      loadBases();
    } catch (e: unknown) {
      if (e instanceof KnowledgeReindexUserCancelled) {
        showToast(t.knowledgePage.reindexStopped, "success");
        loadBases();
        return;
      }
      const msg = String(e);
      if (msg.includes("501")) {
        showToast(t.knowledgePage.reindexNotImplemented, "error");
      } else {
        showToast(`${t.status.error}: ${e}`, "error");
      }
    } finally {
      reindexAbortRef.current = null;
      setReindexOverlay(null);
    }
  };

  const handleTestEmbed = async () => {
    const s = embedInput.trim();
    if (!s) return;
    try {
      const r = await api.debugKnowledgeEmbedding(s);
      setEmbedResult(JSON.stringify(r, null, 2));
      showToast(t.knowledgePage.embedOk, "success");
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
      setEmbedResult("");
    }
  };

  const handleQuery = async () => {
    const q = queryText.trim();
    if (!queryKbId) {
      showToast(t.knowledgePage.queryNeedBase, "error");
      return;
    }
    if (!q) {
      showToast(t.knowledgePage.queryNeedInput, "error");
      return;
    }
    const picked = bases.find((b) => b.id === queryKbId);
    if (!picked) {
      showToast(t.knowledgePage.queryNeedBase, "error");
      return;
    }

    const ac = new AbortController();
    queryAbortRef.current = ac;
    setQueryWait({
      minimized: false,
      kbName: picked.name,
      mode: picked.mode,
      startedAt: Date.now(),
    });

    try {
      const r =
        picked.mode === "graphrag"
          ? await api.queryKnowledge(
              {
                kb_ids: [queryKbId],
                query: q,
                graphrag_method: queryGraphragMethod,
              },
              { signal: ac.signal },
            )
          : await api.queryKnowledge(
              { kb_ids: [queryKbId], query: q, top_k: 8 },
              { signal: ac.signal },
            );
      setQueryHits(r.results);
      showToast(t.knowledgePage.queryOk, "success");
    } catch (e: unknown) {
      const err = e as { name?: string };
      if (err?.name === "AbortError") {
        showToast(t.knowledgePage.queryCancelled, "success");
        return;
      }
      showToast(`${t.status.error}: ${e}`, "error");
      setQueryHits(null);
    } finally {
      queryAbortRef.current = null;
      setQueryWait(null);
    }
  };

  const patchChunkField = (kbId: string, patch: Partial<LocalChunkForm>) => {
    setChunkForms((prev) => {
      const cur = prev[kbId];
      if (!cur) return prev;
      return { ...prev, [kbId]: { ...cur, ...patch } };
    });
  };

  const openSummaryDialog = (kb: KnowledgeBase) => {
    setSummaryDialogKb(kb);
    setSummaryDialogMode(normalizeSummaryRoutingMode(kb.summary_routing_mode));
    setSummaryDialogDraft(kb.agent_summary ?? "");
  };

  const closeSummaryDialog = () => {
    if (summaryDialogSaving) return;
    setSummaryDialogKb(null);
  };

  const saveSummaryDialog = async () => {
    const kb = summaryDialogKb;
    if (!kb) return;
    setSummaryDialogSaving(true);
    try {
      if (summaryDialogMode === "manual") {
        const raw = summaryDialogDraft.trim();
        await api.patchKnowledgeBase(kb.id, {
          summary_routing_mode: "manual",
          agent_summary: raw.length ? raw : null,
        });
      } else {
        await api.patchKnowledgeBase(kb.id, {
          summary_routing_mode: "auto",
          agent_summary: null,
        });
      }
      showToast(t.knowledgePage.agentSummarySaved, "success");
      setSummaryDialogKb(null);
      loadBases();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    } finally {
      setSummaryDialogSaving(false);
    }
  };

  const handleSaveChunk = async (kb: KnowledgeBase) => {
    const form = chunkForms[kb.id] ?? kbToLocalForm(kb);
    try {
      await api.patchKnowledgeBase(kb.id, { chunk_config: localFormToPayload(form) });
      showToast(t.knowledgePage.chunkSaveOk, "success");
      loadBases();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const handleResetChunk = async (kb: KnowledgeBase) => {
    try {
      await api.patchKnowledgeBase(kb.id, { chunk_config: null });
      showToast(t.knowledgePage.chunkSaveOk, "success");
      loadBases();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const kbDelete = useConfirmDelete({
    onDelete: useCallback(
      async (id: string) => {
        const b = bases.find((x) => x.id === id);
        try {
          await api.deleteKnowledgeBase(id);
          showToast(
            `${t.common.delete}: "${b?.name ?? id}"`,
            "success",
          );
          loadBases();
        } catch (e) {
          showToast(`${t.status.error}: ${e}`, "error");
          throw e;
        }
      },
      [bases, loadBases, showToast, t.common.delete, t.status.error],
    ),
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="text-2xl text-primary" />
      </div>
    );
  }

  const pendingBase = kbDelete.pendingId
    ? bases.find((b) => b.id === kbDelete.pendingId)
    : null;

  return (
    <div className="flex flex-col gap-6">
      <PluginSlot name="knowledge:top" />
      <Toast toast={toast} />

      <DeleteConfirmDialog
        open={kbDelete.isOpen}
        onCancel={kbDelete.cancel}
        onConfirm={kbDelete.confirm}
        title={t.knowledgePage.confirmDeleteTitle}
        description={
          pendingBase
            ? `"${pendingBase.name}" — ${t.knowledgePage.confirmDeleteMessage}`
            : t.knowledgePage.confirmDeleteMessage
        }
        loading={kbDelete.isDeleting}
      />

      {summaryDialogKb &&
        createPortal(
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="kb-summary-dialog-title"
            className={cn(
              "fixed inset-0 z-[110] flex items-center justify-center",
              "bg-black/60 backdrop-blur-sm",
            )}
            onClick={() => {
              if (!summaryDialogSaving) closeSummaryDialog();
            }}
          >
            <div
              className="relative mx-4 w-full max-w-lg border border-border bg-card p-4 shadow-lg"
              onClick={(e) => e.stopPropagation()}
            >
              <h2
                id="kb-summary-dialog-title"
                className="font-expanded text-sm font-bold tracking-[0.08em] uppercase blend-lighter"
              >
                {t.knowledgePage.summaryDialogTitle}
              </h2>
              <p className="mt-1 truncate text-sm text-muted-foreground">{summaryDialogKb.name}</p>

              <div className="mt-4 grid gap-2">
                <Label className="text-xs">{t.knowledgePage.summaryRoutingModeLabel}</Label>
                <Select
                  value={summaryDialogMode}
                  onValueChange={(v) => {
                    const m = v as SummaryRoutingMode;
                    setSummaryDialogMode(m);
                    if (m === "auto") {
                      setSummaryDialogDraft("");
                    } else {
                      setSummaryDialogDraft(summaryDialogKb.agent_summary ?? "");
                    }
                  }}
                >
                  <SelectOption value="manual">{t.knowledgePage.summaryRoutingManual}</SelectOption>
                  <SelectOption value="auto">{t.knowledgePage.summaryRoutingAuto}</SelectOption>
                </Select>
              </div>

              {summaryDialogMode === "manual" ? (
                <div className="mt-4 grid gap-1">
                  <Label className="text-xs">{t.knowledgePage.agentSummaryLabel}</Label>
                  <p className="text-xs text-muted-foreground">{t.knowledgePage.agentSummaryHint}</p>
                  <textarea
                    className={cn(
                      "min-h-[96px] w-full rounded-md border border-border bg-background/40 px-3 py-2 text-sm",
                      "placeholder:text-muted-foreground",
                      "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30",
                    )}
                    placeholder={t.knowledgePage.agentSummaryPlaceholder}
                    value={summaryDialogDraft}
                    onChange={(e) => setSummaryDialogDraft(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">{t.knowledgePage.routingSummaryHiddenManual}</p>
                </div>
              ) : (
                <div className="mt-4 grid gap-2">
                  <p className="text-xs text-muted-foreground">{t.knowledgePage.routingSummaryAutoNote}</p>
                  <Label className="text-xs text-muted-foreground">
                    {t.knowledgePage.routingSummaryReadonly}
                  </Label>
                  {summaryDialogKb.routing_summary ? (
                    <p className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md border border-dashed border-border bg-muted/20 p-2 text-xs leading-relaxed">
                      {summaryDialogKb.routing_summary}
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground">{t.knowledgePage.routingSummaryEmpty}</p>
                  )}
                </div>
              )}

              <div className="mt-4 flex justify-end gap-2">
                <Button type="button" outlined onClick={closeSummaryDialog} disabled={summaryDialogSaving}>
                  {t.common.cancel}
                </Button>
                <Button type="button" onClick={() => void saveSummaryDialog()} disabled={summaryDialogSaving}>
                  {summaryDialogSaving ? t.common.saving : t.common.save}
                </Button>
              </div>
            </div>
          </div>,
          document.body,
        )}

      <div className="flex flex-col gap-2">
        <H2 variant="sm" className="flex items-center gap-2">
          <Database className="h-5 w-5" />
          {t.knowledgePage.title}
        </H2>
        <p className="text-sm text-muted-foreground max-w-3xl">
          {t.knowledgePage.subtitle}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="h-4 w-4" />
            {t.knowledgePage.newBase}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <div className="grid gap-2 lg:col-span-2">
              <Label htmlFor="kb-name">{t.knowledgePage.nameLabel}</Label>
              <Input
                id="kb-name"
                placeholder={t.knowledgePage.namePlaceholder}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="kb-mode">{t.knowledgePage.modeLabel}</Label>
              <Select
                id="kb-mode"
                value={mode}
                onValueChange={(v) => setMode(v as "vector" | "graphrag")}
              >
                <SelectOption value="vector">
                  {t.knowledgePage.modeVector}
                </SelectOption>
                <SelectOption value="graphrag">
                  {t.knowledgePage.modeGraphrag}
                </SelectOption>
              </Select>
            </div>
            <div className="flex items-end">
              <Button
                onClick={handleCreate}
                disabled={creating}
                className="w-full"
                prefix={<Database />}
              >
                {creating ? t.common.creating : t.common.create}
              </Button>
            </div>
          </div>
          <div className="mt-4 grid gap-2 max-w-xl">
            <Label htmlFor="kb-summary-mode">{t.knowledgePage.summaryRoutingModeLabel}</Label>
            <Select
              id="kb-summary-mode"
              value={createSummaryMode}
              onValueChange={(v) => {
                const m = v as SummaryRoutingMode;
                setCreateSummaryMode(m);
                if (m === "auto") setNewBaseSummary("");
              }}
            >
              <SelectOption value="manual">{t.knowledgePage.summaryRoutingManual}</SelectOption>
              <SelectOption value="auto">{t.knowledgePage.summaryRoutingAuto}</SelectOption>
            </Select>
            <p className="text-xs text-muted-foreground">{t.knowledgePage.summaryRoutingHintCreate}</p>
          </div>
          {createSummaryMode === "manual" && (
            <div className="mt-4 grid gap-2">
              <Label htmlFor="kb-agent-summary-new">{t.knowledgePage.agentSummaryNewLabel}</Label>
              <p className="text-xs text-muted-foreground">{t.knowledgePage.agentSummaryNewHint}</p>
              <textarea
                id="kb-agent-summary-new"
                className={cn(
                  "min-h-[72px] w-full rounded-md border border-border bg-background/40 px-3 py-2 text-sm",
                  "placeholder:text-muted-foreground",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30",
                )}
                placeholder={t.knowledgePage.agentSummaryPlaceholder}
                value={newBaseSummary}
                onChange={(e) => setNewBaseSummary(e.target.value)}
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t.knowledgePage.toolsCard}</CardTitle>
        </CardHeader>
        <CardContent className="grid min-w-0 grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
          <div className="grid min-w-0 gap-2">
            <Label>{t.knowledgePage.embedTestLabel}</Label>
            <Input
              value={embedInput}
              onChange={(e) => setEmbedInput(e.target.value)}
            />
            <Button
              type="button"
              className="w-fit max-w-full justify-self-start"
              onClick={() => void handleTestEmbed()}
            >
              {t.knowledgePage.embedTestButton}
            </Button>
            {embedResult && (
              <pre className="max-h-40 min-w-0 overflow-auto break-words rounded border border-input bg-muted/30 p-2 text-xs whitespace-pre-wrap">
                {t.knowledgePage.embedTestResult}:{"\n"}
                {embedResult}
              </pre>
            )}
          </div>
          <div className="grid min-w-0 gap-2">
            <Label>{t.knowledgePage.queryLabel}</Label>
            <div className="grid min-w-0 gap-2 sm:grid-cols-2">
              <div className="grid gap-1">
                <span className="text-xs text-muted-foreground">
                  {t.knowledgePage.queryPickBase}
                </span>
                <Select
                  value={queryKbId}
                  onValueChange={(v) => setQueryKbId(v)}
                  disabled={bases.length === 0}
                  placeholder={t.knowledgePage.queryPickBase}
                >
                  {queryBasesOrdered.map((b) => (
                    <SelectOption key={b.id} value={b.id}>
                      {queryDebugKbLabel(b, t.knowledgePage)}
                    </SelectOption>
                  ))}
                </Select>
              </div>
              {bases.find((b) => b.id === queryKbId)?.mode === "graphrag" && (
                <div className="grid gap-1">
                  <span className="text-xs text-muted-foreground">
                    {t.knowledgePage.queryGraphragMethodLabel}
                  </span>
                  <Select
                    value={queryGraphragMethod}
                    onValueChange={(v) =>
                      setQueryGraphragMethod(v as "local" | "global" | "basic")
                    }
                  >
                    <SelectOption value="local">{t.knowledgePage.graphragMethodLocal}</SelectOption>
                    <SelectOption value="global">{t.knowledgePage.graphragMethodGlobal}</SelectOption>
                    <SelectOption value="basic">{t.knowledgePage.graphragMethodBasic}</SelectOption>
                  </Select>
                </div>
              )}
              <div className="grid gap-1 sm:col-span-2">
                <Input
                  placeholder={t.knowledgePage.queryPlaceholder}
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                />
              </div>
            </div>
            <Button
              type="button"
              className="w-fit max-w-full justify-self-start"
              disabled={queryWait != null}
              onClick={() => void handleQuery()}
            >
              {queryHits !== null
                ? t.knowledgePage.queryButtonAgain
                : t.knowledgePage.queryButton}
            </Button>
            {queryHits && queryHits.length > 0 && (
              <ul className="max-h-56 min-w-0 space-y-2 overflow-auto text-xs">
                {queryHits.map((h) => (
                  <li
                    key={`${h.kb_id}-${h.chunk_id ?? "graphrag"}-${h.graphrag_method ?? ""}`}
                    className="min-w-0 rounded border border-input p-2"
                  >
                    <div className="mb-1 min-w-0 break-words text-muted-foreground">
                      {h.kind === "graphrag" ? (
                        <>
                          GraphRAG · {h.graphrag_method ?? queryGraphragMethod}
                        </>
                      ) : (
                        <>
                          score={h.score != null ? h.score.toFixed(4) : "—"} ·{" "}
                          {h.source_path ?? "—"}
                        </>
                      )}
                    </div>
                    <div className="min-w-0 whitespace-pre-wrap break-words">{h.text}</div>
                  </li>
                ))}
              </ul>
            )}
            {queryHits && queryHits.length === 0 && (
              <p className="text-xs text-muted-foreground">{t.common.noResults}</p>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-3">
        <H2
          variant="sm"
          className="flex items-center gap-2 text-muted-foreground"
        >
          <Database className="h-4 w-4" />
          {t.knowledgePage.listHeading} ({bases.length})
        </H2>

        {bases.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {t.knowledgePage.empty}
            </CardContent>
          </Card>
        )}

        {bases.map((kb) => {
          const ux = kbUxHints[kb.id];
          const uploaded = ux?.uploaded ?? lsHasUploaded(kb.id);
          const indexedOnce =
            (ux?.indexedOnce ?? lsHasIndexedOnce(kb.id)) ||
            kb.indexing_status === "ready";
          const rowUploadLabel = uploaded ? t.knowledgePage.reuploadFile : t.knowledgePage.uploadFile;
          const rowIndexLabel = indexedOnce ? t.knowledgePage.reindex : t.knowledgePage.indexBuild;
          const kbUploadBusy = uploadOverlay?.kbId === kb.id;
          /** Include `recovering` so row actions stay off until poll finishes or user closes dock */
          const kbReindexBusy = reindexOverlay?.kbId === kb.id;
          const rowIndexDisabled =
            kb.indexing_status === "indexing" || kbUploadBusy || kbReindexBusy;
          const rowUploadDisabled =
            kb.indexing_status === "indexing" || kbUploadBusy || kbReindexBusy;
          return (
          <Card key={kb.id}>
            <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:gap-4">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-medium">{kb.name}</span>
                  <Badge tone="secondary" className="text-[0.65rem]">
                    {kb.mode === "vector"
                      ? t.knowledgePage.modeVector
                      : t.knowledgePage.modeGraphrag}
                  </Badge>
                  <Badge tone={STATUS_TONE[kb.indexing_status] ?? "secondary"}>
                    {statusLabel(kb.indexing_status, t)}
                  </Badge>
                </div>
                <p className="truncate font-mono text-xs text-muted-foreground">
                  {kb.id}
                </p>
                {kb.error_message && (
                  <p className="mt-1 text-xs text-destructive">{kb.error_message}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  {t.knowledgePage.uploadHint}
                </p>
                {kb.mode === "graphrag" && (
                  <p className="mt-1 text-[11px] leading-snug text-muted-foreground/90">
                    {t.knowledgePage.corpusReplaceTopHint}
                  </p>
                )}
                {kb.mode === "vector" && (
                  <div className="mt-2 space-y-2 border-t border-border pt-2">
                    <Button
                      ghost
                      size="sm"
                      type="button"
                      className="h-8 px-2 text-xs"
                      prefix={
                        chunkPanelKbId === kb.id ? (
                          <ChevronUp className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5" />
                        )
                      }
                      onClick={() => {
                        setChunkPanelKbId((id) => {
                          const next = id === kb.id ? null : kb.id;
                          if (next === kb.id) {
                            setChunkForms((prev) =>
                              prev[kb.id] ? prev : { ...prev, [kb.id]: kbToLocalForm(kb) },
                            );
                          }
                          return next;
                        });
                      }}
                    >
                      {t.knowledgePage.chunkToggle}
                    </Button>
                    {chunkPanelKbId === kb.id && (
                      <div className="grid gap-3 rounded-md border border-input bg-muted/20 p-3">
                        <p className="text-xs font-medium">{t.knowledgePage.chunkCardTitle}</p>
                        {(() => {
                          const form = chunkForms[kb.id] ?? kbToLocalForm(kb);
                          return (
                            <>
                              <div className="grid gap-1">
                                <Label className="text-xs">{t.knowledgePage.chunkStrategy}</Label>
                                <Select
                                  value={form.strategy}
                                  onValueChange={(v) =>
                                    patchChunkField(kb.id, {
                                      strategy: v as KnowledgeChunkStrategy,
                                    })
                                  }
                                >
                                  <SelectOption value="window">
                                    {t.knowledgePage.chunkStrategyWindow}
                                  </SelectOption>
                                  <SelectOption value="delimiter">
                                    {t.knowledgePage.chunkStrategyDelimiter}
                                  </SelectOption>
                                  <SelectOption value="semantic">
                                    {t.knowledgePage.chunkStrategySemantic}
                                  </SelectOption>
                                  <SelectOption value="smart">
                                    {t.knowledgePage.chunkStrategySmart}
                                  </SelectOption>
                                </Select>
                              </div>
                              <div className="grid gap-2 sm:grid-cols-2">
                                <div className="grid gap-1">
                                  <Label className="text-xs">{t.knowledgePage.chunkSizeTokens}</Label>
                                  <Input
                                    type="number"
                                    min={32}
                                    value={form.sizeTokens}
                                    onChange={(e) =>
                                      patchChunkField(kb.id, {
                                        sizeTokens: Number(e.target.value),
                                      })
                                    }
                                  />
                                </div>
                                <div className="grid gap-1">
                                  <Label className="text-xs">{t.knowledgePage.chunkOverlapTokens}</Label>
                                  <Input
                                    type="number"
                                    min={0}
                                    value={form.overlapTokens}
                                    onChange={(e) =>
                                      patchChunkField(kb.id, {
                                        overlapTokens: Number(e.target.value),
                                      })
                                    }
                                  />
                                </div>
                              </div>
                              {form.strategy === "delimiter" && (
                                <>
                                  <div className="grid gap-1">
                                    <Label className="text-xs">
                                      {t.knowledgePage.chunkDelimiterHint}
                                    </Label>
                                    <textarea
                                      className={cn(
                                        "min-h-[88px] w-full rounded-md border border-border bg-background/40 px-3 py-2 font-courier text-sm",
                                        "placeholder:text-muted-foreground",
                                        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30",
                                      )}
                                      value={form.delimiterLines}
                                      onChange={(e) =>
                                        patchChunkField(kb.id, { delimiterLines: e.target.value })
                                      }
                                    />
                                  </div>
                                  <div className="grid gap-1 sm:max-w-xs">
                                    <Label className="text-xs">{t.knowledgePage.chunkMergeUnder}</Label>
                                    <Input
                                      type="number"
                                      min={0}
                                      value={form.mergeUnderChars}
                                      onChange={(e) =>
                                        patchChunkField(kb.id, {
                                          mergeUnderChars: Number(e.target.value),
                                        })
                                      }
                                    />
                                  </div>
                                </>
                              )}
                              {form.strategy === "smart" && (
                                <p className="text-xs text-muted-foreground">{t.knowledgePage.chunkSmartHint}</p>
                              )}
                              {form.strategy === "semantic" && (
                                <>
                                  <div className="grid gap-1">
                                    <Label className="text-xs">{t.knowledgePage.chunkSemanticMode}</Label>
                                    <Select
                                      value={form.semanticMode}
                                      onValueChange={(v) =>
                                        patchChunkField(kb.id, {
                                          semanticMode: v as "pack" | "embedding",
                                        })
                                      }
                                    >
                                      <SelectOption value="pack">
                                        {t.knowledgePage.chunkSemanticPack}
                                      </SelectOption>
                                      <SelectOption value="embedding">
                                        {t.knowledgePage.chunkSemanticEmbedding}
                                      </SelectOption>
                                    </Select>
                                  </div>
                                  <div className="grid gap-2 sm:grid-cols-2">
                                    <div className="grid gap-1">
                                      <Label className="text-xs">
                                        {t.knowledgePage.chunkOverlapSentences}
                                      </Label>
                                      <Input
                                        type="number"
                                        min={0}
                                        max={8}
                                        value={form.overlapSentences}
                                        onChange={(e) =>
                                          patchChunkField(kb.id, {
                                            overlapSentences: Number(e.target.value),
                                          })
                                        }
                                      />
                                    </div>
                                    <div className="grid gap-1">
                                      <Label className="text-xs">
                                        {t.knowledgePage.chunkSimilarity}
                                      </Label>
                                      <Input
                                        type="number"
                                        step={0.05}
                                        min={0}
                                        max={1}
                                        disabled={form.semanticMode !== "embedding"}
                                        value={form.similarityThreshold}
                                        onChange={(e) =>
                                          patchChunkField(kb.id, {
                                            similarityThreshold: Number(e.target.value),
                                          })
                                        }
                                      />
                                    </div>
                                  </div>
                                </>
                              )}
                              {(form.strategy === "delimiter" ||
                                form.strategy === "semantic" ||
                                form.strategy === "smart") && (
                                <div className="grid gap-1 sm:max-w-xs">
                                  <Label className="text-xs">{t.knowledgePage.chunkMaxChars}</Label>
                                  <Input
                                    placeholder={t.knowledgePage.chunkMaxCharsHint}
                                    value={form.maxChunkChars}
                                    onChange={(e) =>
                                      patchChunkField(kb.id, { maxChunkChars: e.target.value })
                                    }
                                  />
                                </div>
                              )}
                              {form.strategy === "smart" && (
                                <div className="grid gap-1 sm:max-w-xs">
                                  <Label className="text-xs">{t.knowledgePage.chunkSmartOverlapChars}</Label>
                                  <Input
                                    type="number"
                                    min={0}
                                    placeholder=""
                                    value={form.smartOverlapChars}
                                    onChange={(e) =>
                                      patchChunkField(kb.id, { smartOverlapChars: e.target.value })
                                    }
                                  />
                                </div>
                              )}
                              <p className="text-xs text-muted-foreground">
                                {t.knowledgePage.chunkReindexHint}
                              </p>
                              <div className="flex flex-wrap gap-2">
                                <Button
                                  size="sm"
                                  type="button"
                                  onClick={() => void handleSaveChunk(kb)}
                                >
                                  {t.knowledgePage.chunkSave}
                                </Button>
                                <Button
                                  ghost
                                  size="sm"
                                  type="button"
                                  onClick={() => void handleResetChunk(kb)}
                                >
                                  {t.knowledgePage.chunkReset}
                                </Button>
                              </div>
                            </>
                          );
                        })()}
                      </div>
                    )}
                  </div>
                )}
                {kb.mode === "graphrag" && (
                  <div className="mt-2 space-y-2 border-t border-border pt-2">
                    <Button
                      ghost
                      size="sm"
                      type="button"
                      className="h-8 px-2 text-xs"
                      prefix={
                        appendPanelKbId === kb.id ? (
                          <ChevronUp className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5" />
                        )
                      }
                      onClick={() =>
                        setAppendPanelKbId((id) => (id === kb.id ? null : kb.id))
                      }
                    >
                      {t.knowledgePage.appendCorpusToggle}
                    </Button>
                    {appendPanelKbId === kb.id && (
                      <div className="grid gap-3 rounded-md border border-input bg-muted/20 p-3">
                        <p className="text-xs leading-relaxed text-muted-foreground">
                          {t.knowledgePage.appendCorpusHintGraphrag}
                        </p>
                        <div className="flex flex-wrap gap-2">
                          <input
                            ref={(el) => {
                              appendFileRefs.current[kb.id] = el;
                            }}
                            type="file"
                            className="hidden"
                            onChange={(e) => {
                              void handleUpload(kb, e.target.files);
                              e.target.value = "";
                            }}
                          />
                          <Button
                            size="sm"
                            type="button"
                            disabled={rowUploadDisabled}
                            prefix={<Plus className="h-3.5 w-3.5" />}
                            onClick={() => appendFileRefs.current[kb.id]?.click()}
                          >
                            {t.knowledgePage.appendUploadOnly}
                          </Button>
                          <Button
                            ghost
                            size="sm"
                            type="button"
                            disabled={rowIndexDisabled}
                            prefix={<RefreshCw className="h-3.5 w-3.5" />}
                            onClick={() =>
                              void handleReindex(kb, { graphragForceFull: false })
                            }
                          >
                            {t.knowledgePage.graphragIncrementalReindex}
                          </Button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={(el) => {
                    replaceFileRefs.current[kb.id] = el;
                  }}
                  type="file"
                  className="hidden"
                  onChange={(e) => {
                    void handleUpload(kb, e.target.files);
                    e.target.value = "";
                  }}
                />
                <Button
                  ghost
                  size="sm"
                  prefix={<FileText className="h-4 w-4" />}
                  onClick={() => openSummaryDialog(kb)}
                >
                  {t.knowledgePage.summarySettingsButton}
                </Button>
                <Button
                  ghost
                  size="sm"
                  prefix={<Upload className="h-4 w-4" />}
                  disabled={rowUploadDisabled}
                  onClick={() => void triggerReplaceUpload(kb, uploaded)}
                >
                  {rowUploadLabel}
                </Button>
                <Button
                  ghost
                  size="sm"
                  prefix={<RefreshCw className="h-4 w-4" />}
                  disabled={rowIndexDisabled}
                  onClick={() => void handleReindex(kb)}
                >
                  {rowIndexLabel}
                </Button>
                <Button
                  ghost
                  size="sm"
                  prefix={<Trash2 className="h-4 w-4" />}
                  onClick={() => kbDelete.requestDelete(kb.id)}
                >
                  {t.common.delete}
                </Button>
              </div>
            </CardContent>
          </Card>
        );})}
      </div>
    </div>
  );
}
