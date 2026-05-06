import { startTransition, useCallback, useEffect, useState } from "react";
import { Plug, Server, Trash2, FlaskConical, KeyRound, Pencil, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { McpServerConfigPayload, McpServerSummary } from "@/lib/mcpTypes";
import { Button } from "@nous-research/ui/ui/components/button";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import { parseMcpInstallCommand } from "@/lib/parseMcpInstallCommand";

const MCP_MOCK = import.meta.env.VITE_MCP_MOCK === "1";

export interface SkillsMcpPanelProps {
  showToast: (message: string, type: "success" | "error") => void;
}

export function SkillsMcpPanel({ showToast }: SkillsMcpPanelProps) {
  const { t } = useI18n();
  const m = t.skillsMcp;

  const [servers, setServers] = useState<McpServerSummary[]>([]);
  const [reloadHint, setReloadHint] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<Set<string>>(new Set());
  const [oauthing, setOAuthing] = useState<string | null>(null);
  const [pasteBox, setPasteBox] = useState("");
  const [llmParsing, setLlmParsing] = useState(false);

  const [editingName, setEditingName] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [formName, setFormName] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [transport, setTransport] = useState<"stdio" | "http">("stdio");
  const [formCommand, setFormCommand] = useState("");
  const [formArgsJson, setFormArgsJson] = useState("[]");
  const [formUrl, setFormUrl] = useState("");
  const [formHeadersJson, setFormHeadersJson] = useState("{}");
  const [formAuth, setFormAuth] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.getMcpServers();
      setServers(data.servers);
      setReloadHint(data.reload_hint ?? "");
    } catch (e) {
      setServers([]);
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    startTransition(() => {
      void load();
    });
  }, [load]);

  const openNew = () => {
    setIsNew(true);
    setEditingName(null);
    setFormName("");
    setFormEnabled(true);
    setTransport("stdio");
    setFormCommand("npx");
    setFormArgsJson('["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]');
    setFormUrl("");
    setFormHeadersJson("{}");
    setFormAuth("");
  };

  const openEdit = (row: McpServerSummary) => {
    setIsNew(false);
    setEditingName(row.name);
    setFormName(row.name);
    const c = row.config;
    const isHttp = Boolean(c.url);
    setTransport(isHttp ? "http" : "stdio");
    setFormEnabled(c.enabled !== false);
    setFormCommand(c.command ?? "");
    setFormArgsJson(JSON.stringify(c.args ?? [], null, 0));
    setFormUrl(c.url ?? "");
    setFormHeadersJson(JSON.stringify(c.headers ?? {}, null, 0));
    setFormAuth(c.auth ?? "");
  };

  const buildPayload = (): McpServerConfigPayload | null => {
    const payload: McpServerConfigPayload = { enabled: formEnabled };
    if (transport === "stdio") {
      payload.command = formCommand.trim();
      try {
        const args = JSON.parse(formArgsJson || "[]") as unknown;
        if (!Array.isArray(args) || !args.every((x) => typeof x === "string")) {
          showToast(m.badArgs, "error");
          return null;
        }
        payload.args = args;
      } catch {
        showToast(m.badArgs, "error");
        return null;
      }
    } else {
      payload.url = formUrl.trim();
      try {
        const headers = JSON.parse(formHeadersJson || "{}") as unknown;
        if (typeof headers !== "object" || headers === null || Array.isArray(headers)) {
          showToast(m.badHeaders, "error");
          return null;
        }
        payload.headers = headers as Record<string, string>;
      } catch {
        showToast(m.badHeaders, "error");
        return null;
      }
      const auth = formAuth.trim();
      if (auth) payload.auth = auth;
    }
    if (transport === "stdio" && !payload.command) {
      showToast(m.needCommand, "error");
      return null;
    }
    if (transport === "http" && !payload.url) {
      showToast(m.needUrl, "error");
      return null;
    }
    return payload;
  };

  const handleSave = async () => {
    const name = (isNew ? formName : editingName)?.trim();
    if (!name || !/^[a-zA-Z0-9_.-]+$/.test(name)) {
      showToast(m.badName, "error");
      return;
    }
    const payload = buildPayload();
    if (!payload) return;
    try {
      await api.putMcpServer(name, payload);
      showToast(m.saved, "success");
      setIsNew(false);
      setEditingName(name);
      await load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : m.saveFailed, "error");
    }
  };

  const handleDelete = async (name: string) => {
    if (!window.confirm(m.confirmDelete.replace("{name}", name))) return;
    try {
      await api.deleteMcpServer(name);
      showToast(m.deleted, "success");
      if (editingName === name) {
        setEditingName(null);
        setIsNew(false);
      }
      await load();
    } catch (e) {
      showToast(e instanceof Error ? e.message : m.deleteFailed, "error");
    }
  };

  const handleTest = async (name: string) => {
    setTesting((s) => new Set(s).add(name));
    try {
      const res = await api.postMcpServerTest(name);
      const testTpl = MCP_MOCK ? m.testOkMock : m.testOk;
      showToast(testTpl.replace("{n}", String(res.tools?.length ?? 0)), "success");
    } catch (e) {
      showToast(e instanceof Error ? e.message : m.testFailed, "error");
    } finally {
      setTesting((s) => {
        const n = new Set(s);
        n.delete(name);
        return n;
      });
    }
  };

  const handlePasteApply = () => {
    const r = parseMcpInstallCommand(pasteBox);
    if ("error" in r) {
      const msg =
        r.error === "empty"
          ? m.pasteErrorEmpty
          : r.error === "bad_url"
            ? m.pasteErrorBadUrl
            : m.pasteErrorGeneric;
      showToast(msg, "error");
      return;
    }
    if (!isNew && !editingName) {
      openNew();
    }
    if (r.transport === "http") {
      setTransport("http");
      setFormUrl(r.url);
      setFormHeadersJson("{}");
      setFormAuth("");
      setFormCommand("");
      setFormArgsJson("[]");
    } else {
      setTransport("stdio");
      setFormCommand(r.command);
      setFormArgsJson(JSON.stringify(r.args, null, 0));
      setFormUrl("");
      setFormHeadersJson("{}");
      setFormAuth("");
    }
    showToast(m.pasteApplied, "success");
  };

  const handleLlmParse = async () => {
    if (!pasteBox.trim()) {
      showToast(m.pasteErrorEmpty, "error");
      return;
    }
    setLlmParsing(true);
    try {
      if (!isNew && !editingName) {
        openNew();
      }
      const res = await api.postMcpParseInstall(pasteBox);
      const args = Array.isArray(res.stdio?.args) ? res.stdio.args.map(String) : [];
      setFormCommand(res.stdio?.command ?? "");
      setFormArgsJson(JSON.stringify(args, null, 0));
      const hdr = res.http?.headers && typeof res.http.headers === "object" ? res.http.headers : {};
      setFormUrl(res.http?.url ?? "");
      setFormHeadersJson(JSON.stringify(hdr, null, 0));
      setFormAuth(res.http?.auth ?? "");
      if (res.recommended_transport === "stdio" || res.recommended_transport === "http") {
        setTransport(res.recommended_transport);
      }
      setFormName((prev) => (prev.trim() ? prev : res.server_name_suggestion || prev));
      const bits = [res.notes, res.model_used ? `${m.llmModelUsed}: ${res.model_used}` : ""].filter(Boolean);
      showToast(bits.length ? `${m.llmApplied} ${bits.join(" — ")}` : m.llmApplied, "success");
    } catch (e) {
      showToast(e instanceof Error ? e.message : m.llmFailed, "error");
    } finally {
      setLlmParsing(false);
    }
  };

  const handleOAuth = async (name: string) => {
    setOAuthing(name);
    try {
      const res = await api.postMcpServerOAuthLogin(name);
      showToast(res.message ?? (MCP_MOCK ? m.oauthOkMock : m.oauthOk), "success");
    } catch (e) {
      showToast(e instanceof Error ? e.message : m.oauthFailed, "error");
    } finally {
      setOAuthing(null);
    }
  };

  const transportOf = useCallback((c: McpServerConfigPayload) => (c.url ? "http" : "stdio"), []);

  if (loading) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          {m.loading}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {MCP_MOCK && (
        <p className="text-xs text-amber-200/90 border border-amber-500/30 bg-amber-500/10 px-3 py-2 rounded-md">
          {m.mockBanner}
        </p>
      )}
      {loadError && (
        <div className="text-sm border border-destructive/40 bg-destructive/10 px-3 py-2 rounded-md space-y-1">
          <p className="text-destructive/90 font-medium">{m.loadFailed}</p>
          <p className="text-muted-foreground text-xs break-all">{loadError}</p>
          {!MCP_MOCK && (
            <p className="text-xs text-muted-foreground">{m.mockHint}</p>
          )}
          <Button size="xs" outlined onClick={() => void load()}>
            {m.retry}
          </Button>
        </div>
      )}
      {reloadHint && !loadError && (
        <p className="text-xs text-muted-foreground border border-border/80 bg-muted/20 px-3 py-2 rounded-md">
          {reloadHint}
        </p>
      )}

      {!loadError && (
        <details className="rounded-md border border-border/80 bg-muted/15 text-sm group">
          <summary className="cursor-pointer select-none list-none px-3 py-2 font-medium hover:bg-muted/25 rounded-md [&::-webkit-details-marker]:hidden flex items-center gap-2">
            <span className="text-muted-foreground text-[10px] group-open:rotate-90 transition-transform">
              ▸
            </span>
            {m.pasteHelperTitle}
          </summary>
          <div className="px-3 pb-3 space-y-2 border-t border-border/50 pt-2">
            <p className="text-xs text-muted-foreground leading-relaxed">{m.pasteHelperDesc}</p>
            <textarea
              className="w-full min-h-[88px] rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
              placeholder={m.pastePlaceholder}
              value={pasteBox}
              onChange={(e) => setPasteBox(e.target.value)}
              spellCheck={false}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                type="button"
                outlined
                onClick={handlePasteApply}
                disabled={llmParsing || !pasteBox.trim()}
                className="!inline-flex !flex-row items-center justify-center gap-1.5 whitespace-nowrap break-normal px-3 py-1.5 h-auto min-h-8 w-auto min-w-max [writing-mode:horizontal-tb]"
              >
                {m.pasteApply}
              </Button>
              <Button
                size="sm"
                type="button"
                onClick={() => void handleLlmParse()}
                disabled={llmParsing || !pasteBox.trim()}
                className="!inline-flex !flex-row items-center justify-center gap-1.5 whitespace-nowrap break-normal px-3 py-1.5 h-auto min-h-8 w-auto min-w-max [writing-mode:horizontal-tb]"
              >
                {m.pasteLlmParse}
              </Button>
            </div>
          </div>
        </details>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="py-2 px-4 flex flex-row items-center justify-between gap-3">
            <CardTitle className="text-sm flex items-center gap-2 min-w-0 flex-1">
              <Server className="h-4 w-4 shrink-0" />
              <span className="truncate">{m.title}</span>
            </CardTitle>
            <Button
              size="xs"
              type="button"
              onClick={openNew}
              className="!inline-flex !flex-row items-center justify-center shrink-0 gap-2 whitespace-nowrap break-normal h-8 px-4 text-xs w-auto min-w-[11.5rem] max-w-none [writing-mode:horizontal-tb]"
            >
              <Plus className="h-3.5 w-3.5 shrink-0" aria-hidden />
              {m.add}
            </Button>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {servers.length === 0 && !loadError ? (
              <p className="text-sm text-muted-foreground text-center py-6">{m.empty}</p>
            ) : (
              <ul className="space-y-0.5">
                {servers.map((row) => (
                  <li
                    key={row.name}
                    className={cn(
                      "group flex items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-sm min-h-9",
                      editingName === row.name && !isNew && "bg-muted/40 border-border",
                    )}
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <span className="font-mono-ui font-medium truncate" title={row.name}>
                        {row.name}
                      </span>
                      <div className="flex shrink-0 items-center gap-1">
                        <Badge tone="secondary" className="text-[10px] px-1.5 py-0 tabular-nums">
                          {transportOf(row.config) === "http" ? m.transportHttp : m.transportStdio}
                        </Badge>
                        <Badge
                          tone={row.config.enabled !== false ? "success" : "outline"}
                          className="text-[10px] px-1.5 py-0 tabular-nums"
                        >
                          {row.config.enabled !== false ? m.enabled : m.disabled}
                        </Badge>
                      </div>
                    </div>
                    <div
                      className="flex shrink-0 items-center gap-0.5 border-l border-border/50 pl-2 ml-0.5"
                      role="toolbar"
                      aria-label={row.name}
                    >
                      <Button
                        size="xs"
                        ghost
                        type="button"
                        className="h-8 w-8 shrink-0 p-0 inline-flex items-center justify-center"
                        onClick={() => handleTest(row.name)}
                        disabled={testing.has(row.name)}
                        data-testid={`mcp-test-${row.name}`}
                        title={m.test}
                        aria-label={`${m.test} ${row.name}`}
                      >
                        <FlaskConical className="h-4 w-4" aria-hidden />
                      </Button>
                      {row.config.url && (row.config.auth || "").toLowerCase() === "oauth" && (
                        <Button
                          size="xs"
                          ghost
                          type="button"
                          className="h-8 w-8 shrink-0 p-0 inline-flex items-center justify-center"
                          onClick={() => void handleOAuth(row.name)}
                          disabled={oauthing === row.name}
                          title={m.oauth}
                          aria-label={`${m.oauth} ${row.name}`}
                        >
                          <KeyRound className="h-4 w-4" aria-hidden />
                        </Button>
                      )}
                      <Button
                        size="xs"
                        ghost
                        type="button"
                        className="h-8 w-8 shrink-0 p-0 inline-flex items-center justify-center"
                        onClick={() => openEdit(row)}
                        title={m.edit}
                        aria-label={`${m.edit} ${row.name}`}
                      >
                        <Pencil className="h-4 w-4" aria-hidden />
                      </Button>
                      <Button
                        size="xs"
                        ghost
                        type="button"
                        className="h-8 w-8 shrink-0 p-0 inline-flex items-center justify-center text-destructive hover:text-destructive"
                        onClick={() => void handleDelete(row.name)}
                        title={m.mcpRowDelete.replace("{name}", row.name)}
                        aria-label={m.mcpRowDelete.replace("{name}", row.name)}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <Plug className="h-4 w-4" />
              {isNew ? m.formNew : editingName ? m.formEdit : m.formPlaceholder}
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 space-y-3">
            {!isNew && !editingName ? (
              <p className="text-sm text-muted-foreground">{m.formPlaceholder}</p>
            ) : (
              <>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">{m.name}</label>
                  <Input
                    className="h-8 text-xs font-mono"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    disabled={!isNew && Boolean(editingName)}
                    placeholder="my-server"
                  />
                </div>
                <label className="flex items-center gap-2 text-xs cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formEnabled}
                    onChange={(e) => setFormEnabled(e.target.checked)}
                    className="rounded border-border"
                  />
                  {m.enabled}
                </label>
                <p className="text-xs text-muted-foreground leading-snug">{m.transportSaveHint}</p>
                <div>
                  <p className="text-xs text-muted-foreground mb-1.5">{m.saveUsesTransport}</p>
                  <div className="flex flex-row flex-wrap gap-2 items-center">
                    <Button
                      size="xs"
                      type="button"
                      outlined={transport !== "stdio"}
                      className={cn(
                        "!inline-flex !flex-row items-center justify-center font-medium",
                        "h-8 min-w-[5.25rem] px-3 text-xs whitespace-nowrap break-normal",
                        "[writing-mode:horizontal-tb] w-auto",
                        transport === "stdio" && "ring-1 ring-primary/60",
                      )}
                      onClick={() => setTransport("stdio")}
                    >
                      {m.transportStdio}
                    </Button>
                    <Button
                      size="xs"
                      type="button"
                      outlined={transport !== "http"}
                      className={cn(
                        "!inline-flex !flex-row items-center justify-center font-medium",
                        "h-8 min-w-[5.25rem] px-3 text-xs whitespace-nowrap break-normal",
                        "[writing-mode:horizontal-tb] w-auto",
                        transport === "http" && "ring-1 ring-primary/60",
                      )}
                      onClick={() => setTransport("http")}
                    >
                      {m.transportHttp}
                    </Button>
                  </div>
                </div>
                <div className="space-y-2 rounded-md border border-border/70 p-3 bg-muted/10">
                  <p className="text-[11px] font-medium text-muted-foreground tracking-wide">
                    {m.transportStdio}
                  </p>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">{m.command}</label>
                    <Input
                      className="h-8 text-xs font-mono"
                      value={formCommand}
                      onChange={(e) => setFormCommand(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">{m.argsJson}</label>
                    <textarea
                      className="w-full min-h-[72px] rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
                      value={formArgsJson}
                      onChange={(e) => setFormArgsJson(e.target.value)}
                    />
                  </div>
                </div>
                <div className="space-y-2 rounded-md border border-border/70 p-3 bg-muted/10">
                  <p className="text-[11px] font-medium text-muted-foreground tracking-wide">
                    {m.transportHttp}
                  </p>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">{m.url}</label>
                    <Input
                      className="h-8 text-xs font-mono"
                      value={formUrl}
                      onChange={(e) => setFormUrl(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">{m.headersJson}</label>
                    <textarea
                      className="w-full min-h-[56px] rounded-md border border-border bg-background px-2 py-1.5 text-xs font-mono"
                      value={formHeadersJson}
                      onChange={(e) => setFormHeadersJson(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">{m.authOptional}</label>
                    <Input
                      className="h-8 text-xs font-mono"
                      value={formAuth}
                      onChange={(e) => setFormAuth(e.target.value)}
                      placeholder="oauth"
                    />
                  </div>
                </div>
                <Button
                  size="xs"
                  type="button"
                  className="!inline-flex !flex-row items-center justify-center whitespace-nowrap break-normal h-8 min-w-[4.5rem] px-5 text-xs [writing-mode:horizontal-tb] w-auto"
                  onClick={() => void handleSave()}
                >
                  {m.save}
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
