import { chromium, expect } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";

const browser = await chromium.launch();
try {
  const context = await browser.newContext({
    viewport: { width: 641, height: 321 },
  });
  const login = await context.request.post(
    "http://127.0.0.1:3000/api/auth/login",
    {
      headers: { Origin: "http://127.0.0.1:3000" },
      data: {
        email: "nexus-smoke-publication-20261024a@example.com",
        password: "synthetic-publication-password",
      },
    },
  );
  expect(login.status()).toBe(200);
  const page = await context.newPage();
  await page.goto(
    "http://127.0.0.1:3003/chat/b1a130be-c1b9-4ef2-aa58-d1df47bfe6ce",
  );
  await expect(page.getByLabel("Message Aster", { exact: true })).toBeVisible();
  const timeline = await page.locator(".chat-scroll").boundingBox();
  expect(timeline.height).toBeGreaterThanOrEqual(159);
  await page.getByLabel("Message Aster", { exact: true }).focus();
  await expect(
    page.getByLabel("Message Aster", { exact: true }),
  ).toBeInViewport();
  await expect(page.getByLabel("Message Aster", { exact: true })).toBeFocused();
  await page.getByLabel("Message Aster", { exact: true }).press("Tab");
  await expect(
    page.getByRole("button", { name: "Attach a document", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Open navigation", exact: true })
    .click();
  const sidebar = page.locator(".sidebar");
  const geometry = await sidebar.evaluate((e) => ({
    height: e.clientHeight,
    scrollHeight: e.scrollHeight,
    overflow: getComputedStyle(e).overflowY,
    bottom: e.getBoundingClientRect().bottom,
  }));
  console.log(JSON.stringify({ timeline, sidebar: geometry }));
  await page
    .getByRole("button", { name: "Log out", exact: true })
    .scrollIntoViewIfNeeded();
  await expect(
    page.getByRole("button", { name: "Log out", exact: true }),
  ).toBeInViewport();
  await page.screenshot({
    path: "artifacts/prepublication/short-window-navigation.png",
  });
  await page.locator('.sidebar a[href="/settings"]').click();
  await page
    .getByRole("button", { name: "Close navigation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .scrollIntoViewIfNeeded();
  await expect(
    page.getByRole("button", { name: "Save preferences", exact: true }),
  ).toBeInViewport();
  const build =
    process.env.NEXUS_LAYOUT_PRODUCTION === "true"
      ? (await readFile("apps/web/.next-e2e/BUILD_ID", "utf8")).trim()
      : null;
  await writeFile(
    "artifacts/prepublication/short-window-layout.json",
    JSON.stringify(
      {
        timeline,
        sidebar: geometry,
        logoutReachable: true,
        settingsReachable: true,
        productionBuild: build,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
