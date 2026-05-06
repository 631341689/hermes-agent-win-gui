const BASE = "";

import type { DashboardTheme } from "@/themes/types";
import type {
  McpServerConfigPayload,
  McpServerDeleteResponse,
  McpServerOAuthLoginResponse,
  McpServerPutResponse,
  McpServersListResponse,
  McpServerSummary,
  McpServerTestResponse,
  McpParseInstallResponse,
} from "@/lib/mcpTypes";

export type {
  McpServerConfigPayload,
  McpServerDeleteResponse,
  McpServerOAuthLoginResponse,
  McpServerPutResponse,
  McpServersListResponse,
  McpServerSummary,
  McpServerTestResponse,
  McpParseInstallResponse,
  McpToolsFilter,
} from "@/lib/mcpTypes";

// Ephemeral session token for protected endpoints.
// Injected into index.html by the server — never fetched via API.
declare global {
  interface Window {
    __HERMES_SESSION_TOKEN__?: string;
    /** Injected by `hermes dashboard`: auto | en | zh — see `dashboard.locale` in config.yaml */
    __HERMES_DASHBOARD_LOCALE__?: string;
  }
}
let _sessionToken: string | null = null;
const SESSION_HEADER = "X-Hermes-Session-Token";

function setSessionHeader(headers: Headers, token: string): void {
  if (!headers.has(SESSION_HEADER)) {
    headers.set(SESSION_HEADER, token);
  }
}

export async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  // Inject the session token into all /api/ requests.
  const headers = new Headers(init?.headers);
  const token = window.__HERMES_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const res = await fetch(`${BASE}${url}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

/** SSE events from ``POST .../upload?stream=1`` (progress + one ``final`` payload). */
export type KnowledgeUploadStreamEvent =
  | { event: "saved"; filename: string; bytes: number }
  | { event: "heartbeat" }
  | { event: "progress"; phase: string; [k: string]: unknown }
  | {
      event: "final";
      ok: boolean;
      path: string;
      bytes: number;
      pdf_converted_to_markdown: boolean;
    }
  | { event: "error"; message: string };

/** Multipart upload with SSE progress (MinerU PDF phases + heartbeats while the server works). */
export async function uploadKnowledgeBaseFile(
  kbId: string,
  file: File,
  onEvent?: (ev: KnowledgeUploadStreamEvent) => void,
): Promise<{ ok: boolean; path: string; bytes: number; pdf_converted_to_markdown?: boolean }> {
  const headers = new Headers();
  const token = window.__HERMES_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const body = new FormData();
  body.append("file", file);
  const url = `${BASE}/api/knowledge/bases/${encodeURIComponent(kbId)}/upload?stream=1`;
  const res = await fetch(url, { method: "POST", headers, body });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("Upload response has no body");
  }
  const decoder = new TextDecoder();
  let buffer = "";
  let finalPayload: {
    ok: boolean;
    path: string;
    bytes: number;
    pdf_converted_to_markdown?: boolean;
  } | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const rawLine of block.split("\n")) {
        const line = rawLine.replace(/\r$/, "");
        if (!line.startsWith("data: ")) continue;
        let parsed: KnowledgeUploadStreamEvent;
        try {
          parsed = JSON.parse(line.slice(6)) as KnowledgeUploadStreamEvent;
        } catch {
          continue;
        }
        onEvent?.(parsed);
        if (parsed.event === "error") {
          throw new Error(parsed.message);
        }
        if (parsed.event === "final") {
          finalPayload = {
            ok: parsed.ok,
            path: parsed.path,
            bytes: parsed.bytes,
            pdf_converted_to_markdown: parsed.pdf_converted_to_markdown,
          };
        }
      }
    }
  }
  if (!finalPayload) {
    throw new Error("Upload stream ended without final event");
  }
  return finalPayload;
}

/** SSE from ``POST .../reindex?stream=1`` (chunking / embedding / writing + ``final``). */
export type KnowledgeReindexStreamEvent =
  | { event: "heartbeat" }
  | {
      event: "progress";
      phase: string;
      current?: number;
      total?: number;
      path?: string;
      chunk_count?: number;
      /** GraphRAG pipeline (mode=graphrag); see hermes_cli/knowledge_graphrag.py */
      graphrag_event?: string;
      graphrag_message?: string;
      workflows?: string[];
      workflow?: string;
      workflow_index?: number;
      workflow_total?: number;
      workflows_completed?: number;
      documents?: number;
      indexing_method?: string;
      message?: string;
      subprogress_description?: string | null;
      subprogress_current?: number | null;
      subprogress_total?: number | null;
      /** Filtered step list matches executed workflows when input_documents skips a loader. */
      skipped_workflow?: string | null;
      completed_workflows?: string[];
      active_workflow?: string | null;
    }
  | { event: "final"; base: KnowledgeBase; stats: KnowledgeReindexStats }
  | { event: "error"; message: string }
  | { event: "cancelled"; message?: string };

/** User stopped reindex (Abort button or server ``cancelled`` SSE). */
export class KnowledgeReindexUserCancelled extends Error {
  constructor(message = "Reindex cancelled") {
    super(message);
    this.name = "KnowledgeReindexUserCancelled";
  }
}

/** Vector reindex with SSE progress (chunk → embed → write FAISS). */
export async function reindexKnowledgeBaseWithStream(
  kbId: string,
  onEvent?: (ev: KnowledgeReindexStreamEvent) => void,
  options?: { signal?: AbortSignal; graphragForceFull?: boolean },
): Promise<{ base: KnowledgeBase; stats: KnowledgeReindexStats }> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const token = window.__HERMES_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const qs = new URLSearchParams({ stream: "1" });
  if (options?.graphragForceFull === true) {
    qs.set("full", "1");
  }
  const url = `${BASE}/api/knowledge/bases/${encodeURIComponent(kbId)}/reindex?${qs}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers,
      body: "{}",
      signal: options?.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new KnowledgeReindexUserCancelled();
    }
    throw e;
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("Reindex response has no body");
  }
  const decoder = new TextDecoder();
  let buffer = "";
  let finalPayload: { base: KnowledgeBase; stats: KnowledgeReindexStats } | null = null;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const rawLine of block.split("\n")) {
          const line = rawLine.replace(/\r$/, "");
          if (!line.startsWith("data: ")) continue;
          let parsed: KnowledgeReindexStreamEvent;
          try {
            parsed = JSON.parse(line.slice(6)) as KnowledgeReindexStreamEvent;
          } catch {
            continue;
          }
          onEvent?.(parsed);
          if (parsed.event === "error") {
            throw new Error(parsed.message);
          }
          if (parsed.event === "cancelled") {
            throw new KnowledgeReindexUserCancelled(parsed.message);
          }
          if (parsed.event === "final") {
            finalPayload = { base: parsed.base, stats: parsed.stats };
          }
        }
      }
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new KnowledgeReindexUserCancelled();
    }
    throw e;
  }
  if (!finalPayload) {
    throw new Error("Reindex stream ended without final event");
  }
  return finalPayload;
}

async function getSessionToken(): Promise<string> {
  if (_sessionToken) return _sessionToken;
  const injected = window.__HERMES_SESSION_TOKEN__;
  if (injected) {
    _sessionToken = injected;
    return _sessionToken;
  }
  throw new Error("Session token not available — page must be served by the Hermes dashboard server");
}

export const api = {
  getStatus: () => fetchJSON<StatusResponse>("/api/status"),
  getSessions: (limit = 20, offset = 0) =>
    fetchJSON<PaginatedSessions>(`/api/sessions?limit=${limit}&offset=${offset}`),
  getSessionMessages: (id: string) =>
    fetchJSON<SessionMessagesResponse>(`/api/sessions/${encodeURIComponent(id)}/messages`),
  deleteSession: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  getLogs: (params: { file?: string; lines?: number; level?: string; component?: string }) => {
    const qs = new URLSearchParams();
    if (params.file) qs.set("file", params.file);
    if (params.lines) qs.set("lines", String(params.lines));
    if (params.level && params.level !== "ALL") qs.set("level", params.level);
    if (params.component && params.component !== "all") qs.set("component", params.component);
    return fetchJSON<LogsResponse>(`/api/logs?${qs.toString()}`);
  },
  getAnalytics: (days: number) =>
    fetchJSON<AnalyticsResponse>(`/api/analytics/usage?days=${days}`),
  getModelsAnalytics: (days: number) =>
    fetchJSON<ModelsAnalyticsResponse>(`/api/analytics/models?days=${days}`),
  getConfig: () => fetchJSON<Record<string, unknown>>("/api/config"),
  getDefaults: () => fetchJSON<Record<string, unknown>>("/api/config/defaults"),
  getSchema: () => fetchJSON<{ fields: Record<string, unknown>; category_order: string[] }>("/api/config/schema"),
  getModelInfo: () => fetchJSON<ModelInfoResponse>("/api/model/info"),
  getModelOptions: () => fetchJSON<ModelOptionsResponse>("/api/model/options"),
  getAuxiliaryModels: () => fetchJSON<AuxiliaryModelsResponse>("/api/model/auxiliary"),
  setModelAssignment: (body: ModelAssignmentRequest) =>
    fetchJSON<ModelAssignmentResponse>("/api/model/set", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  saveConfig: (config: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    }),
  getConfigRaw: () => fetchJSON<{ yaml: string }>("/api/config/raw"),
  saveConfigRaw: (yaml_text: string) =>
    fetchJSON<{ ok: boolean }>("/api/config/raw", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml_text }),
    }),
  getEnvVars: () => fetchJSON<Record<string, EnvVarInfo>>("/api/env"),
  setEnvVar: (key: string, value: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    }),
  deleteEnvVar: (key: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  revealEnvVar: async (key: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ key: string; value: string }>("/api/env/reveal", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [SESSION_HEADER]: token,
      },
      body: JSON.stringify({ key }),
    });
  },

  // Cron jobs
  getCronJobs: () => fetchJSON<CronJob[]>("/api/cron/jobs"),
  createCronJob: (job: { prompt: string; schedule: string; name?: string; deliver?: string }) =>
    fetchJSON<CronJob>("/api/cron/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    }),
  pauseCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/pause`, { method: "POST" }),
  resumeCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/resume`, { method: "POST" }),
  triggerCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/trigger`, { method: "POST" }),
  deleteCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}`, { method: "DELETE" }),

  // Knowledge bases (docs/zh/knowledge-api.md)
  listKnowledgeBases: () => fetchJSON<{ bases: KnowledgeBase[] }>("/api/knowledge/bases"),
  createKnowledgeBase: (body: {
    name: string;
    mode?: "vector" | "graphrag";
    agent_summary?: string | null;
    summary_routing_mode?: "manual" | "auto";
  }) =>
    fetchJSON<{ base: KnowledgeBase }>("/api/knowledge/bases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteKnowledgeBase: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/knowledge/bases/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  /** Remove all files under ``raw/`` (replace-corpus workflow). */
  clearKnowledgeRaw: (id: string) =>
    fetchJSON<{ ok: boolean; removed_files: number }>(
      `/api/knowledge/bases/${encodeURIComponent(id)}/raw`,
      { method: "DELETE" },
    ),
  patchKnowledgeBase: (
    id: string,
    body: {
      name?: string;
      mode?: "vector" | "graphrag";
      chunk_config?: KnowledgeChunkConfig | null;
      agent_summary?: string | null;
      summary_routing_mode?: "manual" | "auto";
    },
  ) =>
    fetchJSON<{ base: KnowledgeBase }>(`/api/knowledge/bases/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  reindexKnowledgeBase: (id: string) =>
    fetchJSON<{ base: KnowledgeBase; stats?: KnowledgeReindexStats }>(
      `/api/knowledge/bases/${encodeURIComponent(id)}/reindex`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
    ),

  queryKnowledge: (
    body: {
      kb_ids: string[];
      query: string;
      top_k?: number;
      graphrag_method?: "local" | "global" | "basic" | "drift";
    },
    init?: RequestInit,
  ) =>
    fetchJSON<{ results: KnowledgeQueryHit[] }>("/api/knowledge/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: init?.signal,
    }),

  debugKnowledgeEmbedding: (input: string) =>
    fetchJSON<KnowledgeDebugEmbeddingResponse>("/api/knowledge/debug/embedding", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input }),
    }),

  // Profiles (minimal)
  getProfiles: () =>
    fetchJSON<{ profiles: ProfileInfo[] }>("/api/profiles"),
  createProfile: (body: { name: string; clone_from_default: boolean }) =>
    fetchJSON<{ ok: boolean; name: string; path: string }>("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  renameProfile: (name: string, newName: string) =>
    fetchJSON<{ ok: boolean; name: string; path: string }>(
      `/api/profiles/${encodeURIComponent(name)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_name: newName }),
      },
    ),
  deleteProfile: (name: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),
  getProfileSetupCommand: (name: string) =>
    fetchJSON<{ command: string }>(
      `/api/profiles/${encodeURIComponent(name)}/setup-command`,
    ),
  getProfileSoul: (name: string) =>
    fetchJSON<{ content: string; exists: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}/soul`,
    ),
  updateProfileSoul: (name: string, content: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/profiles/${encodeURIComponent(name)}/soul`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),

  // Skills & Toolsets
  getSkills: () => fetchJSON<SkillInfo[]>("/api/skills"),
  getSkillCategories: () => fetchJSON<SkillCategoriesResponse>("/api/skills/categories"),
  toggleSkill: (name: string, enabled: boolean) =>
    fetchJSON<{ ok: boolean }>("/api/skills/toggle", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, enabled }),
    }),
  installSkillZip: (formData: FormData) => installSkillZipForm(formData),
  getToolsets: () => fetchJSON<ToolsetInfo[]>("/api/tools/toolsets"),

  // MCP servers (``config.yaml`` → ``mcp_servers``) — backend routes land in phase B.
  getMcpServers: () => fetchJSON<McpServersListResponse>("/api/mcp/servers"),
  getMcpServer: (name: string) =>
    fetchJSON<McpServerSummary>(`/api/mcp/servers/${encodeURIComponent(name)}`),
  putMcpServer: (name: string, config: McpServerConfigPayload) =>
    fetchJSON<McpServerPutResponse>(`/api/mcp/servers/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }),
  deleteMcpServer: (name: string) =>
    fetchJSON<McpServerDeleteResponse>(`/api/mcp/servers/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  postMcpServerTest: (name: string) =>
    fetchJSON<McpServerTestResponse>(`/api/mcp/servers/${encodeURIComponent(name)}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }),
  postMcpServerOAuthLogin: (name: string) =>
    fetchJSON<McpServerOAuthLoginResponse>(
      `/api/mcp/servers/${encodeURIComponent(name)}/oauth-login`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    ),
  postMcpParseInstall: (raw: string) =>
    fetchJSON<McpParseInstallResponse>("/api/mcp/parse-install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw }),
    }),

  // Session search (FTS5)
  searchSessions: (q: string) =>
    fetchJSON<SessionSearchResponse>(`/api/sessions/search?q=${encodeURIComponent(q)}`),

  // OAuth provider management
  getOAuthProviders: () =>
    fetchJSON<OAuthProvidersResponse>("/api/providers/oauth"),
  disconnectOAuthProvider: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean; provider: string }>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}`,
      {
        method: "DELETE",
        headers: { [SESSION_HEADER]: token },
      },
    );
  },
  startOAuthLogin: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthStartResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/start`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [SESSION_HEADER]: token,
        },
        body: "{}",
      },
    );
  },
  submitOAuthCode: async (providerId: string, sessionId: string, code: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthSubmitResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/submit`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [SESSION_HEADER]: token,
        },
        body: JSON.stringify({ session_id: sessionId, code }),
      },
    );
  },
  pollOAuthSession: (providerId: string, sessionId: string) =>
    fetchJSON<OAuthPollResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/poll/${encodeURIComponent(sessionId)}`,
    ),
  cancelOAuthSession: async (sessionId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean }>(
      `/api/providers/oauth/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "DELETE",
        headers: { [SESSION_HEADER]: token },
      },
    );
  },

  // Gateway / update actions
  restartGateway: () =>
    fetchJSON<ActionResponse>("/api/gateway/restart", { method: "POST" }),
  updateHermes: () =>
    fetchJSON<ActionResponse>("/api/hermes/update", { method: "POST" }),
  getActionStatus: (name: string, lines = 200) =>
    fetchJSON<ActionStatusResponse>(
      `/api/actions/${encodeURIComponent(name)}/status?lines=${lines}`,
    ),

  // Dashboard plugins
  getPlugins: () =>
    fetchJSON<PluginManifestResponse[]>("/api/dashboard/plugins"),
  rescanPlugins: () =>
    fetchJSON<{ ok: boolean; count: number }>("/api/dashboard/plugins/rescan"),

  getPluginsHub: () => fetchJSON<PluginsHubResponse>("/api/dashboard/plugins/hub"),

  installAgentPlugin: (body: AgentPluginInstallRequest) =>
    fetchJSON<AgentPluginInstallResponse>("/api/dashboard/agent-plugins/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body }),
    }),

  enableAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string; unchanged?: boolean }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/enable`,
      { method: "POST" },
    ),

  disableAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string; unchanged?: boolean }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/disable`,
      { method: "POST" },
    ),

  updateAgentPlugin: (name: string) =>
    fetchJSON<AgentPluginUpdateResponse>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}/update`,
      { method: "POST" },
    ),

  removeAgentPlugin: (name: string) =>
    fetchJSON<{ ok: boolean; name: string }>(
      `/api/dashboard/agent-plugins/${encodeURIComponent(name)}`,
      { method: "DELETE" },
    ),

  savePluginProviders: (body: PluginProvidersPutRequest) =>
    fetchJSON<{ ok: boolean }>("/api/dashboard/plugin-providers", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  setPluginVisibility: (name: string, hidden: boolean) =>
    fetchJSON<{ ok: boolean; name: string; hidden: boolean }>(
      `/api/dashboard/plugins/${encodeURIComponent(name)}/visibility`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hidden }),
      },
    ),

  // Dashboard themes
  getThemes: () =>
    fetchJSON<DashboardThemesResponse>("/api/dashboard/themes"),
  setTheme: (name: string) =>
    fetchJSON<{ ok: boolean; theme: string }>("/api/dashboard/theme", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
};

export interface ActionResponse {
  name: string;
  ok: boolean;
  pid: number;
}

export interface ActionStatusResponse {
  exit_code: number | null;
  lines: string[];
  name: string;
  pid: number | null;
  running: boolean;
}

export interface PlatformStatus {
  error_code?: string;
  error_message?: string;
  state: string;
  updated_at: string;
}

export interface StatusResponse {
  active_sessions: number;
  config_path: string;
  config_version: number;
  env_path: string;
  gateway_exit_reason: string | null;
  gateway_health_url: string | null;
  gateway_pid: number | null;
  gateway_platforms: Record<string, PlatformStatus>;
  gateway_running: boolean;
  gateway_state: string | null;
  gateway_updated_at: string | null;
  hermes_home: string;
  latest_config_version: number;
  release_date: string;
  version: string;
}

export interface SessionInfo {
  id: string;
  source: string | null;
  model: string | null;
  title: string | null;
  started_at: number;
  ended_at: number | null;
  last_active: number;
  is_active: boolean;
  message_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  preview: string | null;
}

export interface PaginatedSessions {
  sessions: SessionInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface EnvVarInfo {
  is_set: boolean;
  redacted_value: string | null;
  description: string;
  url: string | null;
  category: string;
  is_password: boolean;
  tools: string[];
  advanced: boolean;
}

export interface SessionMessage {
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_name?: string;
  tool_call_id?: string;
  timestamp?: number;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: SessionMessage[];
}

export interface LogsResponse {
  file: string;
  lines: string[];
}

export interface AnalyticsDailyEntry {
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsModelEntry {
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  sessions: number;
  api_calls: number;
}

export interface AnalyticsSkillEntry {
  skill: string;
  view_count: number;
  manage_count: number;
  total_count: number;
  percentage: number;
  last_used_at: number | null;
}

export interface AnalyticsSkillsSummary {
  total_skill_loads: number;
  total_skill_edits: number;
  total_skill_actions: number;
  distinct_skills_used: number;
}

export interface AnalyticsResponse {
  daily: AnalyticsDailyEntry[];
  by_model: AnalyticsModelEntry[];
  totals: {
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
    total_api_calls: number;
  };
  skills: {
    summary: AnalyticsSkillsSummary;
    top_skills: AnalyticsSkillEntry[];
  };
}

export interface ProfileInfo {
  name: string;
  path: string;
  is_default: boolean;
  model: string | null;
  provider: string | null;
  has_env: boolean;
  skill_count: number;
}

export interface ModelsAnalyticsModelEntry {
  model: string;
  provider: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
  api_calls: number;
  tool_calls: number;
  last_used_at: number;
  avg_tokens_per_session: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

export interface ModelsAnalyticsResponse {
  models: ModelsAnalyticsModelEntry[];
  totals: {
    distinct_models: number;
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
    total_api_calls: number;
  };
  period_days: number;
}

export interface CronJob {
  id: string;
  name?: string;
  prompt: string;
  schedule: { kind: string; expr: string; display: string };
  schedule_display: string;
  enabled: boolean;
  state: string;
  deliver?: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
}

export type KnowledgeChunkStrategy = "window" | "delimiter" | "semantic" | "smart";

export interface KnowledgeChunkConfig {
  strategy?: KnowledgeChunkStrategy;
  size_tokens?: number;
  overlap_tokens?: number;
  delimiter?: {
    separators?: string[];
    merge_under_chars?: number;
    max_chunk_chars?: number | null;
  };
  semantic?: {
    mode?: "pack" | "embedding";
    overlap_sentences?: number;
    similarity_threshold?: number;
    max_chunk_chars?: number | null;
  };
  /** Markdown structure-aware chunking (PDF→MD); optional caps / overlap in characters */
  smart?: {
    max_chunk_chars?: number | null;
    overlap_chars?: number | null;
  };
}

export interface KnowledgeBase {
  id: string;
  name: string;
  mode: "vector" | "graphrag";
  indexing_status: "idle" | "indexing" | "ready" | "error";
  error_message: string | null;
  created_at: string;
  updated_at: string;
  chunk_config?: KnowledgeChunkConfig | null;
  /** Short blurb for agents (tool knowledge_catalog); optional. */
  agent_summary?: string | null;
  /** Auto-generated after reindex; from ``routing_summary.txt`` on disk. */
  routing_summary?: string | null;
  /** manual = handwritten only for agents; auto = generated routing_summary.txt after reindex. */
  summary_routing_mode?: "manual" | "auto";
}

export interface KnowledgeReindexStats {
  chunk_count: number;
  embedding_model: string;
  dimension?: number;
}

export interface KnowledgeQueryHit {
  chunk_id: string | null;
  text: string;
  source_path: string | null;
  score: number | null;
  kb_id: string;
  recall_score?: number;
  /** Present when hit comes from GraphRAG ``POST /query`` branch. */
  kind?: "vector" | "graphrag";
  graphrag_method?: string;
}

export interface KnowledgeDebugEmbeddingResponse {
  ok: boolean;
  model: string;
  dimension: number;
  base_url_set: boolean;
}

/** Response from ``POST /api/skills/install-zip`` (200 body; check ``ok``). */
export interface SkillZipInstallScanSummary {
  verdict: string;
  summary: string;
  findings_count: number;
  report_lines?: string[];
}

export interface SkillCategoriesResponse {
  categories: string[];
}

export interface SkillZipInstallResponse {
  ok: boolean;
  skill_name?: string;
  installed_path?: string;
  scan?: SkillZipInstallScanSummary;
  reload_hint?: string;
  detail?: string;
  blocked_reason?: string;
  errors?: string[];
}

export async function installSkillZipForm(formData: FormData): Promise<SkillZipInstallResponse> {
  const headers = new Headers();
  const token = window.__HERMES_SESSION_TOKEN__;
  if (token) {
    setSessionHeader(headers, token);
  }
  const res = await fetch(`${BASE}/api/skills/install-zip`, { method: "POST", headers, body: formData });
  let data: SkillZipInstallResponse = { ok: false, detail: "Invalid JSON response" };
  try {
    data = (await res.json()) as SkillZipInstallResponse;
  } catch {
    /* ignore */
  }
  if (res.status === 413) {
    throw new Error(typeof data.detail === "string" ? data.detail : "ZIP too large");
  }
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : `${res.status}: ${res.statusText}`);
  }
  return data;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
}

export interface ToolsetInfo {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  tools: string[];
}

export interface SessionSearchResult {
  session_id: string;
  snippet: string;
  role: string | null;
  source: string | null;
  model: string | null;
  session_started: number | null;
}

export interface SessionSearchResponse {
  results: SessionSearchResult[];
}

// ── Model info types ──────────────────────────────────────────────────

export interface ModelInfoResponse {
  model: string;
  provider: string;
  auto_context_length: number;
  config_context_length: number;
  effective_context_length: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

// ── Model options / assignment types ──────────────────────────────────

export interface ModelOptionProvider {
  name: string;
  slug: string;
  models?: string[];
  total_models?: number;
  is_current?: boolean;
  is_user_defined?: boolean;
  source?: string;
  warning?: string;
}

export interface ModelOptionsResponse {
  model?: string;
  provider?: string;
  providers?: ModelOptionProvider[];
}

export interface AuxiliaryTaskAssignment {
  task: string;
  provider: string;
  model: string;
  base_url: string;
}

export interface AuxiliaryModelsResponse {
  tasks: AuxiliaryTaskAssignment[];
  main: { provider: string; model: string };
}

export interface ModelAssignmentRequest {
  scope: "main" | "auxiliary";
  provider: string;
  model: string;
  /** For auxiliary: task slot name, "" for all, "__reset__" to reset all. */
  task?: string;
}

export interface ModelAssignmentResponse {
  ok: boolean;
  scope?: string;
  provider?: string;
  model?: string;
  tasks?: string[];
  reset?: boolean;
}

// ── OAuth provider types ────────────────────────────────────────────────

export interface OAuthProviderStatus {
  logged_in: boolean;
  source?: string | null;
  source_label?: string | null;
  token_preview?: string | null;
  expires_at?: string | null;
  has_refresh_token?: boolean;
  last_refresh?: string | null;
  error?: string;
}

export interface OAuthProvider {
  id: string;
  name: string;
  /** "pkce" (browser redirect + paste code), "device_code" (show code + URL),
   *  or "external" (delegated to a separate CLI like Claude Code or Qwen). */
  flow: "pkce" | "device_code" | "external";
  cli_command: string;
  docs_url: string;
  status: OAuthProviderStatus;
}

export interface OAuthProvidersResponse {
  providers: OAuthProvider[];
}

/** Discriminated union — the shape of /start depends on the flow. */
export type OAuthStartResponse =
  | {
      session_id: string;
      flow: "pkce";
      auth_url: string;
      expires_in: number;
    }
  | {
      session_id: string;
      flow: "device_code";
      user_code: string;
      verification_url: string;
      expires_in: number;
      poll_interval: number;
    };

export interface OAuthSubmitResponse {
  ok: boolean;
  status: "approved" | "error";
  message?: string;
}

export interface OAuthPollResponse {
  session_id: string;
  status: "pending" | "approved" | "denied" | "expired" | "error";
  error_message?: string | null;
  expires_at?: number | null;
}

// ── Dashboard theme types ──────────────────────────────────────────────

export interface DashboardThemeSummary {
  description: string;
  label: string;
  name: string;
  /** Full theme definition for user themes; undefined for built-ins
   *  (which the frontend already has locally). */
  definition?: DashboardTheme;
}

export interface DashboardThemesResponse {
  active: string;
  themes: DashboardThemeSummary[];
}

// ── Dashboard plugin types ─────────────────────────────────────────────

export interface PluginManifestResponse {
  name: string;
  label: string;
  description: string;
  icon: string;
  version: string;
  tab: {
    path: string;
    position?: string;
    override?: string;
    hidden?: boolean;
  };
  slots?: string[];
  entry: string;
  css?: string | null;
  has_api: boolean;
  source: string;
}

export interface HubAgentPluginRow {
  name: string;
  version: string;
  description: string;
  source: string;
  runtime_status: "disabled" | "enabled" | "inactive";
  has_dashboard_manifest: boolean;
  dashboard_manifest: PluginManifestResponse | null;
  path: string;
  can_remove: boolean;
  can_update_git: boolean;
  auth_required: boolean;
  auth_command: string;
  user_hidden: boolean;
}

export interface PluginsHubProviders {
  memory_provider: string;
  memory_options: Array<{ name: string; description: string }>;
  context_engine: string;
  context_options: Array<{ name: string; description: string }>;
}

export interface PluginsHubResponse {
  plugins: HubAgentPluginRow[];
  orphan_dashboard_plugins: PluginManifestResponse[];
  providers: PluginsHubProviders;
}

export interface AgentPluginInstallRequest {
  identifier: string;
  force?: boolean;
  enable?: boolean;
}

export interface AgentPluginInstallResponse {
  ok: boolean;
  plugin_name?: string;
  warnings?: string[];
  missing_env?: string[];
  after_install_path?: string | null;
  enabled?: boolean;
  error?: string;
}

export interface AgentPluginUpdateResponse {
  ok: boolean;
  name?: string;
  output?: string;
  unchanged?: boolean;
  error?: string;
}

export interface PluginProvidersPutRequest {
  memory_provider?: string;
  context_engine?: string;
}
