import { test, expect } from "./isolation";
import type { Page } from "@playwright/test";
import { execFileSync, spawn } from "node:child_process";
import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";

const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Indexing");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-upload-index-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-indexing-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  const user = (await (await page.request.get("/api/me")).json()).id as string;
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.waitForURL("**/documents");
  await expect(
    page.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  await expect(page.locator('input[type="file"][multiple]')).toHaveCount(1);
  await page.locator('input[type="file"]').setInputFiles({
    name: "index-evidence.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Cedar Lantern indexing evidence. Acceptance owner is Mira.",
    ),
  });
  await expect(
    page.getByRole("heading", { name: "index-evidence.txt", exact: true }),
  ).toBeVisible();
  const doc = (await (await page.request.get("/api/documents")).json())[0];
  return { user, doc };
}
function ingest(doc: string, mode = "default") {
  execFileSync(
    python,
    [
      "tests/e2e/ingest_fixture.py",
      ...(mode === "default" ? [doc] : [mode, doc]),
    ],
    { timeout: 45_000 },
  );
}
const probe = (action: string, user: string, doc: string) =>
  JSON.parse(
    execFileSync(
      python,
      ["tests/e2e/index_probe_fixture.py", action, user, doc],
      { encoding: "utf8" },
    ),
  );

test("IDX-06/11/12 reindex replaces chunks, obsolete model excluded until rebuild, deletion removes search", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const { user, doc } = await account(page);
  ingest(doc.id);
  await page.reload();
  const before = probe("search", user, doc.id);
  expect(before.chunks).toBe(1);
  expect(before.search_sources).toBe(1);
  probe("old-model", user, doc.id);
  await page.reload();
  await expect(page.locator(".resource-card")).toContainText(
    "obsolete-test-model",
  );
  expect(probe("search", user, doc.id).search_sources).toBe(0);
  await page
    .getByRole("button", { name: "Reindex document", exact: true })
    .click();
  ingest(doc.id);
  await page.reload();
  const rebuilt = probe("search", user, doc.id);
  expect(rebuilt.chunks).toBe(1);
  expect(rebuilt.search_sources).toBe(1);
  await expect(page.locator(".resource-card")).not.toContainText(
    "obsolete-test-model",
  );
  await page
    .getByRole("button", { name: "Delete index-evidence.txt", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page.locator(".resource-card")).toHaveCount(0);
  const deleted = probe("search", user, doc.id);
  expect(deleted).toEqual({
    documents: 0,
    chunks: 0,
    jobs: 0,
    search_sources: 0,
  });
  expect(
    (await page.request.get(`/api/documents/${doc.id}/preview`)).status(),
  ).toBe(404);
  await writeFile(
    "artifacts/prepublication/IDX-reindex-delete.json",
    JSON.stringify({ before, rebuilt, deleted }, null, 2),
  );
});

test("IDX-07 deletion during in-flight embedding never recreates chunks or blob", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const { user, doc } = await account(page);
  const marker = path.resolve(
    `artifacts/prepublication/index-wait-${doc.id}.json`,
  );
  const before = new Set(await readdir(path.resolve(".data/e2e/blobs")));
  const child = spawn(python, ["tests/e2e/ingest_fixture.py", "slow", doc.id], {
    stdio: "ignore",
  });
  try {
    await expect
      .poll(
        async () =>
          readFile(marker, "utf8")
            .then(() => true)
            .catch(() => false),
        { timeout: 30_000 },
      )
      .toBe(true);
    await page.reload();
    await expect(page.locator(".resource-card")).toContainText("processing");
    await page
      .getByRole("button", { name: "Delete index-evidence.txt", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Delete permanently", exact: true })
      .click();
    await expect(page.locator(".resource-card")).toHaveCount(0);
    await expect.poll(() => child.exitCode, { timeout: 20_000 }).toBe(0);
    expect(probe("counts", user, doc.id)).toEqual({
      documents: 0,
      chunks: 0,
      jobs: 0,
    });
    expect((await readdir(path.resolve(".data/e2e/blobs"))).length).toBe(
      before.size - 1,
    );
  } finally {
    if (child.exitCode === null) {
      if (process.platform === "win32")
        execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
          stdio: "ignore",
        });
      else child.kill("SIGKILL");
    }
  }
});

test("IDX-14 provider outage fails readably with Retry, then recovery produces ready", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const { doc } = await account(page);
  ingest(doc.id, "outage");
  await page.reload();
  await expect(page.locator(".resource-card").getByRole("alert")).toContainText(
    "HTTP 503",
  );
  await page
    .getByRole("button", { name: "Retry indexing", exact: true })
    .click();
  ingest(doc.id);
  await page.reload();
  await expect(
    page.locator(".resource-card").getByText("ready", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".resource-card").getByRole("alert")).toHaveCount(
    0,
  );
});
