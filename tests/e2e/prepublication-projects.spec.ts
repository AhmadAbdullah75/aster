import { test, expect } from "./isolation";
import { execFileSync, spawn } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const origin = { Origin: "http://127.0.0.1:3001" };
async function account(
  page: import("@playwright/test").Page,
  prefix = "publication-upload-projects-",
) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Projects");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`${prefix}${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-project-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return (await (await page.request.get("/api/me")).json()).id;
}
async function document(
  page: import("@playwright/test").Page,
  project: string,
) {
  await page.goto("/documents");
  await expect(
    page.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Filter project", { exact: true })
    .selectOption(project);
  await page.locator('input[type="file"]').setInputFiles({
    name: "project-evidence.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Project private evidence: the verification marker is FERN-PROJECT-81.",
    ),
  });
  await expect(
    page.getByRole("heading", { name: "project-evidence.txt", exact: true }),
  ).toBeVisible();
  return (await (await page.request.get("/api/documents")).json())[0];
}
function probe(
  user: string,
  project: string,
  thread: string,
  doc: string,
  blob?: string,
) {
  return JSON.parse(
    execFileSync(
      python,
      [
        "tests/e2e/project_probe_fixture.py",
        user,
        project,
        thread,
        doc,
        ...(blob ? [blob] : []),
      ],
      { encoding: "utf8", timeout: 30_000 },
    ).trim(),
  );
}
async function removeProject(
  page: import("@playwright/test").Page,
  title: string,
) {
  await page.goto("/projects");
  await page
    .getByRole("button", { name: "Delete " + title, exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toHaveCount(0);
}

test("PRJ-01/02/03/04/06/07/08/09/10 TSK-16 NOT-04/11 full scoped deletion keeps personal data", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const user = await account(page);
  await page.goto("/projects");
  await page.getByRole("button", { name: "New project", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save project", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("Title", { exact: true })
    .fill("Publication full cleanup");
  await page
    .getByLabel("Description", { exact: true })
    .fill("All scoped resource types");
  await page
    .getByLabel("Project instructions", { exact: true })
    .fill("Use concise explanations.");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByRole("button", { name: "Edit Publication full cleanup", exact: true })
    .click();
  await page
    .getByLabel("Description", { exact: true })
    .fill("Edited project description");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const project = (await (await page.request.get("/api/projects")).json())[0];
  expect(project).toMatchObject({
    description: "Edited project description",
    instructions: "Use concise explanations.",
    version: 2,
  });
  for (const kind of ["tasks", "notes", "memories"]) {
    const result = await page.request.post("/api/" + kind, {
      headers: origin,
      data: {
        title: "Scoped " + kind,
        project_id: project.id,
        ...(kind !== "tasks" ? { content: "Scoped content" } : {}),
      },
    });
    expect(result.ok()).toBeTruthy();
  }
  await page.request.post("/api/notes", {
    headers: origin,
    data: {
      title: "Outside project note",
      content: "Personal data must survive",
    },
  });
  const doc = await document(page, project.id);
  expect(doc.project_id).toBe(project.id);
  execFileSync(python, ["tests/e2e/ingest_fixture.py", doc.id], {
    timeout: 30_000,
  });
  const thread = await (
    await page.request.post("/api/conversations", {
      headers: origin,
      data: { title: "Project cleanup chat", project_id: project.id },
    })
  ).json();
  execFileSync(python, [
    "tests/e2e/stream_fixture.py",
    "seed",
    user,
    thread.id,
  ]);
  execFileSync(
    python,
    ["tests/e2e/stream_fixture.py", "run", thread.id, "fast"],
    { timeout: 30_000 },
  );
  const before = probe(user, project.id, thread.id, doc.id);
  expect(before.blob_exists).toBeTruthy();
  expect(before.rows.chunks).toBeGreaterThan(0);
  expect(before.checkpoints.checkpoints).toBeGreaterThan(0);
  for (const name of ["Tasks", "Notes", "Memories", "Documents"]) {
    await page.getByRole("link", { name, exact: true }).click();
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByLabel("Filter project", { exact: true }),
    ).toHaveValue(project.id);
    await expect(page.locator(".resource-card")).toHaveCount(1);
  }
  await page.goto("/projects");
  await page
    .getByRole("button", {
      name: "Delete Publication full cleanup",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Keep it", exact: true }).click();
  expect(probe(user, project.id, thread.id, doc.id).rows).toEqual(before.rows);
  await removeProject(page, project.title);
  const after = probe(user, project.id, thread.id, doc.id, before.blob);
  expect(Object.values(after.rows).every((count) => count === 0)).toBeTruthy();
  expect(
    Object.values(after.checkpoints).every((count) => count === 0),
  ).toBeTruthy();
  expect(after.blob_exists).toBeFalsy();
  expect(
    (
      await page.request.get(`/api/conversations/${thread.id}/history`)
    ).status(),
  ).toBe(404);
  const notes = await (await page.request.get("/api/notes")).json();
  expect(notes.map((n: { title: string }) => n.title)).toEqual([
    "Outside project note",
  ]);
  await page.goto("/notes");
  await page
    .getByRole("button", { name: "Delete Outside project note", exact: true })
    .click();
  await page.getByRole("button", { name: "Keep it", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Outside project note", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Delete Outside project note", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page.locator(".resource-card")).toHaveCount(0);
});

for (const mode of ["stream", "index"]) {
  test(`PRJ-11/12 deleting project during actual ${mode} work leaves no resurrection`, async ({
    page,
  }) => {
    test.setTimeout(150_000);
    const user = await account(page);
    const title = "Publication active " + mode;
    const project = await (
      await page.request.post("/api/projects", {
        headers: origin,
        data: { title },
      })
    ).json();
    const doc = await document(page, project.id);
    const thread = await (
      await page.request.post("/api/conversations", {
        headers: origin,
        data: { title: "Active project chat", project_id: project.id },
      })
    ).json();
    const before = probe(user, project.id, thread.id, doc.id);
    if (mode === "stream")
      execFileSync(python, [
        "tests/e2e/stream_fixture.py",
        "seed",
        user,
        thread.id,
      ]);
    const args =
      mode === "stream"
        ? ["tests/e2e/stream_fixture.py", "run", thread.id]
        : ["tests/e2e/ingest_fixture.py", "slow", doc.id];
    const child = spawn(python, args, {
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const output: string[] = [];
    child.stderr.on("data", (data) => output.push(data.toString()));
    child.stdout.on("data", (data) => output.push(data.toString()));
    const ended = new Promise<number | null>((resolve) =>
      child.once("close", resolve),
    );
    try {
      if (mode === "stream") {
        await page.goto(`/chat/${thread.id}`);
        await Promise.race([
          expect(page.locator(".message.assistant")).toContainText(
            "Audit stream paragraph 000",
            { timeout: 60_000 },
          ),
          ended.then((code) => {
            throw new Error(
              `Stream fixture exited before deletion (${code}): ${output.join("")}`,
            );
          }),
        ]);
      } else
        await expect
          .poll(
            async () => {
              try {
                return JSON.parse(
                  await readFile(
                    `artifacts/prepublication/index-wait-${doc.id}.json`,
                    "utf8",
                  ),
                ).embedding_started;
              } catch {
                return false;
              }
            },
            { timeout: 15_000 },
          )
          .toBeTruthy();
      await removeProject(page, title);
      expect(await ended, output.join("")).toBe(0);
      const after = probe(user, project.id, thread.id, doc.id, before.blob);
      expect(
        Object.values(after.rows).every((count) => count === 0),
      ).toBeTruthy();
      expect(
        Object.values(after.checkpoints).every((count) => count === 0),
      ).toBeTruthy();
      expect(after.blob_exists).toBeFalsy();
    } finally {
      await writeFile(
        `artifacts/prepublication/project-${mode}-worker.log`,
        output.join(""),
      );
      if (child.exitCode === null) child.kill();
    }
  });
}

test("PRJ-15 fifty projects remain searchable and usable at mobile width", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page, "publication-collection-");
  execFileSync(python, ["tests/e2e/collection_fixture.py", "projects", user], {
    timeout: 30_000,
  });
  await page.goto("/projects");
  await expect(page.locator(".resource-card")).toHaveCount(50);
  await page
    .getByLabel("Search projects", { exact: true })
    .fill("Collection project49");
  await expect(page.locator(".resource-card")).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
  await page.screenshot({ path: "artifacts/prepublication/PRJ-15-mobile.png" });
});
