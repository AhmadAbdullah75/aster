import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import path from "node:path";

test("IDX-04/05 missing worker key fails clearly, restored real free key plus Retry indexes", async ({
  page,
}) => {
  test.skip(
    process.env.NEXUS_LIVE_PREPUBLICATION !== "true",
    "Explicit live embedding opt-in and quota watcher required.",
  );
  test.setTimeout(150_000);
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication key recovery");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-upload-key-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-key-recovery-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.waitForURL("**/documents");
  await expect(
    page.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({
    name: "key-recovery.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Cedar Lantern key-recovery evidence. Acceptance owner is Mira.",
    ),
  });
  await expect(
    page.getByRole("heading", { name: "key-recovery.txt", exact: true }),
  ).toBeVisible();
  const doc = (await (await page.request.get("/api/documents")).json())[0];
  execFileSync(python, ["tests/e2e/ingest_fixture.py", "missing-key", doc.id], {
    timeout: 30_000,
  });
  await page.reload();
  const card = page.locator(".resource-card").filter({
    has: page.getByRole("heading", { name: "key-recovery.txt", exact: true }),
  });
  await expect(card.getByRole("alert")).toContainText("GEMINI_API_KEY");
  await expect(card.getByText("failed", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Notes", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "New note", exact: true }),
  ).toBeEnabled();
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.waitForURL("**/documents");
  await expect(
    page.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  await card
    .getByRole("button", { name: "Retry indexing", exact: true })
    .click();
  execFileSync(python, ["tests/e2e/ingest_fixture.py", "live", doc.id], {
    timeout: 100_000,
  });
  await page.reload();
  await expect(card.getByText("ready", { exact: true })).toBeVisible();
  await expect(card).toContainText("gemini-embedding-2");
  await expect(card.getByRole("alert")).toHaveCount(0);
  await page.screenshot({
    path: "artifacts/prepublication/IDX-05-recovered.png",
    fullPage: true,
  });
});
