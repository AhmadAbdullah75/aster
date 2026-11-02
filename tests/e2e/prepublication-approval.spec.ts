import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import path from "node:path";
const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
async function account(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Approval");
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
function seed(user: string, count = 2) {
  return execFileSync(
    python,
    [
      "tests/e2e/graph_fixture.py",
      "seed",
      user,
      "tasks.create",
      JSON.stringify(
        Array.from({ length: count }, (_, index) => ({
          title: `Proposed task${index}`,
          due_date: "2026-10-30",
        })),
      ),
    ],
    { encoding: "utf8", timeout: 30_000 },
  )
    .trim()
    .split(/\r?\n/)
    .at(-1)!;
}
function resume(thread: string) {
  execFileSync(python, ["tests/e2e/graph_fixture.py", "resume", thread], {
    timeout: 30_000,
  });
}

test("APR-04/05/06/10 edited fields, invalid title/date and zero selection remain safe", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page),
    thread = seed(user, 5);
  await page.goto(`/chat/${thread}`);
  await page
    .getByRole("button", { name: "Edit proposal", exact: true })
    .click();
  await page.getByLabel("Title", { exact: true }).first().fill("");
  await page
    .getByRole("button", { name: "Approve edited selection", exact: true })
    .click();
  await expect(page.locator(".alert.error")).toContainText(
    "Invalid proposal fields. title",
  );
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
  await page
    .getByRole("button", { name: "Dismiss error", exact: true })
    .click();
  const history = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json(),
    proposal = history.proposals[0];
  const invalid = structuredClone(proposal.payload);
  invalid.items[0].due_date = "2026-02-30";
  const response = await page.request.post(
    `/api/proposals/${proposal.id}/decision`,
    {
      headers: { Origin: "http://127.0.0.1:3001" },
      data: { approve: true, version: proposal.version, payload: invalid },
    },
  );
  expect(response.status()).toBe(422);
  await page
    .getByLabel("Title", { exact: true })
    .first()
    .fill("Reviewed first task");
  await page.getByLabel("Due date", { exact: true }).first().fill("2026-10-31");
  for (let i = 1; i <= 5; i++)
    await page
      .getByLabel(`Include proposed item ${i}`, { exact: true })
      .uncheck();
  await expect(
    page.getByRole("button", { name: "Approve edited selection", exact: true }),
  ).toBeDisabled();
  for (let i = 1; i <= 4; i++)
    await page
      .getByLabel(`Include proposed item ${i}`, { exact: true })
      .check();
  await page
    .getByRole("button", { name: "Approve edited selection", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Approve edited selection", exact: true }),
  ).toHaveCount(0);
  resume(thread);
  await page.reload();
  const tasks = await (await page.request.get("/api/tasks")).json();
  expect(tasks).toHaveLength(4);
  expect(
    tasks.find(
      (task: { title: string }) => task.title === "Reviewed first task",
    ).due_date,
  ).toBe("2026-10-31");
  expect(
    tasks.some((task: { title: string }) => task.title === "Proposed task4"),
  ).toBeFalsy();
  await page.screenshot({
    path: "artifacts/prepublication/APR-05-four-of-five.png",
  });
});

test("APR-08 two-tab approval race executes one selected batch", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page),
    thread = seed(user);
  await page.goto(`/chat/${thread}`);
  const other = await page.context().newPage();
  await other.goto(`/chat/${thread}`);
  const matches = (response: import("@playwright/test").Response) =>
    response.url().includes("/decision") &&
    response.request().method() === "POST";
  const first = page.waitForResponse(matches),
    second = other.waitForResponse(matches);
  await Promise.all([
    page
      .getByRole("button", { name: "Approve selection", exact: true })
      .click(),
    other
      .getByRole("button", { name: "Approve selection", exact: true })
      .click(),
  ]);
  const statuses = [(await first).status(), (await second).status()].sort();
  expect(statuses).toEqual([200, 200]);
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
  resume(thread);
  await page.reload();
  await other.reload();
  expect(await (await page.request.get("/api/tasks")).json()).toHaveLength(2);
  await expect(
    other.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(0);
});

test("APR-09 repeated rapid clicks do not duplicate execution", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page),
    thread = seed(user);
  await page.goto(`/chat/${thread}`);
  await page
    .getByRole("button", { name: "Approve selection", exact: true })
    .evaluate((button) => {
      for (let i = 0; i < 20; i++) (button as HTMLButtonElement).click();
    });
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(0);
  resume(thread);
  await page.reload();
  const tasks = await (await page.request.get("/api/tasks")).json();
  expect(tasks).toHaveLength(2);
  expect(new Set(tasks.map((task: { id: string }) => task.id)).size).toBe(2);
});

test("APR-11/12/13 20+1 split proposals resume only after both decisions", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const user = await account(page);
  const { thread_id: thread } = JSON.parse(
    execFileSync(python, ["tests/e2e/approval_pair_fixture.py", user], {
      encoding: "utf8",
      timeout: 30_000,
    }).trim(),
  );
  await page.goto(`/chat/${thread}`);
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(2);
  await expect(
    page.locator('.approval-card input[type="checkbox"]'),
  ).toHaveCount(21);
  await page
    .getByRole("button", { name: "Approve selection", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(1);
  let history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  expect(history.runs[0].status).toBe("waiting");
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Reject", exact: true }),
  ).toHaveCount(0);
  resume(thread);
  await page.reload();
  expect(await (await page.request.get("/api/tasks")).json()).toHaveLength(20);
  history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  expect(history.runs[0].status).toBe("completed");
  expect(
    history.proposals.map((p: { status: string }) => p.status).sort(),
  ).toEqual(["completed", "rejected"]);
  await page.screenshot({
    path: "artifacts/prepublication/APR-13-both-decisions.png",
  });
});
