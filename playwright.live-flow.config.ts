import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

const live =
  process.env.NEXUS_LIVE_PREPUBLICATION === "true" &&
  process.env.NEXUS_LIVE_FLOW === "true";
export default defineConfig({
  ...base,
  testMatch: "prepublication-flow-live.spec.ts",
  outputDir: "artifacts/prepublication/live-flow-traces",
  timeout: 1_800_000,
  retries: 0,
  // Functional failures must not hide later scenarios. The independent quota
  // watcher/guard still terminates the entire run on the first real quota error.
  maxFailures: 0,
  use: { ...base.use, viewport: { width: 1440, height: 1000 } },
  webServer: live
    ? [
        {
          command: "python -m uv run python tests/e2e/serve_workspace.py",
          url: "http://127.0.0.1:3001",
          reuseExistingServer: false,
          timeout: 150_000,
          env: {
            NEXUS_E2E_PRODUCTION: "true",
            NEXUS_E2E_QUEUE_ONLY: "true",
            NEXUS_E2E_REAL_PROVIDER: "true",
            NEXUS_LIVE_PREPUBLICATION: "true",
            NEXUS_LIVE_FLOW: "true",
          },
        },
      ]
    : undefined,
});
