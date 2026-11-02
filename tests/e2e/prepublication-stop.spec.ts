import { test, expect } from "./isolation";
import type { Page } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";

test.skip(
  process.env.NEXUS_E2E_QUEUE_ONLY !== "true",
  "Explicit isolated queue-only API; deterministic worker only.",
);
const python = path.resolve(".venv/Scripts/python.exe");
async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page.getByLabel("Your name", { exact: true }).fill("Publication Stop");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-history-stop-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-stop-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return (await (await page.request.get("/api/me")).json()).id as string;
}
const fixture = (...args: string[]) =>
  execFileSync(python, args, { encoding: "utf8" })
    .trim()
    .split(/\r?\n/)
    .at(-1)!;

test("STP-02/06/07 cancel running tool twice then next message has valid tool pairs", async ({
  page,
}) => {
  test.setTimeout(100_000);
  const user = await account(page);
  const thread = fixture("tests/e2e/stream_fixture.py", "seed", user);
  const worker = spawn(
    python,
    ["tests/e2e/stream_fixture.py", "run", thread, "tool"],
    { stdio: "ignore" },
  );
  try {
    await page.goto(`/chat/${thread}`);
    await expect(
      page.getByText("Using calculator", { exact: true }),
    ).toBeVisible({ timeout: 30_000 });
    await page
      .getByRole("button", { name: "Stop generation", exact: true })
      .click({ clickCount: 2 });
    await expect(page.locator(".alert.error")).toContainText(
      "Generation stopped.",
    );
    await expect.poll(() => worker.exitCode, { timeout: 15_000 }).toBe(0);
    expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
    await page
      .getByLabel("Message Aster", { exact: true })
      .fill("Hello after cancellation");
    await page
      .getByRole("button", { name: "Send message", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Stop generation", exact: true }),
    ).toBeVisible();
    fixture("tests/e2e/stream_fixture.py", "run", thread, "after-cancel");
    await expect(
      page.getByText(
        "Follow-up after cancellation has valid tool-call history and completes successfully.",
        { exact: true },
      ),
    ).toBeVisible();
    const history = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(history.runs.map((run: { status: string }) => run.status)).toEqual([
      "canceled",
      "completed",
    ]);
    await page.screenshot({
      path: "artifacts/prepublication/STP-07.png",
      fullPage: true,
    });
  } finally {
    if (worker.exitCode === null) worker.kill();
  }
});

test("STP-03 stop pending approval invalidates card without writing tasks", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const user = await account(page);
  const thread = fixture("tests/e2e/conversation_fixture.py", "pending", user);
  await page.goto(`/chat/${thread}`);
  await expect(
    page.getByText("Must never be written after deletion", { exact: true }),
  ).toBeVisible();
  const before = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  await page
    .getByRole("button", { name: "Stop generation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).not.toBeVisible();
  const history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  expect(history.runs[0].status).toBe("canceled");
  expect(history.proposals[0].status).toBe("stale");
  const decision = await page.request.post(
    `/api/proposals/${before.proposals[0].id}/decision`,
    {
      headers: { origin: "http://127.0.0.1:3001" },
      data: { approve: true, version: before.proposals[0].version },
    },
  );
  expect(decision.status()).toBe(409);
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
});

test("STP-04 stop after committed approved write retains exact tasks and truthful outcome", async ({
  page,
}) => {
  test.setTimeout(100_000);
  const user = await account(page);
  const thread = fixture("tests/e2e/graph_fixture.py", "seed", user);
  await page.goto(`/chat/${thread}`);
  await page
    .getByRole("button", { name: "Approve selection", exact: true })
    .click();
  const worker = spawn(
    python,
    ["tests/e2e/graph_fixture.py", "resume", thread, "slow"],
    { stdio: "ignore" },
  );
  try {
    await expect(
      page.getByText(/These committed tasks remain saved/),
    ).toBeVisible({ timeout: 30_000 });
    const before = await (await page.request.get("/api/tasks")).json();
    expect(before).toHaveLength(2);
    await page
      .getByRole("button", { name: "Stop generation", exact: true })
      .click();
    await expect.poll(() => worker.exitCode, { timeout: 15_000 }).toBe(0);
    await page.reload();
    await expect(page.locator(".approval-card")).toHaveCount(0);
    expect(
      (
        await (
          await page.request.get(`/api/conversations/${thread}/history`)
        ).json()
      ).proposals.at(-1).status,
    ).toBe("completed");
    await expect(page.locator(".alert.error")).toContainText(
      "Generation stopped.",
    );
    expect(await (await page.request.get("/api/tasks")).json()).toEqual(before);
    await page.getByRole("link", { name: "Tasks", exact: true }).click();
    await expect(page.locator(".resource-card")).toHaveCount(2);
    await expect(
      page.getByRole("heading", { name: "Confirm scope", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Review launch", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: "artifacts/prepublication/STP-04.png",
      fullPage: true,
    });
  } finally {
    if (worker.exitCode === null) worker.kill();
  }
});
