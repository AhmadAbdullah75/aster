import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("CTX-01/02/03/04/05 real Gemini handles seeded 60-message tool history, summary and independent thread", async ({
  page,
}) => {
  test.skip(
    process.env.NEXUS_LIVE_PREPUBLICATION !== "true",
    "Explicit real-provider opt-in and active quota watcher required.",
  );
  test.setTimeout(330_000);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Context");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-context-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-context-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  const user = await (await page.request.get("/api/me")).json();
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const result = JSON.parse(
    execFileSync(python, ["tests/e2e/live_context_fixture.py", user.id], {
      encoding: "utf8",
      timeout: 290_000,
    }).trim(),
  );
  await page.goto(`/chat/${result.thread_id}`);
  await expect(page.locator(".message")).toHaveCount(62);
  await expect(page.locator(".message.assistant").last()).toContainText("84");
  const early = page
    .locator(".message.user")
    .filter({ hasText: "GARDEN-SILVER-47" });
  await early.scrollIntoViewIfNeeded();
  await expect(early).toBeVisible();
  await page.screenshot({
    path: "artifacts/prepublication/CTX-02-full-history.png",
    fullPage: false,
  });
  await page.goto(`/chat/${result.new_thread_id}`);
  await expect(page.locator(".message")).toHaveCount(2);
  await expect(page.locator(".message.assistant")).not.toContainText(
    "GARDEN-SILVER-47",
  );
});
