import { test, expect } from "./isolation";
import { execFileSync, spawnSync } from "node:child_process";
import path from "node:path";
const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const origin = { Origin: "http://127.0.0.1:3001" };
async function account(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Approval Lifecycle");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-approval-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-approval-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return (await (await page.request.get("/api/me")).json()).id;
}
function graphSeed(user: string, action = "tasks.create", items?: unknown[]) {
  return execFileSync(
    python,
    [
      "tests/e2e/graph_fixture.py",
      "seed",
      user,
      action,
      ...(items ? [JSON.stringify(items)] : []),
    ],
    { encoding: "utf8", timeout: 30_000 },
  )
    .trim()
    .split(/\r?\n/)
    .at(-1)!;
}
function lifecycle(mode: string, user: string, thread?: string) {
  return JSON.parse(
    execFileSync(
      python,
      [
        "tests/e2e/approval_lifecycle_fixture.py",
        mode,
        user,
        ...(thread ? [thread] : []),
      ],
      { encoding: "utf8", timeout: 50_000 },
    ).trim(),
  );
}

for (const operation of ["update", "delete"]) {
  test(`APS-07/08 ${operation} proposal conflicts with competing target change`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const user = await account(page);
    const target = await (
      await page.request.post("/api/tasks", {
        headers: origin,
        data: { title: "Original target" },
      })
    ).json();
    const thread = graphSeed(user, `tasks.${operation}`, [
      {
        id: target.id,
        version: target.version,
        title: "Proposed target change",
      },
    ]);
    await page.goto(`/chat/${thread}`);
    await expect(
      page.getByRole("button", { name: "Approve selection", exact: true }),
    ).toBeVisible();
    if (operation === "update")
      expect(
        (
          await page.request.put(`/api/tasks/${target.id}`, {
            headers: origin,
            data: { title: "Competing manual edit", version: target.version },
          })
        ).ok(),
      ).toBeTruthy();
    else
      expect(
        (
          await page.request.delete(
            `/api/tasks/${target.id}?version=${target.version}`,
            { headers: origin },
          )
        ).ok(),
      ).toBeTruthy();
    await page
      .getByRole("button", { name: "Approve selection", exact: true })
      .click();
    await expect(page.locator(".alert.error")).toContainText(
        /changed|version|not found|unavailable/i,
    );
    const tasks = await (await page.request.get("/api/tasks")).json();
    if (operation === "update")
      expect(tasks[0].title).toBe("Competing manual edit");
    else expect(tasks).toEqual([]);
    await expect(
      page.getByRole("button", { name: "Approve selection", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `artifacts/prepublication/APS-target-${operation}.png`,
    });
  });
}

test("APS-12 project deletion invalidates pending approval and removes graph rows", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page),
    data = lifecycle("project", user);
  await page.goto(`/chat/${data.thread_id}`);
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toBeVisible();
  await page.goto("/projects");
  await page
    .getByRole("button", {
      name: "Delete Publication pending project",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Publication pending project",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(
    (
      await page.request.get(`/api/conversations/${data.thread_id}/history`)
    ).status(),
  ).toBe(404);
  expect(
    (
      await page.request.post(`/api/proposals/${data.proposal_id}/decision`, {
        headers: origin,
        data: { approve: true, version: 1 },
      })
    ).status(),
  ).toBe(404);
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
  expect(
    lifecycle("deleted-check", user, data.thread_id).deleted_graph_rows,
  ).toBe(0);
});

test("APS-15 global memory off rejects model write and leaves no review card", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page);
  await page.goto("/settings");
  await page
    .getByRole("checkbox", {
      name: "Allow Aster to read and propose saved memories",
      exact: true,
    })
    .uncheck();
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    page.getByText("Preferences saved", { exact: true }),
  ).toBeVisible();
  const data = lifecycle("memory-off", user);
  await page.goto(`/chat/${data.thread_id}`);
  await expect(page.locator(".message.assistant")).toContainText(
    "Memory is disabled",
  );
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(0);
  const history = await (
    await page.request.get(`/api/conversations/${data.thread_id}/history`)
  ).json();
  expect(history.proposals).toEqual([]);
  expect(history.runs[0].status).toBe("completed");
  expect(await (await page.request.get("/api/memories")).json()).toEqual([]);
});

test("APS-09 actual post-commit process exit and natural lease recovery replay saved outcome once", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const user = await account(page),
    thread = graphSeed(user);
  await page.goto(`/chat/${thread}`);
  await page
    .getByRole("button", { name: "Approve selection", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(0);
  const crashed = spawnSync(
    python,
    ["tests/e2e/approval_lifecycle_fixture.py", "crash", user, thread],
    { encoding: "utf8", timeout: 30_000 },
  );
  expect(crashed.status).toBe(91);
  expect(JSON.parse(crashed.stdout.trim()).committed).toBeTruthy();
  const before = await (await page.request.get("/api/tasks")).json();
  expect(before).toHaveLength(2);
  const replay = lifecycle("replay", user, thread);
  expect(replay.known_outcome).toBeTruthy();
  expect(replay.duplicates).toBeFalsy();
  const after = await (await page.request.get("/api/tasks")).json();
  expect(after.map((t: { id: string }) => t.id).sort()).toEqual(
    before.map((t: { id: string }) => t.id).sort(),
  );
  await page.reload();
  await expect(page.locator(".alert.error")).toContainText(
    "Approved writes are retained",
  );
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "artifacts/prepublication/APS-09-postcommit-recovery.png",
  });
});
