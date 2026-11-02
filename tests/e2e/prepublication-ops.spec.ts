import { test, expect } from "./isolation";
import type { Page } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";

test.skip(
  process.env.NEXUS_E2E_SUPERVISE !== "true",
  "Dedicated restartable isolated workspace required.",
);
const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const fixture = (...args: string[]) =>
  execFileSync(python, args, { encoding: "utf8", timeout: 110_000 }).trim();
const worker = (...args: string[]) => spawn(python, args, { stdio: "ignore" });
function kill(child: ReturnType<typeof spawn>) {
  if (child.exitCode !== null) return;
  if (process.platform === "win32")
    execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
    });
  else child.kill("SIGKILL");
}
async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Operations");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-history-ops-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-operations-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return (await (await page.request.get("/api/me")).json()).id as string;
}
async function stream(page: Page, user: string, mode = "stream") {
  const thread = fixture("tests/e2e/stream_fixture.py", "seed", user);
  const child = worker("tests/e2e/stream_fixture.py", "run", thread, mode);
  await page.goto(`/chat/${thread}`);
  return { thread, child };
}

test("WRK-03 no worker keeps UI run queued, then fresh worker consumes it", async ({
  page,
}) => {
  test.setTimeout(80_000);
  await account(page);
  await page
    .getByLabel("Message Aster", { exact: true })
    .fill("Queued until worker starts");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByText("Waiting for a worker…", { exact: true }),
  ).toBeVisible();
  const thread = page.url().split("/").at(-1)!;
  await page.reload();
  await expect(
    page.getByText("Waiting for a worker…", { exact: true }),
  ).toBeVisible();
  const history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  expect(history.runs[0].status).toBe("queued");
  const child = worker("tests/e2e/stream_fixture.py", "run", thread, "fast");
  try {
    await expect(
      page.getByText("Recovered worker completed this fresh run.", {
        exact: true,
      }),
    ).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => child.exitCode).toBe(0);
  } finally {
    kill(child);
  }
});

test("WRK-04 restart actual API process during independent worker streaming", async ({
  page,
}) => {
  test.setTimeout(110_000);
  const user = await account(page);
  const { thread, child } = await stream(page, user);
  try {
    await expect(page.getByText(/Audit stream paragraph 000/)).toBeVisible({
      timeout: 30_000,
    });
    const restart = JSON.parse(
      fixture("tests/e2e/restart_workspace_fixture.py", "api"),
    );
    expect(restart.after).toBeGreaterThan(restart.before);
    await expect(page.getByText(/Audit stream paragraph 149/)).toBeVisible({
      timeout: 70_000,
    });
    await expect.poll(() => child.exitCode).toBe(0);
    const history = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(history.runs[0].status).toBe("completed");
    expect(history.messages).toHaveLength(2);
    await test.info().attach("actual-api-restart", {
      body: JSON.stringify(restart),
      contentType: "application/json",
    });
  } finally {
    kill(child);
  }
});

test("WRK-05 restart API and web while approval waits, then new worker resumes exactly once", async ({
  page,
}) => {
  test.setTimeout(130_000);
  const user = await account(page);
  const thread = fixture("tests/e2e/graph_fixture.py", "seed", user)
    .split(/\r?\n/)
    .at(-1)!;
  await page.goto(`/chat/${thread}`);
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toBeVisible();
  const restart = JSON.parse(
    fixture("tests/e2e/restart_workspace_fixture.py", "all"),
  );
  await page.reload();
  expect((await (await page.request.get("/api/me")).json()).id).toBe(user);
  await page
    .getByRole("button", { name: "Approve selection", exact: true })
    .click();
  fixture("tests/e2e/graph_fixture.py", "resume", thread);
  await page.reload();
  await expect(page.locator(".approval-card")).toHaveCount(0);
  expect(
    (
      await (
        await page.request.get(`/api/conversations/${thread}/history`)
      ).json()
    ).proposals.at(-1).status,
  ).toBe("completed");
  expect(await (await page.request.get("/api/tasks")).json()).toHaveLength(2);
  await test.info().attach("actual-workspace-restart", {
    body: JSON.stringify(restart),
    contentType: "application/json",
  });
});

test("WRK-01/02/07 real worker kill, natural lease expiry, saved partial and new worker recovery", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const user = await account(page);
  const { thread, child } = await stream(page, user);
  let next: ReturnType<typeof spawn> | undefined;
  try {
    await expect(page.getByText(/Audit stream paragraph 000/)).toBeVisible({
      timeout: 30_000,
    });
    const before = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    const samples = JSON.parse(
      fixture("tests/e2e/ops_fixture.py", "leases", before.runs[0].id),
    );
    expect(samples.length).toBeGreaterThanOrEqual(3);
    for (let index = 2; index < samples.length; index++)
      expect(
        samples[index].elapsed - samples[index - 1].elapsed,
      ).toBeGreaterThanOrEqual(1.4);
    kill(child);
    fixture("tests/e2e/ops_fixture.py", "recover", before.runs[0].id);
    await expect(page.locator(".alert.error")).toContainText(
      "Worker interrupted.",
    );
    await expect(
      page.getByText("Interrupted · partial response", { exact: true }),
    ).toBeVisible();
    const after = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(after.runs[0].status).toBe("failed");
    expect(
      after.messages[1].content.startsWith(before.messages[1].content),
    ).toBe(true);
    await page
      .getByRole("button", { name: "Prepare retry", exact: true })
      .click();
    await page
      .getByLabel("Message Aster", { exact: true })
      .fill("Fresh message after worker restart");
    await page
      .getByRole("button", { name: "Send message", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Stop generation", exact: true }),
    ).toBeVisible();
    next = worker("tests/e2e/stream_fixture.py", "run", thread, "fast");
    await expect(
      page.getByText("Recovered worker completed this fresh run.", {
        exact: true,
      }),
    ).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => next!.exitCode).toBe(0);
    await test.info().attach("real-lease-refresh", {
      body: JSON.stringify(samples),
      contentType: "application/json",
    });
  } finally {
    kill(child);
    if (next) kill(next);
  }
});

test("WRK-06 two worker processes claim queued jobs once", async ({ page }) => {
  test.setTimeout(90_000);
  const user = await account(page);
  const runs: string[] = [];
  for (let index = 0; index < 3; index++) {
    const thread = await (
      await page.request.post("/api/conversations", {
        headers: { origin: "http://127.0.0.1:3001" },
        data: { title: `Concurrent job ${index}` },
      })
    ).json();
    const response = await page.request.post(
      `/api/conversations/${thread.id}/runs`,
      {
        headers: { origin: "http://127.0.0.1:3001" },
        data: { message: "Process this synthetic job" },
      },
    );
    expect(response.status()).toBe(202);
    runs.push((await response.json()).id);
  }
  const workers = [
    worker("tests/e2e/ops_fixture.py", "worker", user),
    worker("tests/e2e/ops_fixture.py", "worker", user),
  ];
  try {
    for (const run of runs) {
      await expect
        .poll(
          async () =>
            (await (await page.request.get(`/api/runs/${run}`)).json()).status,
          { timeout: 35_000 },
        )
        .toBe("completed");
      const state = await (await page.request.get(`/api/runs/${run}`)).json();
      expect(state.attempts).toBe(1);
      const events = await (
        await page.request.get(`/api/runs/${run}/events`)
      ).text();
      expect(events.match(/event: run.started/g)).toHaveLength(1);
      expect(events.match(/event: run.completed/g)).toHaveLength(1);
    }
    for (const child of workers)
      await expect.poll(() => child.exitCode).toBe(0);
  } finally {
    workers.forEach(kill);
  }
});

test("WRK-08 actual 180-second run timeout keeps partial output and exposes retry", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const user = await account(page);
  const started = Date.now();
  const { thread, child } = await stream(page, user, "timeout");
  try {
    await expect(
      page.getByText(
        /Saved partial output before the controlled long provider wait/,
      ),
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".alert.error")).toContainText("Run timed out.", {
      timeout: 200_000,
    });
    expect(Date.now() - started).toBeGreaterThan(175_000);
    await expect.poll(() => child.exitCode).toBe(0);
    const history = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(history.runs[0].status).toBe("failed");
    expect(history.messages[1].interrupted).toBe(true);
    await expect(
      page.getByRole("button", { name: "Prepare retry", exact: true }),
    ).toBeVisible();
  } finally {
    kill(child);
  }
});

test("WRK-09 actual Gemini SDK request timeout against a hanging loopback endpoint", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const user = await account(page);
  const thread = fixture("tests/e2e/stream_fixture.py", "seed", user);
  const history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  const started = Date.now();
  const child = worker(
    "tests/e2e/ops_fixture.py",
    "sdk-hang",
    history.runs[0].id,
  );
  try {
    await page.goto(`/chat/${thread}`);
    await expect(page.locator(".alert.error")).toContainText(
      /timed out|timeout/i,
      { timeout: 155_000 },
    );
    expect(Date.now() - started).toBeGreaterThan(55_000);
    await expect.poll(() => child.exitCode).toBe(0);
    const after = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(after.runs[0].status).toBe("failed");
    await expect(
      page.getByRole("button", { name: "Prepare retry", exact: true }),
    ).toBeVisible();
  } finally {
    kill(child);
  }
});
