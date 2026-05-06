import { describe, it, expect } from "vitest";
import { parseMcpInstallCommand, splitCommandLine } from "./parseMcpInstallCommand";

describe("splitCommandLine", () => {
  it("splits on spaces", () => {
    expect(splitCommandLine('npx -y @foo/bar')).toEqual(["npx", "-y", "@foo/bar"]);
  });

  it("respects double quotes", () => {
    expect(splitCommandLine('npx -y "@scope/pkg" /tmp')).toEqual(["npx", "-y", "@scope/pkg", "/tmp"]);
  });
});

describe("parseMcpInstallCommand", () => {
  it("parses npx stdio", () => {
    const r = parseMcpInstallCommand('npx -y @modelcontextprotocol/server-filesystem /tmp');
    expect(r).toEqual({
      transport: "stdio",
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    });
  });

  it("parses uvx", () => {
    const r = parseMcpInstallCommand("uvx mcp-server-fetch");
    expect(r).toEqual({
      transport: "stdio",
      command: "uvx",
      args: ["mcp-server-fetch"],
    });
  });

  it("uses first non-empty line", () => {
    const r = parseMcpInstallCommand("\n\n  deno run -A script.ts  \n");
    expect(r).toEqual({ transport: "stdio", command: "deno", args: ["run", "-A", "script.ts"] });
  });

  it("parses bare https URL", () => {
    const r = parseMcpInstallCommand("https://example.com/mcp");
    expect(r).toEqual({ transport: "http", url: "https://example.com/mcp" });
  });

  it("parses URL with trailing path only", () => {
    const r = parseMcpInstallCommand("https://host.run.tools/mcp/sse");
    expect(r).toEqual({ transport: "http", url: "https://host.run.tools/mcp/sse" });
  });

  it("returns error for empty", () => {
    expect(parseMcpInstallCommand("   \n  ")).toEqual({ error: "empty" });
  });
});
