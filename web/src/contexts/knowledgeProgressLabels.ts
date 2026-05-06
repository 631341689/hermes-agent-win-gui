import { useCallback } from "react";
import type { KnowledgeReindexStreamEvent } from "@/lib/api";
import { useI18n } from "@/i18n";

/** Shared upload / reindex progress label helpers for Knowledge page + global task panels. */
export function useKnowledgeProgressLabels() {
  const { t } = useI18n();

  const uploadPhaseLabel = useCallback(
    (phase: string) => {
      const map: Record<string, string> = {
        starting: t.knowledgePage.uploadPhaseStarting,
        saved: t.knowledgePage.uploadPhaseSaved,
        working: t.knowledgePage.uploadPhaseWorking,
        skip_mineru_disabled: t.knowledgePage.uploadPhaseSkipMineruDisabled,
        skip_mineru_no_root: t.knowledgePage.uploadPhaseSkipMineruNoRoot,
        skip_mineru_bad_root: t.knowledgePage.uploadPhaseSkipMineruBadRoot,
        skip_non_pdf: t.knowledgePage.uploadPhaseSkipNonPdf,
        read_error: t.knowledgePage.uploadPhaseReadError,
        mineru_prepare: t.knowledgePage.uploadPhaseMineruPrepare,
        mineru_parsing: t.knowledgePage.uploadPhaseMineruParsing,
        mineru_parse_done: t.knowledgePage.uploadPhaseMineruParseDone,
        mineru_writing: t.knowledgePage.uploadPhaseMineruWriting,
        mineru_complete: t.knowledgePage.uploadPhaseMineruComplete,
        mineru_import_failed: t.knowledgePage.uploadPhaseMineruImportFailed,
        mineru_missing_md: t.knowledgePage.uploadPhaseMineruMissingMd,
        mineru_error: t.knowledgePage.uploadPhaseMineruError,
      };
      return map[phase] ?? `${t.knowledgePage.uploadPhaseUnknown}: ${phase}`;
    },
    [t],
  );

  const humanizeGraphragWorkflow = useCallback((name: string) => name.replace(/_/g, " "), []);

  const reindexPhaseLabel = useCallback(
    (ev: KnowledgeReindexStreamEvent) => {
      if (ev.event !== "progress") return "";
      const { phase, current, total, path, chunk_count: chunkCount } = ev;
      if (phase === "graphrag") {
        const ge = ev.graphrag_event;
        if (ge === "prepare") {
          const mode =
            ev.graphrag_message === "incremental"
              ? t.knowledgePage.reindexGraphragModeIncremental
              : t.knowledgePage.reindexGraphragModeFull;
          const method = ev.indexing_method ?? "standard";
          return t.knowledgePage.reindexGraphragPrepare
            .replace("{{mode}}", mode)
            .replace("{{method}}", method)
            .replace("{{n}}", String(ev.documents ?? 0));
        }
        if (ge === "pipeline_start") {
          const n = ev.workflow_total ?? ev.workflows?.length ?? 0;
          return t.knowledgePage.reindexGraphragPipelineStart.replace("{{n}}", String(n));
        }
        if (ge === "workflow_start" && ev.workflow) {
          const label = humanizeGraphragWorkflow(ev.workflow);
          return t.knowledgePage.reindexGraphragWorkflowRunning
            .replace("{{current}}", String(ev.workflow_index ?? 0))
            .replace("{{total}}", String(ev.workflow_total ?? 0))
            .replace("{{name}}", label);
        }
        if (ge === "workflow_end" && ev.workflow) {
          const label = humanizeGraphragWorkflow(ev.workflow);
          return t.knowledgePage.reindexGraphragWorkflowDone.replace("{{name}}", label);
        }
        if (ge === "pipeline_end") return t.knowledgePage.reindexGraphragPipelineDone;
        if (ge === "subprogress") {
          const d = ev.subprogress_description ?? "";
          const c = ev.subprogress_current;
          const tot = ev.subprogress_total;
          if (d && c != null && tot != null) {
            return t.knowledgePage.reindexGraphragSubprogress
              .replace("{{desc}}", d)
              .replace("{{cur}}", String(c))
              .replace("{{tot}}", String(tot));
          }
          return d || "";
        }
        return ev.graphrag_message || phase;
      }
      if (phase === "chunking") {
        if (current === 0 && typeof total === "number") {
          return t.knowledgePage.reindexPhaseChunkingPrep.replace("{{total}}", String(total));
        }
        if (typeof current === "number" && typeof total === "number" && total > 0) {
          const p = path ?? "";
          return t.knowledgePage.reindexPhaseChunkingDetail
            .replace("{{current}}", String(current))
            .replace("{{total}}", String(total))
            .replace("{{path}}", p);
        }
        return t.knowledgePage.reindexPhaseChunking;
      }
      if (phase === "embedding") {
        if (typeof chunkCount === "number") {
          return t.knowledgePage.reindexPhaseEmbeddingCount.replace("{{n}}", String(chunkCount));
        }
        return t.knowledgePage.reindexPhaseEmbedding;
      }
      if (phase === "writing_index") return t.knowledgePage.reindexPhaseWriting;
      if (phase === "routing_summary") return t.knowledgePage.reindexPhaseRoutingSummary;
      return phase;
    },
    [humanizeGraphragWorkflow, t],
  );

  return { uploadPhaseLabel, reindexPhaseLabel, humanizeGraphragWorkflow };
}
