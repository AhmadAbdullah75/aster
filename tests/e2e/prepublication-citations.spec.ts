import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import path from "node:path";

const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
function seed(scenario: string, userId: string) {
  return JSON.parse(
    execFileSync(python, ["tests/e2e/citation_fixture.py", scenario, userId], {
      encoding: "utf8",
      timeout: 30_000,
    }).trim(),
  );
}
async function account(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Citation");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-citation-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-citation-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return (await (await page.request.get("/api/me")).json()).id;
}

test("CIT-04/06 RAG-15 invalid references are inert and deleted source fails honestly", async ({
  page,
}) => {
  const user = await account(page);
  const data = seed("invalid", user);
  await page.goto(`/chat/${data.thread_id}`);
  await expect(page.locator(".message.assistant")).toContainText("[99]");
  await expect(page.locator(".message.assistant a")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Source ↗", exact: true }),
  ).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toContainText(
    "[source unavailable]",
  );
  const doc = await (await page.request.get("/api/documents")).json();
  const deleted = await page.request.delete(
    `/api/documents/${data.document_id}?version=${doc[0].version}`,
    { headers: { Origin: "http://127.0.0.1:3001" } },
  );
  expect(deleted.ok()).toBeTruthy();
  await page.getByRole("button", { name: "Source ↗", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Source unavailable");
  await expect(page.getByRole("dialog")).toContainText(
    "This source was deleted or is no longer available",
  );
  await page.screenshot({
    path: "artifacts/prepublication/CIT-04-deleted.png",
  });
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
  const after = seed("deleted", user);
  await page.goto(`/chat/${after.thread_id}`);
  await expect(page.locator(".message.assistant")).toContainText(
    "No current document evidence",
  );
  await expect(page.locator(".source-chip")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Source ↗", exact: true }),
  ).toHaveCount(0);
});

test("CIT-11 grounding failure leaves stale proposal and no approval card or task", async ({
  page,
}) => {
  const user = await account(page);
  const data = seed("groundfail", user);
  await page.goto(`/chat/${data.thread_id}`);
  await expect(
    page.getByRole("button", { name: "Prepare retry", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(0);
  const history = await (
    await page.request.get(`/api/conversations/${data.thread_id}/history`)
  ).json();
  expect(history.runs[0].status).toBe("failed");
  expect(history.proposals).toHaveLength(1);
  expect(history.proposals[0].status).toBe("stale");
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
  await page.screenshot({
    path: "artifacts/prepublication/CIT-11-no-card.png",
  });
});
