/**
 * Dashboard MCP API types — aligned with on-disk ``config.yaml`` → ``mcp_servers.<name>``
 * and with the REST contract to be implemented in phase B (FastAPI under ``hermes_cli``).
 *
 * Field names mirror Python / YAML (``command``, ``args``, ``url``, ``headers``, …).
 * No runtime behaviour changes until backend routes exist; these types define the wire
 * format the UI will use.
 *
 * @see tools/mcp_tool.py (config examples)
 * @see hermes_cli/mcp_config.py (CLI persistence)
 */

/** Per-server tool allow/deny lists (issue #690 style). */
export interface McpToolsFilter {
  include?: string[];
  exclude?: string[];
}

/**
 * One MCP server block under ``mcp_servers`` — body for ``PUT /api/mcp/servers/{name}``
 * (full replace for that server name). Exactly one transport is required on write:
 * stdio (``command``) XOR HTTP (``url``); the backend validates.
 */
export interface McpServerConfigPayload {
  enabled?: boolean;
  /** Stdio transport — mutually exclusive with ``url``. */
  command?: string;
  args?: string[];
  /** Extra env for the child process; may use ``${VAR}`` interpolation. */
  env?: Record<string, string>;
  /** Streamable HTTP transport — mutually exclusive with ``command``. */
  url?: string;
  headers?: Record<string, string>;
  timeout?: number;
  connect_timeout?: number;
  tools?: McpToolsFilter;
  /** e.g. ``"oauth"`` for URL servers using MCP OAuth 2.1 */
  auth?: string;
  oauth?: Record<string, unknown>;
  sampling?: Record<string, unknown>;
}

/** One row from ``GET /api/mcp/servers`` — ``config`` may contain masked secrets. */
export interface McpServerSummary {
  name: string;
  config: McpServerConfigPayload;
}

export interface McpServersListResponse {
  servers: McpServerSummary[];
  /** After mutations — in-process MCP still needs chat/gateway restart per Hermes docs. */
  reload_hint?: string;
}

export interface McpServerPutResponse {
  ok: boolean;
  name: string;
  reload_hint?: string;
}

export interface McpServerDeleteResponse {
  ok: boolean;
  name?: string;
}

/**
 * Successful ``POST /api/mcp/servers/{name}/test`` body (HTTP 2xx).
 * Failures: non-2xx + FastAPI ``detail``; ``fetchJSON`` throws ``Error``.
 */
export interface McpServerTestResponse {
  ok: true;
  tools: Array<{ name: string; description?: string }>;
  elapsed_ms?: number;
}

/** ``POST /api/mcp/servers/{name}/oauth-login`` */
export interface McpServerOAuthLoginResponse {
  ok: boolean;
  message?: string;
  tool_count?: number;
}

/** ``POST /api/mcp/parse-install`` — LLM-assisted draft for stdio + HTTP (save uses one). */
export interface McpParseInstallStdio {
  command: string;
  args: string[];
}

export interface McpParseInstallHttp {
  url: string;
  headers: Record<string, string>;
  auth: string;
}

export interface McpParseInstallResponse {
  recommended_transport: "stdio" | "http" | "unclear";
  confidence: string;
  server_name_suggestion: string;
  stdio: McpParseInstallStdio;
  http: McpParseInstallHttp;
  notes: string;
  model_used?: string;
  credential_source?: string;
}
