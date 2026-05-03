/**
 * `chmod +x` is a no-op on Windows and breaks `npm run build` when invoked
 * literally from package.json (dashboard's `_tui_build_needed` path).
 */
import { execSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

if (process.platform !== "win32") {
  execSync("chmod +x dist/entry.js", { stdio: "inherit", cwd: root });
}
