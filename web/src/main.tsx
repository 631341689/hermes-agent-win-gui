import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App";
import { KnowledgeTasksProvider } from "./contexts/KnowledgeTasksContext";
import { SystemActionsProvider } from "./contexts/SystemActions";
import { I18nProvider } from "./i18n";
import { exposePluginSDK } from "./plugins";
import { ThemeProvider } from "./themes";

// Expose the plugin SDK before rendering so plugins loaded via <script>
// can access React, components, etc. immediately.
exposePluginSDK();

async function bootstrap() {
  // Build-time: set VITE_MCP_MOCK=1 when running `npm run build` so
  // `hermes dashboard` (production bundle in web_dist) can mock /api/mcp/* locally.
  // Omit the variable for normal production builds.
  if (import.meta.env.VITE_MCP_MOCK === "1") {
    const { worker } = await import("./mocks/browser");
    await worker.start({
      onUnhandledRequest: "bypass",
      serviceWorker: { url: "/mockServiceWorker.js" },
    });
  }
}

void bootstrap().then(() => {
  createRoot(document.getElementById("root")!).render(
    <BrowserRouter>
      <I18nProvider>
        <ThemeProvider>
          <SystemActionsProvider>
            <KnowledgeTasksProvider>
              <App />
            </KnowledgeTasksProvider>
          </SystemActionsProvider>
        </ThemeProvider>
      </I18nProvider>
    </BrowserRouter>,
  );
});
