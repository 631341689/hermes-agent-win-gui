/**
 * MSW handlers for ``POST /api/skills/install-zip`` when ``VITE_MCP_MOCK=1``.
 * Filename tricks (dev-only): ``__bad`` → layout error, ``__block`` → policy blocked.
 */
import { http, HttpResponse } from "msw";

export const skillZipHandlers = [
  http.get("/api/skills/categories", () =>
    HttpResponse.json({ categories: ["custom", "devops", "mlops"] }),
  ),

  http.post("/api/skills/install-zip", async ({ request }) => {
    let fd: FormData;
    try {
      fd = await request.formData();
    } catch {
      return HttpResponse.json({ ok: false, detail: "Invalid form data", errors: ["bad_form"] }, {
        status: 400,
      });
    }
    const file = fd.get("file");
    const fn =
      file && typeof file === "object" && "name" in file && typeof (file as File).name === "string"
        ? (file as File).name
        : "";

    if (fn.includes("__bad")) {
      return HttpResponse.json({
        ok: false,
        detail: "Mock: ZIP layout invalid (filename contains __bad).",
        errors: ["mock_bad_layout"],
      });
    }

    if (fn.includes("__block")) {
      return HttpResponse.json({
        ok: false,
        blocked_reason: "Mock policy blocked (filename contains __block).",
        detail: "Mock policy blocked (filename contains __block).",
        errors: ["policy_blocked"],
        scan: {
          verdict: "dangerous",
          summary: "mock scanner",
          findings_count: 2,
          report_lines: ["mock finding A", "mock finding B"],
        },
      });
    }

    const cat = String(fd.get("category") ?? "").trim();
    const path = cat ? `${cat}/mock-uploaded-skill` : "mock-uploaded-skill";

    return HttpResponse.json({
      ok: true,
      skill_name: "mock-uploaded-skill",
      installed_path: path,
      scan: {
        verdict: "safe",
        summary: "mock scan OK",
        findings_count: 0,
        report_lines: [],
      },
      reload_hint:
        "Mock install only — skills list will not change until you use the real dashboard API.",
    });
  }),
];
