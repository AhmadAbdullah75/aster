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
    .fill("Publication Memory Context");
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
function run(user: string, expected: string[] | number, project = "-") {
  return JSON.parse(
    execFileSync(
      python,
      [
        "tests/e2e/memory_context_fixture.py",
        user,
        project,
        JSON.stringify(expected),
      ],
      { encoding: "utf8", timeout: 30_000 },
    ).trim(),
  );
}
test("MEM-03/08/10/16 disabled, project-only, global-off and deleted memories do not enter new context", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const user = await account(page);
  const project = await (
    await page.request.post("/api/projects", {
      headers: origin,
      data: { title: "Memory scope A" },
    })
  ).json();
  const global = await (
    await page.request.post("/api/memories", {
      headers: origin,
      data: {
        title: "Global preference",
        content: "Keep garden answers brief",
      },
    })
  ).json();
  const scoped = await (
    await page.request.post("/api/memories", {
      headers: origin,
      data: {
        title: "Project-only preference",
        content: "Project garden marker SCOPED-FERN",
        project_id: project.id,
        category: "project_decision",
      },
    })
  ).json();
  const personal = run(user, [global.id]);
  run(user, [global.id, scoped.id], project.id);
  await page.goto("/memories");
  await page.getByLabel("Enable Global preference", { exact: true }).uncheck();
  await expect(
    page.getByLabel("Enable Global preference", { exact: true }),
  ).not.toBeChecked();
  run(user, []);
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
  run(user, [], project.id);
  const before = await (
    await page.request.get(`/api/conversations/${personal.thread_id}/history`)
  ).json();
  expect(
    before.messages.find(
      (message: { role: string }) => message.role === "assistant",
    ).content,
  ).toContain("Keep garden answers brief");
  expect(
    (
      await page.request.delete(`/api/memories/${global.id}?version=2`, {
        headers: origin,
      })
    ).ok(),
  ).toBeTruthy();
  const after = await (
    await page.request.get(`/api/conversations/${personal.thread_id}/history`)
  ).json();
  expect(after.messages).toEqual(before.messages);
  await page.goto(`/chat/${personal.thread_id}`);
  await expect(page.locator(".message.assistant")).toContainText(
    "Synthetic overview",
  );
  expect(await (await page.request.get("/api/memories")).json()).toHaveLength(
    1,
  );
});
test("MEM-15 only five relevant memories reach the model and audit event", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page);
  for (let i = 0; i < 6; i++)
    expect(
      (
        await page.request.post("/api/memories", {
          headers: origin,
          data: {
            title: `Relevant${i}`,
            content: `Keep garden answers brief preference${i}`,
          },
        })
      ).ok(),
    ).toBeTruthy();
  const result = run(user, 5);
  expect(result.selected_ids).toHaveLength(5);
  expect(new Set(result.selected_ids).size).toBe(5);
  await page.goto(`/chat/${result.thread_id}`);
  await expect(page.locator(".message.assistant")).toContainText(
    "Only the authorized current memory selection",
  );
  expect(await (await page.request.get("/api/memories")).json()).toHaveLength(
    6,
  );
});
