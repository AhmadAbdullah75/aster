import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
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
    .fill("Publication Collections");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-collection-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-collection-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return (await (await page.request.get("/api/me")).json()).id;
}
function seed(mode: string, user: string) {
  return JSON.parse(
    execFileSync(python, ["tests/e2e/collection_fixture.py", mode, user], {
      encoding: "utf8",
      timeout: 60_000,
    }).trim(),
  );
}
async function open(page: import("@playwright/test").Page, kind: string) {
  await page.goto("/" + kind);
  await expect(
    page.getByRole("heading", {
      name: kind[0].toUpperCase() + kind.slice(1),
      exact: true,
    }),
  ).toBeVisible();
}
async function save(page: import("@playwright/test").Page, kind: string) {
  await page.getByRole("button", { name: `Save ${kind}`, exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

test("TSK-01/02/03/04/05/06/07/09/10/15/17/18 task fields, dates, defaults and validation", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await account(page);
  await open(page, "tasks");
  await expect(
    page.getByText("A fresh space for your tasks", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New task", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save task", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Title", { exact: true }).fill("Default task");
  await save(page, "task");
  let tasks = await (await page.request.get("/api/tasks")).json();
  expect(tasks[0].status).toBe("todo");
  expect(tasks[0].priority).toBe("medium");
  const project = await (
    await page.request.post("/api/projects", {
      headers: origin,
      data: { title: "Task assignment scope" },
    })
  ).json();
  await page.reload();
  await page
    .getByRole("button", { name: "Edit Default task", exact: true })
    .click();
  await page
    .getByLabel("Description", { exact: true })
    .fill("Complete task details");
  await page.getByLabel("Priority", { exact: true }).selectOption("high");
  await page.getByLabel("Status", { exact: true }).selectOption("in_progress");
  await page
    .getByLabel("Item project", { exact: true })
    .selectOption(project.id);
  await page.getByLabel("Due date", { exact: true }).fill("2028-02-29");
  await save(page, "task");
  tasks = await (await page.request.get("/api/tasks")).json();
  expect(tasks[0]).toMatchObject({
    description: "Complete task details",
    priority: "high",
    status: "in_progress",
    due_date: "2028-02-29",
    project_id: project.id,
    version: 2,
  });
  await page.getByRole("button", { name: "Mark done", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Reopen task", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Reopen task", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Mark done", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Edit Default task", exact: true })
    .click();
  await page.getByLabel("Item project", { exact: true }).selectOption("");
  await save(page, "task");
  expect(
    (await (await page.request.get("/api/tasks")).json())[0].project_id,
  ).toBeNull();
  const today = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Karachi",
  }).format(new Date());
  for (const due of [today, "2000-01-01", "2099-12-31"]) {
    await page.getByRole("button", { name: "New task", exact: true }).click();
    await page.getByLabel("Title", { exact: true }).fill("Date " + due);
    await page.getByLabel("Due date", { exact: true }).fill(due);
    await save(page, "task");
  }
  const before = await (await page.request.get("/api/tasks")).json();
  await page.goto("/settings");
  await page.getByLabel("Timezone", { exact: true }).fill("Pacific/Auckland");
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    page.getByText("Preferences saved", { exact: true }),
  ).toBeVisible();
  expect(
    (await (await page.request.get("/api/tasks")).json()).map(
      (t: { due_date: string }) => t.due_date,
    ),
  ).toEqual(before.map((t: { due_date: string }) => t.due_date));
  await open(page, "tasks");
  await page.getByRole("button", { name: "New task", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("x".repeat(1000));
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(
    "x".repeat(200),
  );
  await page.getByLabel("Description", { exact: true }).fill("d".repeat(21000));
  await expect(page.getByLabel("Description", { exact: true })).toHaveValue(
    "d".repeat(20000),
  );
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  for (const values of [
    { title: "Invalid", status: "invalid" },
    { title: "Invalid", priority: "urgent" },
    { title: "x".repeat(1000) },
    { title: "Invalid", description: "x".repeat(20001) },
  ])
    expect(
      (
        await page.request.post("/api/tasks", { headers: origin, data: values })
      ).status(),
    ).toBe(422);
  await page
    .getByRole("button", { name: "Delete Default task", exact: true })
    .click();
  await page.getByRole("button", { name: "Keep it", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Default task", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Delete Default task", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Default task", exact: true }),
  ).toHaveCount(0);
});

test("TSK-11/12/13/14 priority/status/project filters, safe search and150task pagination/board", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const user = await account(page),
    truth = seed("tasks", user);
  await open(page, "tasks");
  await expect(page.locator(".resource-card")).toHaveCount(100);
  const first = await page.locator(".resource-card h3").allTextContents();
  await page
    .getByRole("button", { name: "Switch to task board", exact: true })
    .click();
  await expect(page.locator(".resource-card")).toHaveCount(100);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator(".resource-card")).toHaveCount(50);
  const second = await page.locator(".resource-card h3").allTextContents();
  expect(new Set([...first, ...second]).size).toBe(150);
  await page
    .getByLabel("Filter task status", { exact: true })
    .selectOption("done");
  await page
    .getByLabel("Filter task priority", { exact: true })
    .selectOption("high");
  await page
    .getByLabel("Filter project", { exact: true })
    .selectOption(truth.projects[0].id);
  const wanted = truth.tasks
    .filter(
      (t: { status: string; priority: string; project_id: string }) =>
        t.status === "done" &&
        t.priority === "high" &&
        t.project_id === truth.projects[0].id,
    )
    .map((t: { title: string }) => t.title)
    .sort();
  await expect(page.locator(".resource-card")).toHaveCount(wanted.length);
  expect(
    (await page.locator(".resource-card h3").allTextContents()).sort(),
  ).toEqual(wanted);
  await page
    .getByRole("button", { name: "Switch to task list", exact: true })
    .click();
  expect(
    (await page.locator(".resource-card h3").allTextContents()).sort(),
  ).toEqual(wanted);
  await page.getByLabel("Search tasks", { exact: true }).fill("' OR 1=1 --");
  await expect(page.locator(".resource-card")).toHaveCount(0);
  await page.getByLabel("Search tasks", { exact: true }).fill(wanted[0]);
  await expect(page.locator(".resource-card")).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "artifacts/prepublication/TSK-11-mobile-filters.png",
  });
});

test("NOT-01/02/03/05/06/08/09/12 Markdown,100kbody, safe search and unsaved-close protection", async ({
  page,
}) => {
  test.setTimeout(150_000);
  await account(page);
  await open(page, "notes");
  await page.getByRole("button", { name: "New note", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save note", exact: true }),
  ).toBeDisabled();
  await page.getByLabel("Title", { exact: true }).fill("Markdown اردو 🌿");
  const markdown =
    "# Heading\n\n- One\n- Two\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n```js\nconst safe = 1;\n```\n\n[Docs](https://example.com/)\n\nمنصوبہ روشن ہے۔";
  await page
    .getByLabel("Note · Markdown supported", { exact: true })
    .fill(markdown);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Discard unsaved changes?",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Keep editing", exact: true }).click();
  await expect(
    page.getByLabel("Note · Markdown supported", { exact: true }),
  ).toHaveValue(markdown);
  const warningPromise = page.waitForEvent("dialog", { timeout: 5000 });
  const canceledReload = page.reload({ timeout: 5000 }).catch(() => null);
  const warning = await warningPromise;
  expect(warning.type()).toBe("beforeunload");
  await warning.dismiss();
  await canceledReload;
  await expect(
    page.getByLabel("Note · Markdown supported", { exact: true }),
  ).toHaveValue(markdown);
  await save(page, "note");
  const card = page.locator(".resource-card").filter({
    has: page.getByRole("heading", { name: "Markdown اردو 🌿", exact: true }),
  });
  await expect(card.locator("table")).toHaveCount(1);
  await expect(card.locator("pre")).toHaveCount(1);
  await expect(
    card.getByRole("link", { name: "Docs", exact: true }),
  ).toHaveAttribute("rel", "noopener noreferrer");
  await page
    .getByRole("button", { name: "Edit Markdown اردو 🌿", exact: true })
    .click();
  await page
    .getByLabel("Note · Markdown supported", { exact: true })
    .fill("Body-only marker COPPER-NOTE-81");
  await save(page, "note");
  await page.getByLabel("Search notes", { exact: true }).fill("COPPER-NOTE-81");
  await expect(page.locator(".resource-card")).toHaveCount(1);
  await page.getByLabel("Search notes", { exact: true }).fill("' OR 1=1 --");
  await expect(page.locator(".resource-card")).toHaveCount(0);
  await page.getByLabel("Search notes", { exact: true }).fill("");
  await page.getByRole("button", { name: "New note", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Empty body allowed");
  await save(page, "note");
  await page.getByRole("button", { name: "New note", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Large note100k");
  await page
    .getByLabel("Note · Markdown supported", { exact: true })
    .fill("x".repeat(100000));
  await save(page, "note");
  const notes = await (await page.request.get("/api/notes")).json();
  expect(
    notes.find((n: { title: string }) => n.title === "Large note100k").content,
  ).toHaveLength(100000);
  await page
    .getByRole("button", { name: "Edit Large note100k", exact: true })
    .click();
  await page
    .getByLabel("Note · Markdown supported", { exact: true })
    .fill("Unsaved replacement");
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
  await page
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  expect(
    (await (await page.request.get("/api/notes")).json()).find(
      (n: { title: string }) => n.title === "Large note100k",
    ).content,
  ).toHaveLength(100000);
});

for (const kind of ["tasks", "notes", "memories"]) {
  test(`TSK-08 NOT-07 MEM-18 competing ${kind} editors preserve the winning version`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await account(page);
    await page.request.post("/api/" + kind, {
      headers: origin,
      data: {
        title: "Shared draft",
        ...(kind !== "tasks" ? { content: "Initial content" } : {}),
      },
    });
    await open(page, kind);
    await page
      .getByRole("button", { name: "Edit Shared draft", exact: true })
      .click();
    const other = await page.context().newPage();
    await open(other, kind);
    await other
      .getByRole("button", { name: "Edit Shared draft", exact: true })
      .click();
    await page.getByLabel("Title", { exact: true }).fill("First editor wins");
    await save(page, kind === "memories" ? "memory" : kind.slice(0, -1));
    await other
      .getByLabel("Title", { exact: true })
      .fill("Second editor loses");
    await other
      .getByRole("button", {
        name: "Save " + (kind === "memories" ? "memory" : kind.slice(0, -1)),
        exact: true,
      })
      .click();
    await expect(
      other.getByRole("dialog").locator(".alert.error"),
    ).toContainText(/changed|version/i);
    await expect(other.getByLabel("Title", { exact: true })).toHaveValue(
      "Second editor loses",
    );
    const records = await (await page.request.get("/api/" + kind)).json();
    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({
      title: "First editor wins",
      version: 2,
    });
  });
}

test("MEM-01/02/04/05/09/14/17 manual categories, off-switch CRUD, length limit and clear confirmation", async ({
  page,
}) => {
  test.setTimeout(150_000);
  await account(page);
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
  await open(page, "memories");
  for (const category of [
    "preference",
    "profile",
    "goal",
    "project_decision",
  ]) {
    await page.getByRole("button", { name: "New memory", exact: true }).click();
    await page.getByLabel("Title", { exact: true }).fill("Manual " + category);
    await page
      .getByLabel("What should Aster remember?", { exact: true })
      .fill("Synthetic manual content " + category);
    await page.getByLabel("Category", { exact: true }).selectOption(category);
    await save(page, "memory");
  }
  let memories = await (await page.request.get("/api/memories")).json();
  expect(memories).toHaveLength(4);
  for (const memory of memories) {
    expect(memory.provenance).toBe("User form");
    expect(Date.parse(memory.created_at)).not.toBeNaN();
    expect(Date.parse(memory.updated_at)).not.toBeNaN();
  }
  await page
    .getByRole("button", { name: "Edit Manual goal", exact: true })
    .click();
  await page
    .getByLabel("What should Aster remember?", { exact: true })
    .fill("Edited searchable marker MEMORY-COPPER-81");
  await save(page, "memory");
  memories = await (await page.request.get("/api/memories")).json();
  expect(
    memories.find((memory: { title: string }) => memory.title === "Manual goal")
      .version,
  ).toBe(2);
  await page
    .getByLabel("Search memories", { exact: true })
    .fill("MEMORY-COPPER-81");
  await expect(page.locator(".resource-card")).toHaveCount(1);
  await page.getByLabel("Search memories", { exact: true }).fill("");
  expect(
    (
      await page.request.post("/api/memories", {
        headers: origin,
        data: { title: "Too long", content: "x".repeat(4001) },
      })
    ).status(),
  ).toBe(422);
  await page
    .getByRole("button", { name: "Delete Manual profile", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Manual profile", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Clear all", exact: true }).click();
  await page.getByRole("button", { name: "Keep it", exact: true }).click();
  expect(await (await page.request.get("/api/memories")).json()).toHaveLength(
    3,
  );
  await page.getByRole("button", { name: "Clear all", exact: true }).click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page.locator(".resource-card")).toHaveCount(0);
  expect(await (await page.request.get("/api/memories")).json()).toEqual([]);
});

test("MEM-12/13 1000authoritative memories paginate without overlap and1001st is rejected", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const user = await account(page);
  expect(seed("memories", user).authoritative_store_api).toBeTruthy();
  await open(page, "memories");
  const seen = new Set<string>();
  for (let index = 0; index < 10; index++) {
    await expect(page.locator(".resource-card")).toHaveCount(100);
    for (const title of await page
      .locator(".resource-card h3")
      .allTextContents()) {
      expect(seen.has(title)).toBeFalsy();
      seen.add(title);
    }
    if (index < 9)
      await page.getByRole("button", { name: "Next", exact: true }).click();
  }
  expect(seen.size).toBe(1000);
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("Search memories", { exact: true })
    .fill("Boundary memory0000");
  await expect(page.locator(".resource-card")).toHaveCount(1);
  await page.getByRole("button", { name: "New memory", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Memory1001");
  await page
    .getByLabel("What should Aster remember?", { exact: true })
    .fill("Must be rejected");
  await page.getByRole("button", { name: "Save memory", exact: true }).click();
  await expect(page.getByRole("dialog").locator(".alert.error")).toContainText(
    "Memory limit reached",
  );
  expect(await (await page.request.get("/api/memories")).json()).toHaveLength(
    1000,
  );
});
