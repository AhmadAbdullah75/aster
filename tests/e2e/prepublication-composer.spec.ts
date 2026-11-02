import { test, expect } from "./isolation";
import type { Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

test.skip(
  process.env.NEXUS_E2E_QUEUE_ONLY !== "true",
  "Explicit isolated queue-only API required; no external provider calls.",
);

async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Composer");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-composer-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-composer-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
}
async function stop(page: Page) {
  await page
    .getByRole("button", { name: "Stop generation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Send message", exact: true }),
  ).toBeVisible();
}

test("CHT-01/02/03/07/10/11 suggestions, whitespace, newline and exact Unicode/code send", async ({
  page,
}) => {
  await account(page);
  const input = page.getByLabel("Message Aster", { exact: true });
  const send = page.getByRole("button", { name: "Send message", exact: true });
  await expect(send).toBeDisabled();
  await input.fill("   ");
  await expect(send).toBeDisabled();
  await page
    .getByRole("button", { name: /Explore an idea Help me think/ })
    .click();
  await expect(input).toHaveValue(
    "Help me think through an idea and ask me useful questions.",
  );
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
  expect(await (await page.request.get("/api/notes")).json()).toEqual([]);
  expect(await (await page.request.get("/api/conversations")).json()).toEqual(
    [],
  );
  await input.fill("First line");
  await input.press("Shift+Enter");
  await expect(input).toHaveValue("First line\n");
  expect(await (await page.request.get("/api/conversations")).json()).toEqual(
    [],
  );
  const message = "```python\nprint('hello')\n```\nاردو میں جواب — 🧭";
  await input.fill(message);
  await input.press("Enter");
  await expect(
    page.getByRole("button", { name: "Stop generation", exact: true }),
  ).toBeVisible();
  const thread = page.url().split("/").at(-1);
  const history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  expect(history.messages[0].content).toBe(message);
  expect(history.runs).toHaveLength(1);
  expect(history.runs[0].status).toBe("queued");
  await stop(page);
});

test("CHT-04/05/06 real API length boundary and worker context-budget error preserve text", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await account(page);
  const input = page.getByLabel("Message Aster", { exact: true });
  const accepted = "a".repeat(40000);
  await input.fill(accepted);
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Stop generation", exact: true }),
  ).toBeVisible();
  let thread = page.url().split("/").at(-1);
  expect(
    (
      await (
        await page.request.get(`/api/conversations/${thread}/history`)
      ).json()
    ).messages[0].content,
  ).toBe(accepted);
  await stop(page);
  const oversized = "b".repeat(40001);
  await input.fill(oversized);
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.locator(".alert.error").filter({ hasText: /40000|40,000/ }),
  ).toBeVisible();
  await expect(input).toHaveValue(oversized);
  await page
    .getByRole("button", { name: "Dismiss error", exact: true })
    .click();
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.waitForURL((url) => url.pathname !== `/chat/${thread}`);
  const tokenHeavy = "🧭".repeat(10000);
  await input.fill(tokenHeavy);
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Stop generation", exact: true }),
  ).toBeVisible();
  thread = page.url().split("/").at(-1);
  execFileSync(path.resolve(".venv/Scripts/python.exe"), [
    "tests/e2e/stream_fixture.py",
    "run",
    thread!,
  ]);
  await expect(page.locator(".alert.error")).toContainText(
    /exceeds the context budget/,
  );
  await page
    .getByRole("button", { name: "Prepare retry", exact: true })
    .click();
  await expect(input).toHaveValue(tokenHeavy);
});

test("CHT-08/09 rapid repeated send and stale second-tab conflict create one writer", async ({
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
  // Hold the second tab's pre-write snapshot so it intentionally remains stale.
  await other.route("**/api/conversations/*/history", async (route) => {
    await route.fulfill({ json: { messages: [], runs: [], proposals: [] } });
  });
  await page
    .getByLabel("Message Aster", { exact: true })
    .fill("One writer only");
  let release!: () => void;
  const hold = new Promise<void>((resolve) => {
    release = resolve;
  });
  let posts = 0;
  await page.route("**/api/conversations/*/runs", async (route) => {
    posts++;
    await hold;
    await route.continue();
  });
  const send = page.getByRole("button", { name: "Send message", exact: true });
  await send.click({ clickCount: 2 });
  await expect(send).toBeDisabled();
  release();
  await expect(
    page.getByRole("button", { name: "Stop generation", exact: true }),
  ).toBeVisible();
  expect(posts).toBe(1);
  const draft = "Keep this conflicting draft";
  await other.getByLabel("Message Aster", { exact: true }).fill(draft);
  await other
    .getByRole("button", { name: "Send message", exact: true })
    .click();
  await expect(other.locator(".alert.error")).toContainText(
    /already has an active run/,
  );
  await expect(other.getByLabel("Message Aster", { exact: true })).toHaveValue(
    draft,
  );
  const thread = url.split("/").at(-1);
  const history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  expect(history.runs).toHaveLength(1);
  expect(history.messages).toHaveLength(1);
  await stop(page);
  await other.close();
});
