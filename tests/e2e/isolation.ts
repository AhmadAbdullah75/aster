import { test as base, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

// Each case owns a fresh disposable database state. Leftover queued work from a
// previous case must not be claimed by its deterministic one-shot worker.
// The helper verifies nexus_e2e before resetting anything; native data is separate.
export const test = base.extend<{ rateIsolation: void }>({
  rateIsolation: [
    async ({}, use) => {
      execFileSync(
        path.resolve(
          ".venv",
          process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
        ),
        ["tests/e2e/reset_limits.py"],
      );
      await use();
    },
    { auto: true },
  ],
});
export { expect };
