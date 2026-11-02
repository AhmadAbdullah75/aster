import { test, expect } from "./isolation";
import type { Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test.skip(
  process.env.NEXUS_E2E_QUEUE_ONLY !== "true",
  "Explicit queue-only isolated API required; no embedding/model calls.",
);
const python = path.resolve(".venv/Scripts/python.exe");
const fixture = (...args: string[]) =>
  execFileSync(python, ["tests/e2e/source_scope_fixture.py", ...args], {
    encoding: "utf8",
  });
async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page.getByLabel("Your name", { exact: true }).fill("Publication Scope");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-scope-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-scope-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return (await (await page.request.get("/api/me")).json()).id as string;
}

test("MOD-07 31 selected documents rejected by real API, draft and source scope retained", async ({
  page,
}) => {
  const user = await account(page);
  const docs = JSON.parse(fixture("seed", user)) as {
    id: string;
    filename: string;
  }[];
  await page.reload();
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  for (const doc of docs)
    await page
      .getByRole("checkbox", { name: new RegExp(doc.filename) })
      .check();
  await page
    .getByLabel("Assistant mode", { exact: true })
    .selectOption("documents");
  const message = "Check this selected scope";
  await page.getByLabel("Message Aster", { exact: true }).fill(message);
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.locator(".alert.error")).toContainText(/at most 30/);
  await expect(page.getByLabel("Message Aster", { exact: true })).toHaveValue(
    message,
  );
  const threads = await (await page.request.get("/api/conversations")).json();
  const history = await (
    await page.request.get(`/api/conversations/${threads[0].id}/history`)
  ).json();
  expect(history.runs).toEqual([]);
  expect(history.messages).toEqual([]);
  await expect(
    page.getByRole("button", { name: "31 sources", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear source selection", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Sources", exact: true }),
  ).toBeVisible();
});

test("MOD-08/09 selected processing and failed sources block send and can be cleared", async ({
  page,
}) => {
  const user = await account(page);
  const docs = JSON.parse(fixture("seed", user)) as {
    id: string;
    filename: string;
  }[];
  await page.reload();
  await page.getByRole("button", { name: "Sources", exact: true }).click();
  const selected = page.getByRole("checkbox", {
    name: new RegExp(docs[0].filename),
  });
  await selected.check();
  await page
    .getByLabel("Message Aster", { exact: true })
    .fill("Wait for this source");
  fixture("indexing", user, docs[0].id);
  await expect(
    page.getByRole("button", { name: "Send message", exact: true }),
  ).toBeDisabled({ timeout: 10_000 });
  await expect(
    page.getByText(
      "Preparing attached documents. Open Sources to check progress or remove a selection.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByLabel("Message Aster", { exact: true }).press("Enter");
  expect(await (await page.request.get("/api/conversations")).json()).toEqual(
    [],
  );
  fixture("failed", user, docs[0].id);
  await expect(
    page.getByText("Synthetic extraction failure. Retry indexing.", {
      exact: true,
    }),
  ).toBeVisible({ timeout: 10_000 });
  await expect(
    page.getByRole("button", { name: "Send message", exact: true }),
  ).toBeDisabled();
  await selected.uncheck();
  await expect(
    page.getByRole("button", { name: "Send message", exact: true }),
  ).toBeEnabled();
});

test("MOD-12 upload failure visible and later chat send still works", async ({
  page,
}) => {
  await account(page);
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "POST")
      await route.fulfill({
        status: 500,
        json: { detail: "Upload unavailable. Please retry." },
      });
    else await route.continue();
  });
  await page
    .locator('input[type="file"]')
    .setInputFiles({
      name: "synthetic.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Synthetic publication upload failure fixture."),
    });
  await expect(page.locator(".alert.error")).toContainText(
    "Upload unavailable.",
  );
  await page
    .getByLabel("Message Aster", { exact: true })
    .fill("Chat after upload failure");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByText("Chat after upload failure", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Stop generation", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Stop generation", exact: true })
    .click();
});
