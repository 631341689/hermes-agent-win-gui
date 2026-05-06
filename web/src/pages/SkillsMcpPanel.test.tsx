import { describe, it, expect, vi, beforeAll, afterEach, afterAll } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { setupServer } from "msw/node";
import { I18nProvider } from "@/i18n";
import { SkillsMcpPanel } from "@/pages/SkillsMcpPanel";
import { mcpHandlers } from "@/mocks/mcpHandlers";
import { skillZipHandlers } from "@/mocks/skillZipHandlers";

const server = setupServer(...mcpHandlers, ...skillZipHandlers);

beforeAll(() =>
  server.listen({
    onUnhandledRequest: (req, print) => {
      if (req.url.includes("/api/mcp")) print.warning();
    },
  }),
);
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel() {
  const showToast = vi.fn();
  render(
    <I18nProvider>
      <SkillsMcpPanel showToast={showToast} />
    </I18nProvider>,
  );
  return { showToast };
}

describe("SkillsMcpPanel", () => {
  it("loads and lists mock MCP servers", async () => {
    renderPanel();
    expect(await screen.findByText("demo_fs")).toBeInTheDocument();
    expect(screen.getByText("demo_http")).toBeInTheDocument();
    expect(screen.getByText("demo_oauth")).toBeInTheDocument();
  });

  it("runs test connection and reports success", async () => {
    const user = userEvent.setup();
    const { showToast } = renderPanel();
    await screen.findByText("demo_fs");
    await user.click(screen.getByTestId("mcp-test-demo_fs"));
    await waitFor(() => {
      expect(showToast).toHaveBeenCalledWith(
        expect.stringMatching(/2/),
        "success",
      );
    });
  });
});
