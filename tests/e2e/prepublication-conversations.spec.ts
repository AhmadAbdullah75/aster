import { test, expect } from "./isolation";
import type { Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication History");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-history-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-history-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
}

test("CNV-05/06 loading and case-insensitive partial/no-match search", async ({
  page,
}) => {
  await account(page);
  for (const title of ["Quartz Finch planning", "Cedar Lantern review"]) {
    const created = await page.request.post("/api/conversations", {
      headers: { origin: "http://127.0.0.1:3001" },
      data: { title },
    });
    expect(created.ok()).toBe(true);
  }
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(/\/api\/conversations(?:\?.*)?$/, async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response });
  });
  try {
    await page.reload();
    await expect(
      page.getByText("Loading saved conversations…", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Your conversations will appear here.", { exact: true }),
    ).not.toBeVisible();
  } finally {
    release();
  }
  await expect(
    page.getByRole("link", { name: "Quartz Finch planning", exact: true }),
  ).toBeVisible();
  const search = page.getByLabel("Search conversations");
  for (const term of ["Finch", "QUARTZ"]) {
    await search.fill(term);
    await expect(page.locator(".conversation-list a")).toHaveCount(1);
    await expect(
      page.getByRole("link", { name: "Quartz Finch planning", exact: true }),
    ).toBeVisible();
  }
  await search.fill("no-matching-synthetic-title");
  await expect(
    page.getByText("No matching conversations.", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: /Clear conversation filters/ })
    .click();
  await expect(page.locator(".conversation-list a")).toHaveCount(2);
});

test("CNV-08/11/16/17 title boundaries, canceled deletion, two-tab refresh and deleted URL", async ({
  page,
  context,
}) => {
  await account(page);
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.waitForURL("**/chat/*");
  const url = page.url();
  const other = await context.newPage();
  await other.goto(url);
  let title = "New conversation";
  for (const next of ["", "x", "z".repeat(300), "🧭 منصوبہ — Review"]) {
    await page.getByLabel(`Rename ${title}`, { exact: true }).click();
    await page.getByLabel("Title", { exact: true }).fill(next);
    const save = page.getByRole("button", {
      name: "Save conversation",
      exact: true,
    });
    if (!next) {
      await expect(save).toBeDisabled();
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
      await page
        .getByRole("button", { name: "Discard changes", exact: true })
        .click();
      continue;
    }
    const expected = next.slice(0, 200);
    await expect(page.getByLabel("Title", { exact: true })).toHaveValue(
      expected,
    );
    await save.click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await expect(
      page.getByRole("link", { name: expected, exact: true }),
    ).toBeVisible();
    title = expected;
  }
  await other.reload();
  await expect(
    other.getByRole("link", { name: title, exact: true }),
  ).toBeVisible();
  await page.getByLabel(`Delete ${title}`, { exact: true }).click();
  await page.getByRole("button", { name: "Keep it", exact: true }).click();
  await expect(
    page.getByRole("link", { name: title, exact: true }),
  ).toBeVisible();
  await page.getByLabel(`Delete ${title}`, { exact: true }).click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: title, exact: true }),
  ).not.toBeVisible();
  await other.reload();
  await expect(
    other.getByRole("heading", { name: "Conversation not found", exact: true }),
  ).toBeVisible();
  await expect(
    other.getByLabel("Message Aster", { exact: true }),
  ).not.toBeVisible();
  await other
    .getByRole("link", { name: "Back to conversations", exact: true })
    .click();
  await expect(
    other.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  await expect(
    other.getByRole("button", { name: "New conversation", exact: true }),
  ).toBeEnabled();
  await other.close();
});

test("CNV-19 220-message transcript renders and scrolls responsively", async ({
  page,
}) => {
  await account(page);
  const user = await (await page.request.get("/api/me")).json();
  const thread = execFileSync(
    path.resolve(".venv/Scripts/python.exe"),
    ["tests/e2e/conversation_fixture.py", "bulk", user.id],
    { encoding: "utf8" },
  ).trim();
  const started = Date.now();
  await page.goto(`/chat/${thread}`);
  await expect(page.locator(".transcript .message")).toHaveCount(220);
  expect(Date.now() - started).toBeLessThan(15_000);
  await page.locator(".chat-scroll").hover();
  await page.mouse.wheel(0, -100000);
  await expect(
    page.getByText("History turn 000", { exact: true }),
  ).toBeInViewport();
  await page.mouse.wheel(0, 100000);
  await expect(
    page.getByText("History turn 219", { exact: true }),
  ).toBeInViewport();
  await page.getByLabel("Search conversations").fill("Long transcript");
  await expect(page.locator(".conversation-list a")).toHaveCount(1);
  await page.screenshot({
    path: "artifacts/prepublication/CNV-19.png",
    fullPage: true,
  });
});

test("CNV-12/13/15 deleting pending approval removes canonical and graph state", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await account(page);
  const user = await (await page.request.get("/api/me")).json();
  const python = path.resolve(".venv/Scripts/python.exe");
  const thread = execFileSync(
    python,
    ["tests/e2e/conversation_fixture.py", "pending", user.id],
    { encoding: "utf8" },
  ).trim();
  const counts = () =>
    JSON.parse(
      execFileSync(
        python,
        ["tests/e2e/conversation_fixture.py", "counts", thread],
        { encoding: "utf8" },
      ),
    );
  await page.goto(`/chat/${thread}`);
  await expect(
    page.getByText("Must never be written after deletion", { exact: true }),
  ).toBeVisible();
  const history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  expect(history.proposals).toHaveLength(1);
  const before = counts();
  expect(before.messages).toBeGreaterThan(0);
  expect(before.events).toBeGreaterThan(0);
  expect(before.checkpoints).toBeGreaterThan(0);
  await page
    .getByLabel("Delete Pending deletion review", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page).toHaveURL(/\/chat$/);
  const after = counts();
  expect(Object.values(after).every((count) => count === 0)).toBe(true);
  const decision = await page.request.post(
    `/api/proposals/${history.proposals[0].id}/decision`,
    {
      headers: { origin: "http://127.0.0.1:3001" },
      data: { approve: true, version: history.proposals[0].version },
    },
  );
  expect(decision.status()).toBe(404);
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
  await test.info().attach("canonical-graph-cleanup", {
    body: JSON.stringify({ before, after }),
    contentType: "application/json",
  });
});
