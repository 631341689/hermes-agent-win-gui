import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type KnowledgeBase } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";
import { useKnowledgeProgressLabels } from "@/contexts/knowledgeProgressLabels";

const SESSION_KEY = "hermes.dashboard.knowledgeTasks.v1";

type PersistedV1 = {
  v: 1;
  upload?: {
    minimized: true;
    kbName: string;
    fileName: string;
    isPdf: boolean;
    phase: string;
    startedAt: number;
  };
  reindex?: {
    minimized: true;
    kbId: string;
    kbName: string;
    kbMode: KnowledgeBase["mode"];
    phase: string;
    line: string;
    startedAt: number;
  };
  query?: {
    minimized: true;
    kbName: string;
    mode: "vector" | "graphrag";
    startedAt: number;
  };
};

export type UploadOverlayState = {
  kbId: string;
  kbName: string;
  fileName: string;
  isPdf: boolean;
  phase: string;
  startedAt: number;
  detail?: string | null;
  minimized: boolean;
};

export type ReindexOverlayState = {
  kbId: string;
  kbName: string;
  kbMode: KnowledgeBase["mode"];
  phase: string;
  line: string;
  startedAt: number;
  minimized: boolean;
  graphrag?: {
    steps: string[];
    completedWorkflows: string[];
    activeWorkflow: string | null;
    subLine: string | null;
  };
};

export type QueryWaitState = {
  minimized: boolean;
  kbName: string;
  mode: "vector" | "graphrag";
  startedAt: number;
};

type RecoverNotifier = (message: string, type: "success" | "error") => void;

export type KnowledgeTasksContextValue = {
  uploadOverlay: UploadOverlayState | null;
  setUploadOverlay: Dispatch<SetStateAction<UploadOverlayState | null>>;
  reindexOverlay: ReindexOverlayState | null;
  setReindexOverlay: Dispatch<SetStateAction<ReindexOverlayState | null>>;
  queryWait: QueryWaitState | null;
  setQueryWait: Dispatch<SetStateAction<QueryWaitState | null>>;
  reindexAbortRef: React.MutableRefObject<AbortController | null>;
  queryAbortRef: React.MutableRefObject<AbortController | null>;
  uploadTick: number;
  registerTaskHooks: (
    notify: RecoverNotifier | null,
    loadBases: (() => void) | null,
  ) => void;
};

const KnowledgeTasksContext = createContext<KnowledgeTasksContextValue | null>(null);

function KnowledgeTaskPanels() {
  const {
    uploadOverlay,
    setUploadOverlay,
    reindexOverlay,
    setReindexOverlay,
    queryWait,
    setQueryWait,
    reindexAbortRef,
    queryAbortRef,
    uploadTick,
  } = useKnowledgeTasks();
  const { t } = useI18n();
  const { uploadPhaseLabel, humanizeGraphragWorkflow } = useKnowledgeProgressLabels();

  const uploadElapsedSec = uploadOverlay
    ? Math.floor((Date.now() - uploadOverlay.startedAt) / 1000)
    : 0;
  const reindexElapsedSec = reindexOverlay
    ? Math.floor((Date.now() - reindexOverlay.startedAt) / 1000)
    : 0;
  const queryElapsedSec = queryWait
    ? Math.floor((Date.now() - queryWait.startedAt) / 1000)
    : 0;

  const graphragBarPct =
    reindexOverlay?.graphrag && reindexOverlay.graphrag.steps.length > 0
      ? Math.min(
          100,
          ((reindexOverlay.graphrag.completedWorkflows.length +
            (reindexOverlay.graphrag.activeWorkflow ? 0.35 : 0)) /
            reindexOverlay.graphrag.steps.length) *
            100,
        )
      : null;

  return (
    <>
      {(uploadOverlay?.minimized ||
        reindexOverlay?.minimized ||
        queryWait?.minimized) && (
        <div
          className="fixed bottom-3 left-3 right-3 z-[95] flex flex-col gap-2 md:left-auto md:right-3 md:max-w-lg md:min-w-[320px]"
          aria-live="polite"
        >
          {uploadOverlay?.minimized && (
            <Card className="border-primary/30 shadow-lg">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-muted-foreground">
                    {t.knowledgePage.uploadProgressTitle}
                  </p>
                  <p className="truncate text-sm">{uploadOverlay.kbName}</p>
                  <p className="truncate font-mono text-[11px] text-muted-foreground">
                    {uploadPhaseLabel(uploadOverlay.phase)}
                  </p>
                  <p className="tabular-nums text-[11px] text-muted-foreground">
                    {t.knowledgePage.uploadElapsed.replace("{{sec}}", String(uploadElapsedSec))}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    type="button"
                    size="sm"
                    ghost
                    onClick={() => setUploadOverlay((o) => (o ? { ...o, minimized: false } : null))}
                  >
                    {t.knowledgePage.expandPanel}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
          {reindexOverlay?.minimized && (
            <Card className="border-primary/30 shadow-lg">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-muted-foreground">
                    {reindexOverlay.kbMode === "graphrag"
                      ? t.knowledgePage.reindexProgressTitleGraphrag
                      : t.knowledgePage.reindexProgressTitle}
                  </p>
                  <p className="truncate text-sm">{reindexOverlay.kbName}</p>
                  <p className="line-clamp-2 text-xs text-muted-foreground">{reindexOverlay.line}</p>
                  <p className="tabular-nums text-[11px] text-muted-foreground">
                    {t.knowledgePage.uploadElapsed.replace("{{sec}}", String(reindexElapsedSec))}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    type="button"
                    size="sm"
                    ghost
                    onClick={() => setReindexOverlay((o) => (o ? { ...o, minimized: false } : null))}
                  >
                    {t.knowledgePage.expandPanel}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    ghost
                    className="text-destructive hover:text-destructive"
                    onClick={() =>
                      reindexOverlay.phase === "recovering"
                        ? setReindexOverlay(null)
                        : reindexAbortRef.current?.abort()
                    }
                  >
                    {reindexOverlay.phase === "recovering"
                      ? t.common.close
                      : t.knowledgePage.reindexStop}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
          {queryWait?.minimized && (
            <Card className="border-primary/30 shadow-lg">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-muted-foreground">
                    {t.knowledgePage.queryRunning}
                  </p>
                  <p className="truncate text-sm">{queryWait.kbName}</p>
                  <p className="tabular-nums text-[11px] text-muted-foreground">
                    {t.knowledgePage.uploadElapsed.replace("{{sec}}", String(queryElapsedSec))}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    type="button"
                    size="sm"
                    ghost
                    onClick={() => setQueryWait((o) => (o ? { ...o, minimized: false } : null))}
                  >
                    {t.knowledgePage.expandPanel}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    ghost
                    className="text-destructive hover:text-destructive"
                    onClick={() => queryAbortRef.current?.abort()}
                  >
                    {t.common.cancel}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {reindexOverlay && !reindexOverlay.minimized && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
          role="alertdialog"
          aria-busy="true"
          aria-live="polite"
          aria-label={
            reindexOverlay.kbMode === "graphrag"
              ? t.knowledgePage.reindexProgressTitleGraphrag
              : t.knowledgePage.reindexProgressTitle
          }
        >
          <Card className="w-full max-w-lg border-border shadow-xl">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                {reindexOverlay.kbMode === "graphrag"
                  ? t.knowledgePage.reindexProgressTitleGraphrag
                  : t.knowledgePage.reindexProgressTitle}
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{reindexOverlay.kbName}</span>
              </div>
              <p className="text-sm leading-snug">{reindexOverlay.line}</p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {reindexOverlay.phase === "recovering"
                  ? t.knowledgePage.indexingRecoveredHint
                  : reindexOverlay.kbMode === "graphrag"
                    ? t.knowledgePage.reindexGraphragHint
                    : t.knowledgePage.reindexProgressHint}
              </p>
              {reindexOverlay.graphrag?.subLine && (
                <p className="font-mono text-[11px] leading-snug text-muted-foreground">
                  {reindexOverlay.graphrag.subLine}
                </p>
              )}
              {reindexOverlay.graphrag && reindexOverlay.graphrag.steps.length > 0 && (
                <ol className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-border bg-muted/30 p-2 text-[11px] text-muted-foreground">
                  {reindexOverlay.graphrag.steps.map((name, i) => {
                    const gr = reindexOverlay.graphrag!;
                    const done = gr.completedWorkflows.includes(name);
                    const active = gr.activeWorkflow === name;
                    const prefix = done ? "✓" : active ? "→" : "○";
                    return (
                      <li
                        key={`${i}-${name}`}
                        className={cn(
                          "font-mono",
                          active && "font-medium text-primary",
                          done && !active && "opacity-70",
                        )}
                      >
                        <span className="mr-1.5 inline-block w-3">{prefix}</span>
                        {humanizeGraphragWorkflow(name)}
                      </li>
                    );
                  })}
                </ol>
              )}
              <div className="tabular-nums text-xs text-muted-foreground">
                <span className="sr-only" aria-hidden>
                  {uploadTick}
                </span>
                {t.knowledgePage.uploadElapsed.replace("{{sec}}", String(reindexElapsedSec))}
              </div>
              <div className="flex flex-wrap gap-2">
                {reindexOverlay.phase !== "recovering" && (
                  <Button
                    type="button"
                    ghost
                    size="sm"
                    onClick={() => setReindexOverlay((o) => (o ? { ...o, minimized: true } : null))}
                  >
                    {t.knowledgePage.backgroundRun}
                  </Button>
                )}
                <Button
                  type="button"
                  ghost
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() =>
                    reindexOverlay.phase === "recovering"
                      ? setReindexOverlay(null)
                      : reindexAbortRef.current?.abort()
                  }
                >
                  {reindexOverlay.phase === "recovering"
                    ? t.common.close
                    : t.knowledgePage.reindexStop}
                </Button>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                {graphragBarPct != null ? (
                  <div
                    className="h-full rounded-full bg-primary/80 transition-[width] duration-500 ease-out"
                    style={{ width: `${graphragBarPct}%` }}
                  />
                ) : (
                  <div className="h-full w-full animate-pulse rounded-full bg-primary/70" />
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {uploadOverlay && !uploadOverlay.minimized && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
          role="alertdialog"
          aria-busy="true"
          aria-live="polite"
          aria-label={t.knowledgePage.uploadProgressTitle}
        >
          <Card className="w-full max-w-lg border-border shadow-xl">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{t.knowledgePage.uploadProgressTitle}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              <div className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{uploadOverlay.kbName}</span>
                <span className="mx-1">·</span>
                <span className="font-mono text-xs">{uploadOverlay.fileName}</span>
              </div>
              <p className="text-sm leading-snug">{uploadPhaseLabel(uploadOverlay.phase)}</p>
              {uploadOverlay.isPdf &&
                (uploadOverlay.phase.startsWith("mineru") ||
                  uploadOverlay.phase === "saved" ||
                  uploadOverlay.phase === "working" ||
                  uploadOverlay.phase === "starting") && (
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {t.knowledgePage.uploadProgressHint}
                  </p>
                )}
              {uploadOverlay.detail && (
                <pre className="max-h-28 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-[11px] text-muted-foreground">
                  {uploadOverlay.detail}
                </pre>
              )}
              <div className="tabular-nums text-xs text-muted-foreground">
                <span className="sr-only" aria-hidden>
                  {uploadTick}
                </span>
                {t.knowledgePage.uploadElapsed.replace("{{sec}}", String(uploadElapsedSec))}
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div className="h-full w-full animate-pulse rounded-full bg-primary/70" />
              </div>
              <Button
                type="button"
                ghost
                size="sm"
                className="w-fit"
                onClick={() => setUploadOverlay((o) => (o ? { ...o, minimized: true } : null))}
              >
                {t.knowledgePage.backgroundRun}
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {queryWait && !queryWait.minimized && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 p-4 backdrop-blur-sm"
          role="alertdialog"
          aria-busy="true"
          aria-live="polite"
          aria-label={t.knowledgePage.queryProgressTitle}
        >
          <Card className="w-full max-w-md border-border shadow-xl">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">{t.knowledgePage.queryProgressTitle}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3">
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{queryWait.kbName}</span>
                <span className="mx-1 text-xs">·</span>
                <span className="text-xs">
                  {queryWait.mode === "graphrag"
                    ? t.knowledgePage.modeGraphrag
                    : t.knowledgePage.modeVector}
                </span>
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground">{t.knowledgePage.queryRunning}</p>
              <div className="tabular-nums text-xs text-muted-foreground">
                <span className="sr-only" aria-hidden>
                  {uploadTick}
                </span>
                {t.knowledgePage.uploadElapsed.replace("{{sec}}", String(queryElapsedSec))}
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div className="h-full w-full animate-pulse rounded-full bg-primary/70" />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  ghost
                  size="sm"
                  onClick={() => setQueryWait((o) => (o ? { ...o, minimized: true } : null))}
                >
                  {t.knowledgePage.backgroundRun}
                </Button>
                <Button
                  type="button"
                  ghost
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => queryAbortRef.current?.abort()}
                >
                  {t.common.cancel}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}

export function KnowledgeTasksProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [uploadOverlay, setUploadOverlay] = useState<UploadOverlayState | null>(null);
  const [reindexOverlay, setReindexOverlay] = useState<ReindexOverlayState | null>(null);
  const [queryWait, setQueryWait] = useState<QueryWaitState | null>(null);
  const [uploadTick, setUploadTick] = useState(0);
  const reindexAbortRef = useRef<AbortController | null>(null);
  const queryAbortRef = useRef<AbortController | null>(null);

  const recoverNotifierRef = useRef<RecoverNotifier | null>(null);
  const loadBasesRef = useRef<(() => void) | null>(null);
  const recoveryRanRef = useRef(false);

  useEffect(() => {
    if (!uploadOverlay && !reindexOverlay && !queryWait) return;
    const tickMs =
      uploadOverlay != null
        ? 500
        : reindexOverlay?.kbMode === "graphrag"
          ? 1000
          : queryWait
            ? 500
            : 500;
    const id = window.setInterval(() => setUploadTick((x) => x + 1), tickMs);
    return () => window.clearInterval(id);
  }, [uploadOverlay, reindexOverlay, queryWait]);

  useEffect(() => {
    const p: Partial<PersistedV1> & { v: 1 } = { v: 1 };
    if (uploadOverlay?.minimized) {
      p.upload = {
        minimized: true,
        kbName: uploadOverlay.kbName,
        fileName: uploadOverlay.fileName,
        isPdf: uploadOverlay.isPdf,
        phase: uploadOverlay.phase,
        startedAt: uploadOverlay.startedAt,
      };
    }
    if (reindexOverlay?.minimized && reindexOverlay.kbId) {
      p.reindex = {
        minimized: true,
        kbId: reindexOverlay.kbId,
        kbName: reindexOverlay.kbName,
        kbMode: reindexOverlay.kbMode,
        phase: reindexOverlay.phase,
        line: reindexOverlay.line,
        startedAt: reindexOverlay.startedAt,
      };
    }
    if (queryWait?.minimized) {
      p.query = {
        minimized: true,
        kbName: queryWait.kbName,
        mode: queryWait.mode,
        startedAt: queryWait.startedAt,
      };
    }
    if (!p.upload && !p.reindex && !p.query) {
      try {
        sessionStorage.removeItem(SESSION_KEY);
      } catch {
        /* ignore */
      }
      return;
    }
    try {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(p));
    } catch {
      /* ignore */
    }
  }, [uploadOverlay, reindexOverlay, queryWait]);

  const registerTaskHooks = useCallback(
    (notify: RecoverNotifier | null, loadBases: (() => void) | null) => {
      recoverNotifierRef.current = notify;
      loadBasesRef.current = loadBases;
      if (!notify || !loadBases || recoveryRanRef.current) return;
      recoveryRanRef.current = true;

      let raw: string | null = null;
      try {
        raw = sessionStorage.getItem(SESSION_KEY);
      } catch {
        return;
      }
      if (!raw) return;

      let parsed: PersistedV1;
      try {
        parsed = JSON.parse(raw) as PersistedV1;
      } catch {
        try {
          sessionStorage.removeItem(SESSION_KEY);
        } catch {
          /* ignore */
        }
        return;
      }
      if (parsed.v !== 1) {
        try {
          sessionStorage.removeItem(SESSION_KEY);
        } catch {
          /* ignore */
        }
        return;
      }

      if (parsed.upload?.minimized) {
        notify(t.knowledgePage.minimizedTaskLostOnRefreshUpload, "error");
      }
      if (parsed.query?.minimized) {
        notify(t.knowledgePage.minimizedTaskLostOnRefreshQuery, "error");
      }

      if (parsed.reindex?.minimized && parsed.reindex.kbId) {
        void (async () => {
          try {
            const { bases } = await api.listKnowledgeBases();
            const kb = bases.find((b) => b.id === parsed.reindex!.kbId);
            if (kb?.indexing_status === "indexing") {
              setReindexOverlay({
                kbId: kb.id,
                kbName: kb.name,
                kbMode: kb.mode,
                phase: "recovering",
                line: t.knowledgePage.indexingRecoveredHint,
                startedAt: parsed.reindex!.startedAt ?? Date.now(),
                minimized: true,
              });
            }
          } catch {
            /* ignore */
          }
        })();
      }

      try {
        sessionStorage.removeItem(SESSION_KEY);
      } catch {
        /* ignore */
      }
    },
    [t],
  );

  useEffect(() => {
    if (reindexOverlay?.phase !== "recovering" || !reindexOverlay.kbId) return;
    const kbId = reindexOverlay.kbId;
    const id = window.setInterval(() => {
      void (async () => {
        try {
          const { bases } = await api.listKnowledgeBases();
          const kb = bases.find((b) => b.id === kbId);
          if (!kb || kb.indexing_status !== "indexing") {
            setReindexOverlay(null);
            recoverNotifierRef.current?.(t.knowledgePage.indexingRecoveredDone, "success");
            loadBasesRef.current?.();
          }
        } catch {
          /* ignore */
        }
      })();
    }, 3000);
    return () => window.clearInterval(id);
  }, [reindexOverlay?.phase, reindexOverlay?.kbId, t]);

  const value = useMemo(
    () =>
      ({
        uploadOverlay,
        setUploadOverlay,
        reindexOverlay,
        setReindexOverlay,
        queryWait,
        setQueryWait,
        reindexAbortRef,
        queryAbortRef,
        uploadTick,
        registerTaskHooks,
      }) satisfies KnowledgeTasksContextValue,
    [
      uploadOverlay,
      reindexOverlay,
      queryWait,
      uploadTick,
      registerTaskHooks,
    ],
  );

  return (
    <KnowledgeTasksContext.Provider value={value}>
      {children}
      <KnowledgeTaskPanels />
    </KnowledgeTasksContext.Provider>
  );
}

export function useKnowledgeTasks(): KnowledgeTasksContextValue {
  const ctx = useContext(KnowledgeTasksContext);
  if (!ctx) {
    throw new Error("useKnowledgeTasks must be used within KnowledgeTasksProvider");
  }
  return ctx;
}
