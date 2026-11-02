import { test, expect } from "./isolation";
import type { Page } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";

const python = path.resolve(".venv/Scripts/python.exe");
async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Recovery");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-recovery-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-recovery-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  const user = await (await page.request.get("/api/me")).json();
  const thread = execFileSync(
    python,
    ["tests/e2e/stream_fixture.py", "seed", user.id],
    { encoding: "utf8" },
  ).trim();
  const history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  return { thread, run: history.runs[0].id as string };
}

test("STR-02/03/04/05/06/09 offline recovery, reload, two tabs and close/reopen preserve one canonical reply", async ({
  page,
  context,
}) => {
  test.setTimeout(130_000);
  const { thread, run } = await account(page);
  const worker = spawn(python, ["tests/e2e/stream_fixture.py", "run", thread], {
    stdio: "ignore",
  });
  try {
    await page.goto(`/chat/${thread}`);
    await expect(page.getByText(/Audit stream paragraph 000/)).toBeVisible({
      timeout: 30_000,
    });
    await context.setOffline(true);
    await page.waitForTimeout(2500); // Deliberate network outage while the independent worker continues.
    await context.setOffline(false);
    await expect(page.getByText(/Audit stream paragraph 015/)).toBeVisible({
      timeout: 20_000,
    });
    const other = await context.newPage();
    await other.goto(`/chat/${thread}`);
    await expect(other.getByText(/Audit stream paragraph 015/)).toBeVisible();
    await page.reload();
    await expect(page.getByText(/Audit stream paragraph 020/)).toBeVisible({
      timeout: 15_000,
    });
    await expect(other.getByText(/Audit stream paragraph 020/)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator(".message.assistant")).toHaveCount(1);
    await expect(other.locator(".message.assistant")).toHaveCount(1);
    await other.close();
    await page.close();
    await expect.poll(() => worker.exitCode, { timeout: 65_000 }).toBe(0);
    const reopened = await context.newPage();
    await reopened.goto(`/chat/${thread}`);
    await expect(
      reopened.getByText(/Audit stream paragraph 149/),
    ).toBeVisible();
    const history = await (
      await reopened.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(history.runs).toHaveLength(1);
    expect(history.runs[0].status).toBe("completed");
    expect(history.messages).toHaveLength(2);
    const content = history.messages.find(
      (message: { role: string }) => message.role === "assistant",
    ).content as string;
    for (let number = 0; number < 150; number++)
      expect(
        content.split(
          `Audit stream paragraph ${String(number).padStart(3, "0")}.`,
        ),
      ).toHaveLength(2);
    const response = await reopened.request.get(`/api/runs/${run}/events`);
    expect(response.headers()["content-type"]).toContain("text/event-stream");
    expect(response.headers()["x-accel-buffering"]).toBe("no");
    const envelopes = (await response.text())
      .split("\n")
      .filter((line) => line.startsWith("data: "))
      .map((line) => JSON.parse(line.slice(6)));
    const seq = envelopes.map((event: { seq: number }) => event.seq);
    expect(seq).toEqual(
      Array.from({ length: seq.length }, (_, index) => index + 1),
    );
    const cursor = seq[Math.floor(seq.length / 2)];
    const replay = await (
      await reopened.request.get(`/api/runs/${run}/events?cursor=${cursor}`)
    ).text();
    const later = replay
      .split("\n")
      .filter((line) => line.startsWith("data: "))
      .map((line) => JSON.parse(line.slice(6)).seq);
    expect(later).toEqual(seq.filter((value: number) => value > cursor));
    await test
      .info()
      .attach("reconnect-events", {
        body: JSON.stringify({
          run,
          events: envelopes,
          cursor,
          replaySeq: later,
          messageCount: history.messages.length,
        }),
        contentType: "application/json",
      });
    await reopened.screenshot({
      path: "artifacts/prepublication/STR-02-recovered.png",
      fullPage: true,
    });
    await reopened.close();
  } finally {
    await context.setOffline(false);
    if (worker.exitCode === null) worker.kill();
  }
});

test("STR-07 queued stream stays open with heartbeats for over 60 seconds", async ({
  page,
}) => {
  test.setTimeout(100_000);
  const { thread, run } = await account(page);
  await page.goto(`/chat/${thread}`);
  const heartbeat = await page.evaluate(async (runId) => {
    const started = performance.now();
    const response = await fetch(`/api/runs/${runId}/events`);
    if (!response.body) throw new Error("Missing event stream");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let comments = 0;
    let done = false;
    while (performance.now() - started < 62000) {
      const next = await reader.read();
      if (next.done) {
        done = true;
        break;
      }
      comments += (
        decoder.decode(next.value, { stream: true }).match(/: heartbeat/g) || []
      ).length;
    }
    await reader.cancel();
    return {
      comments,
      prematurelyClosed: done,
      elapsed: performance.now() - started,
    };
  }, run);
  expect(heartbeat.prematurelyClosed).toBe(false);
  expect(heartbeat.elapsed).toBeGreaterThan(60000);
  expect(heartbeat.comments).toBeGreaterThanOrEqual(7);
  await page
    .getByRole("button", { name: "Stop generation", exact: true })
    .click();
  await test
    .info()
    .attach("idle-stream-heartbeats", {
      body: JSON.stringify(heartbeat),
      contentType: "application/json",
    });
});
