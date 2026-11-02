import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  testMatch: "cross-browser.spec.ts",
  projects: [
    {
      name: "chrome",
      use: {
        browserName: "chromium",
        ...(process.env.NEXUS_CHROME_BINARY
          ? { launchOptions: { executablePath: process.env.NEXUS_CHROME_BINARY } }
          : { channel: "chrome" }),
      },
    },
    { name: "edge", use: { browserName: "chromium", channel: "msedge" } },
    { name: "firefox", use: { browserName: "firefox" } },
  ],
});
