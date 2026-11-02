import { test, expect } from "./isolation";
import { execFileSync, spawn } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const headers = { Origin: "http://127.0.0.1:3001" };
async function account(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Integrity");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-integrity-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-integrity-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return (await (await page.request.get("/api/me")).json()).id;
}

test("DAT-05/06/07 twenty parallel approvals uploads and edits preserve one outcome", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const user = await account(page);
  const thread = execFileSync(
    python,
    ["tests/e2e/graph_fixture.py", "seed", user],
    { encoding: "utf8", timeout: 60_000 },
  )
    .trim()
    .split(/\r?\n/)
    .at(-1)!;
  const history = await (
    await page.request.get(`/api/conversations/${thread}/history`)
  ).json();
  const proposal = history.proposals[0];
  const decisions = await Promise.all(
    Array.from({ length: 20 }, () =>
      page.request.post(`/api/proposals/${proposal.id}/decision`, {
        headers,
        data: { version: proposal.version, approve: true },
      }),
    ),
  );
  expect(decisions.map((r) => r.status())).toEqual(Array(20).fill(200));
  execFileSync(python, ["tests/e2e/graph_fixture.py", "resume", thread], {
    timeout: 60_000,
  });
  expect(await (await page.request.get("/api/tasks")).json()).toHaveLength(2);
  const uploads = await Promise.all(
    Array.from({ length: 20 }, () =>
      page.request.post("/api/documents", {
        headers,
        multipart: {
          file: {
            name: "Concurrent duplicate.txt",
            mimeType: "text/plain",
            buffer: Buffer.from("Same synthetic concurrent evidence."),
          },
        },
      }),
    ),
  );
  expect(
    uploads.every((r) => [200, 202, 429].includes(r.status())),
  ).toBeTruthy();
  const accepted = uploads.filter(
    (r) => r.status() === 200 || r.status() === 202,
  );
  expect(accepted.length).toBeGreaterThan(0);
  const uploaded = await Promise.all(accepted.map((r) => r.json()));
  expect(new Set(uploaded.map((d) => d.id)).size).toBe(1);
  const docs = await (await page.request.get("/api/documents")).json();
  expect(
    docs.filter(
      (d: { filename: string }) => d.filename === "Concurrent duplicate.txt",
    ),
  ).toHaveLength(1);
  const task = (await (await page.request.get("/api/tasks")).json())[0];
  const edits = await Promise.all(
    Array.from({ length: 20 }, (_, index) =>
      page.request.put(`/api/tasks/${task.id}`, {
        headers,
        data: { title: `Concurrent winner ${index}`, version: task.version },
      }),
    ),
  );
  expect(edits.filter((r) => r.status() === 200)).toHaveLength(1);
  expect(edits.filter((r) => r.status() === 409)).toHaveLength(19);
  await page.goto("/tasks");
  await expect(
    page.locator(".resource-card").filter({ hasText: "Concurrent winner" }),
  ).toHaveCount(1);
  await writeFile(
    "artifacts/prepublication/DAT-parallel.json",
    JSON.stringify(
      {
        approvals: decisions.map((r) => r.status()),
        duplicateUploads: uploads.map((r) => r.status()),
        uniqueDocuments: 1,
        edits: edits.map((r) => r.status()),
      },
      null,
      2,
    ),
  );
});

test("DAT-08 browser deletes document while actual retrieval is waiting", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const user = await account(page);
  const child = spawn(python, ["tests/e2e/search_deletion_fixture.py", user], {
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  child.stderr.on("data", (data) => (output += data.toString()));
  const ended = new Promise<number | null>((resolve) =>
    child.once("close", resolve),
  );
  const marker = `artifacts/prepublication/search-deletion-${user}.json`;
  try {
    await expect
      .poll(
        async () => {
          try {
            return JSON.parse(await readFile(marker, "utf8")).search_started;
          } catch {
            return false;
          }
        },
        { timeout: 60_000 },
      )
      .toBeTruthy();
    const data = JSON.parse(await readFile(marker, "utf8"));
    await page.goto("/documents");
    await page
      .getByRole("button", {
        name: "Delete Search deletion evidence.txt",
        exact: true,
      })
      .click();
    await page
      .getByRole("button", { name: "Delete permanently", exact: true })
      .click();
    await expect(
      page.getByRole("heading", {
        name: "Search deletion evidence.txt",
        exact: true,
      }),
    ).toHaveCount(0);
    expect(await ended, output).toBe(0);
    await page.goto(`/chat/${data.thread_id}`);
    await expect(page.locator(".message.assistant")).toContainText(
      "The document was removed",
    );
    await expect(page.locator(".source-chip")).toHaveCount(0);
    const history = await (
      await page.request.get(`/api/conversations/${data.thread_id}/history`)
    ).json();
    expect(history.runs[0].status).toBe("completed");
    await page.screenshot({
      path: "artifacts/prepublication/DAT-08-deleted-search.png",
    });
  } finally {
    await writeFile(
      "artifacts/prepublication/search-deletion-worker.log",
      output,
    );
    if (child.exitCode === null) child.kill();
  }
});
