import type { Page } from "@playwright/test";
import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import path from "node:path";
async function register(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page.getByLabel("Your name").fill("Alex Example");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`alex-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-test-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
}
test("registration, project/task/note/memory CRUD, stale forms, theme and logout", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await register(page);
  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await page.getByRole("button", { name: "New project" }).click();
  await page.getByLabel("Title", { exact: true }).fill("Synthetic launch");
  await page
    .getByLabel("Description", { exact: true })
    .fill("A two-week launch plan");
  await page
    .getByLabel("Project instructions")
    .fill("Use simple English and cite evidence.");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Synthetic launch" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Tasks", exact: true }).click();
  await page.getByRole("button", { name: "New task" }).click();
  await page.getByLabel("Title", { exact: true }).fill("Prepare launch");
  await page.getByLabel("Due date").fill("2030-01-15");
  await page
    .getByLabel("Item project")
    .selectOption({ label: "Synthetic launch" });
  await page.getByRole("button", { name: "Save task", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Prepare launch" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Switch to task board" }).click();
  await page.getByRole("button", { name: "Mark done", exact: true }).click();
  await expect(page.getByRole("button", { name: "Reopen task" })).toBeVisible();
  await page.getByRole("link", { name: "Notes", exact: true }).click();
  await page.getByRole("button", { name: "New note" }).click();
  await page.getByLabel("Title", { exact: true }).fill("Launch notes");
  await page
    .getByLabel("Note · Markdown supported")
    .fill("## Decisions\nKeep scope focused.");
  await page.getByRole("button", { name: "Save note", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Launch notes" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Memories", exact: true }).click();
  await page.getByRole("button", { name: "New memory" }).click();
  await page.getByLabel("Title", { exact: true }).fill("Writing preference");
  await page
    .getByLabel("What should Aster remember?")
    .fill("Prefer simple English");
  await page.getByRole("button", { name: "Save memory", exact: true }).click();
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes("/api/memories/") && r.request().method() === "PUT",
    ),
    page.getByLabel("Enable Writing preference").uncheck(),
  ]);
  await page.reload();
  await expect(page.getByLabel("Enable Writing preference")).not.toBeChecked();
  await page.getByRole("button", { name: "Toggle dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("link", { name: /Alex Example/ }).click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
for (const width of [390, 768, 1440])
  test(`responsive workspace at ${width}px with keyboard and unavailable states`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await register(page);
    await expect(page.getByLabel("Send message")).toBeDisabled();
    await expect(page.getByText(/Add GEMINI_API_KEY directly/)).toBeVisible();
    await page
      .getByRole("button", { name: "Explore an idea", exact: false })
      .click();
    await expect(page.getByLabel("Message Aster")).toHaveValue(/Help me think/);
    if (width <= 800) await page.getByLabel("Open navigation").click();
    await page.getByRole("link", { name: "Documents", exact: true }).click();
    await page.waitForURL("**/documents");
    await expect(
      page.getByRole("heading", { name: "Documents", exact: true }),
    ).toBeVisible();
    await expect(page.locator('input[type="file"][multiple]')).toHaveCount(1);
    await page.locator("input[type=file]").setInputFiles({
      name: "Synthetic.md",
      mimeType: "text/markdown",
      buffer: Buffer.from(
        "# Proposal\n## Discovery\nConfirm scope.\n## Delivery\nReview launch.",
      ),
    });
    await expect(
      page.getByRole("heading", { name: "Synthetic.md" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: `artifacts/workspace-${width}.png`,
      fullPage: true,
    });
  });
test("real graph pending approval reload, source drawer, edited selection and one-time save", async ({
  page,
}) => {
  await register(page);
  const user = await (await page.request.get("/api/me")).json();
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const seed = execFileSync(
    python,
    ["tests/e2e/graph_fixture.py", "seed", user.id],
    { encoding: "utf8" },
  )
    .trim()
    .split(/\r?\n/)
    .at(-1)!;
  await page.goto("/chat/" + seed);
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toBeVisible();
  const before = await (await page.request.get("/api/tasks")).json();
  expect(before).toEqual([]);
  await page.getByRole("button", { name: "Source ↗", exact: true }).click();
  await expect(page.getByText(/Delivery milestone launches/)).toBeVisible();
  await page.getByLabel("Close dialog").click();
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByLabel("Copy code", { exact: true }).click();
  await expect(page.getByLabel("Copy code", { exact: true })).toContainText(
    "Copied",
  );
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    "print('Ready for review')",
  );
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page
      .getByRole("button", { name: "Approve selection", exact: true })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `artifacts/approval-${width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
  await page
    .getByRole("button", { name: "Edit proposal", exact: true })
    .click();
  await page
    .getByLabel("Title", { exact: true })
    .first()
    .fill("Edited discovery");
  await page.getByLabel("Include proposed item 2").uncheck();
  await page
    .getByRole("button", { name: "Approve edited selection", exact: true })
    .click();
  await expect(page.locator(".approval-card")).toHaveCount(0);
  await expect
    .poll(async () => {
      const history = await (
        await page.request.get("/api/conversations/" + seed + "/history")
      ).json();
      return history.proposals[0].status;
    })
    .toBe("approved");
  execFileSync(python, ["tests/e2e/graph_fixture.py", "resume", seed], {
    encoding: "utf8",
  });
  await page.reload();
  await expect(
    page.getByText("Your approved selection has been saved exactly once."),
  ).toBeVisible();
  const tasks = await (await page.request.get("/api/tasks")).json();
  expect(tasks).toHaveLength(1);
  expect(tasks[0].title).toBe("Edited discovery");
  await expect(page.locator(".approval-card")).toHaveCount(0);
  expect(
    tasks.some((task: { title: string }) => task.title !== "Edited discovery"),
  ).toBeFalsy();
  await page.screenshot({
    path: "artifacts/approval-completed.png",
    fullPage: true,
  });
});
