/**
 * MSW handlers for ``/api/mcp/*`` — dev-only when ``VITE_MCP_MOCK=1``.
 * In-memory store resets on full page reload. Vitest imports the same handlers
 * with ``setupServer`` from ``msw/node``.
 */
import { http, HttpResponse } from "msw";

import type { McpServerConfigPayload } from "@/lib/mcpTypes";

const RELOAD_HINT =
  "Restart CLI, TUI, or the messaging gateway for MCP changes to take effect in running sessions.";

/** Mutable mock state (clone on read for handlers). */
export const mcpMockStore: Record<string, McpServerConfigPayload> = {
  demo_fs: {
    enabled: true,
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
  },
  demo_http: {
    enabled: true,
    url: "https://example.invalid/mcp",
    headers: { Authorization: "Bearer ghp_****abcd" },
  },
  demo_oauth: {
    enabled: true,
    url: "https://example.invalid/mcp",
    auth: "oauth",
    oauth: { redirect_port: 0 },
  },
};

export function resetMcpMockStore() {
  Object.keys(mcpMockStore).forEach((k) => delete mcpMockStore[k]);
  mcpMockStore.demo_fs = {
    enabled: true,
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
  };
  mcpMockStore.demo_http = {
    enabled: true,
    url: "https://example.invalid/mcp",
    headers: { Authorization: "Bearer ghp_****abcd" },
  };
  mcpMockStore.demo_oauth = {
    enabled: true,
    url: "https://example.invalid/mcp",
    auth: "oauth",
    oauth: { redirect_port: 0 },
  };
}

function listResponse() {
  const servers = Object.keys(mcpMockStore)
    .sort()
    .map((name) => ({
      name,
      config: JSON.parse(JSON.stringify(mcpMockStore[name])) as McpServerConfigPayload,
    }));
  return { servers, reload_hint: RELOAD_HINT };
}

function paramName(params: Record<string, string | readonly string[] | undefined>): string {
  const raw = params.name;
  const s = Array.isArray(raw) ? raw[0] : raw;
  return decodeURIComponent(String(s ?? ""));
}

export const mcpHandlers = [
  http.get("/api/mcp/servers", () => HttpResponse.json(listResponse())),

  http.get("/api/mcp/servers/:name", ({ params }) => {
    const name = paramName(params);
    const cfg = mcpMockStore[name];
    if (!cfg) {
      return HttpResponse.json({ detail: "Server not found" }, { status: 404 });
    }
    return HttpResponse.json({ name, config: JSON.parse(JSON.stringify(cfg)) });
  }),

  http.put("/api/mcp/servers/:name", async ({ params, request }) => {
    const name = paramName(params);
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return HttpResponse.json({ detail: "Invalid JSON" }, { status: 400 });
    }
    if (!body || typeof body !== "object") {
      return HttpResponse.json({ detail: "Body must be an object" }, { status: 400 });
    }
    mcpMockStore[name] = body as McpServerConfigPayload;
    return HttpResponse.json({ ok: true, name, reload_hint: RELOAD_HINT });
  }),

  http.delete("/api/mcp/servers/:name", ({ params }) => {
    const name = paramName(params);
    if (!mcpMockStore[name]) {
      return HttpResponse.json({ detail: "Server not found" }, { status: 404 });
    }
    delete mcpMockStore[name];
    return HttpResponse.json({ ok: true, name });
  }),

  http.post("/api/mcp/servers/:name/test", ({ params }) => {
    const name = paramName(params);
    if (!mcpMockStore[name]) {
      return HttpResponse.json({ detail: "Server not found" }, { status: 404 });
    }
    if (name === "demo_fail" || name.endsWith("__fail")) {
      return HttpResponse.json(
        { detail: "Connection refused (mock)" },
        { status: 502 },
      );
    }
    return HttpResponse.json({
      ok: true as const,
      tools: [
        { name: "read_file", description: "Read a file from disk (mock)." },
        { name: "write_file", description: "Write content to a path (mock)." },
      ],
      elapsed_ms: 42,
    });
  }),

  http.post("/api/mcp/servers/:name/oauth-login", ({ params }) => {
    const name = paramName(params);
    const cfg = mcpMockStore[name];
    if (!cfg) {
      return HttpResponse.json({ detail: "Server not found" }, { status: 404 });
    }
    if (!cfg.url) {
      return HttpResponse.json(
        { detail: "OAuth applies to HTTP servers only" },
        { status: 400 },
      );
    }
    if ((cfg.auth || "").toLowerCase() !== "oauth") {
      return HttpResponse.json(
        { detail: "Server is not configured with auth: oauth" },
        { status: 400 },
      );
    }
    return HttpResponse.json({
      ok: true,
      message: "Mock OAuth flow completed.",
      tool_count: 2,
    });
  }),

  http.post("/api/mcp/parse-install", async ({ request }) => {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return HttpResponse.json({ detail: "Invalid JSON" }, { status: 400 });
    }
    const raw = typeof body === "object" && body && "raw" in body ? String((body as { raw: unknown }).raw) : "";
    if (!raw.trim()) {
      return HttpResponse.json({ detail: "raw required" }, { status: 400 });
    }
    return HttpResponse.json({
      recommended_transport: "stdio",
      confidence: "high",
      server_name_suggestion: "mock-parsed",
      stdio: { command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"] },
      http: { url: "", headers: {}, auth: "" },
      notes: "MSW mock parse.",
      model_used: "mock",
      credential_source: "msw",
    });
  }),
];
