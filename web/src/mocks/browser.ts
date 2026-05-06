import { setupWorker } from "msw/browser";

import { mcpHandlers } from "./mcpHandlers";
import { skillZipHandlers } from "./skillZipHandlers";

export const worker = setupWorker(...mcpHandlers, ...skillZipHandlers);
