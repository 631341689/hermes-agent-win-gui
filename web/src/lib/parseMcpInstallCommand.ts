/**
 * Parse pasted "install command" lines (npx/uvx/node/…) or leading MCP HTTPS URLs
 * into Hermes ``mcp_servers`` stdio (command + args) or HTTP (url) fields.
 */

export type ParsedMcpInstall =
  | { transport: "stdio"; command: string; args: string[] }
  | { transport: "http"; url: string }
  | { error: "empty" | "bad_url" };

/** Split one line on whitespace; double-quoted segments stay one token. */
export function splitCommandLine(line: string): string[] {
  const s = line.trim();
  if (!s) return [];
  const parts: string[] = [];
  let cur = "";
  let inQuote = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === '"') {
      inQuote = !inQuote;
    } else if ((c === " " || c === "\t") && !inQuote) {
      if (cur.length) {
        parts.push(cur);
        cur = "";
      }
    } else {
      cur += c;
    }
  }
  if (cur.length) parts.push(cur);
  return parts;
}

function firstNonEmptyLine(text: string): string {
  const lines = text.split(/\r?\n/);
  for (const ln of lines) {
    const t = ln.trim();
    if (t) return t;
  }
  return "";
}

/**
 * Parse user paste into stdio command/args or HTTP url.
 *
 * HTTP: first line starts with ``https?://`` — the first URL token is used
 * (trailing text on the same line is ignored).
 *
 * stdio: shell-like split on the first non-empty line.
 */
export function parseMcpInstallCommand(raw: string): ParsedMcpInstall {
  const first = firstNonEmptyLine(raw);
  if (!first) {
    return { error: "empty" };
  }

  const trimmed = first.trim();
  const urlLead = trimmed.match(/^(https?:\/\/[^\s"'<>]+)/i);
  if (urlLead && /^https?:\/\//i.test(trimmed)) {
    const u = urlLead[1];
    try {
      new URL(u);
    } catch {
      return { error: "bad_url" };
    }
    return { transport: "http", url: u };
  }

  const tokens = splitCommandLine(first);
  if (tokens.length === 0) {
    return { error: "empty" };
  }

  const command = tokens[0];
  if (!command) {
    return { error: "empty" };
  }

  const args = tokens.slice(1);
  return { transport: "stdio", command, args };
}
