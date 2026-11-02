import { defineConfig } from "@playwright/test";
const production = process.env.NEXUS_E2E_PRODUCTION === "true";
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3001",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer:
    process.env.NEXUS_E2E_SUPERVISE === "true"
      ? [
          {
            command: "python -m uv run python tests/e2e/serve_workspace.py",
            url: "http://127.0.0.1:3001",
            reuseExistingServer: false,
            timeout: 150_000,
          },
        ]
      : [
          {
            command: "python -m uv run python tests/e2e/serve_api.py",
            url: "http://127.0.0.1:8001/health/ready",
            reuseExistingServer: !production,
            timeout: 120_000,
          },
          {
            command: production
              ? "pnpm --dir apps/web exec next start --hostname 127.0.0.1 --port 3001"
              : "pnpm --dir apps/web dev --port 3001",
            url: "http://127.0.0.1:3001",
            reuseExistingServer: !production,
            timeout: 120_000,
            env: {
              API_INTERNAL_URL: "http://127.0.0.1:8001",
              NEXUS_NEXT_DIR: production
                ? process.env.NEXUS_E2E_PRODUCTION_DIR || ".next"
                : ".next-e2e",
            },
          },
        ],
});
