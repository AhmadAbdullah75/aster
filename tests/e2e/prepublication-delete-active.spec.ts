import { test, expect } from "./isolation";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";

test("CNV-14 active worker deletion cancels and cannot recreate graph or messages", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication active deletion");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-history-active-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-active-delete-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  const user = await (await page.request.get("/api/me")).json();
  const python = path.resolve(".venv/Scripts/python.exe");
  const thread = execFileSync(
    python,
    ["tests/e2e/stream_fixture.py", "seed", user.id],
    { encoding: "utf8" },
  ).trim();
  const worker = spawn(python, ["tests/e2e/stream_fixture.py", "run", thread], {
    stdio: "ignore",
  });
  try {
    await page.goto(`/chat/${thread}`);
    await expect(page.getByText(/Audit stream paragraph 000/)).toBeVisible({
      timeout: 30_000,
    });
    const history = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(history.runs[0].status).toBe("running");
    await page.getByLabel("Delete Audit streaming", { exact: true }).click();
    await page
      .getByRole("button", { name: "Delete permanently", exact: true })
      .click();
    await expect(page).toHaveURL(/\/chat$/, { timeout: 30_000 });
    await expect
      .poll(() => worker.exitCode, { timeout: 15_000 })
      .not.toBeNull();
    expect(worker.exitCode).toBe(0);
    expect(
      (await page.request.get(`/api/runs/${history.runs[0].id}`)).status(),
    ).toBe(404);
    expect(
      (await page.request.get(`/api/conversations/${thread}/history`)).status(),
    ).toBe(404);
    const counts = JSON.parse(
      execFileSync(
        python,
        ["tests/e2e/conversation_fixture.py", "counts", thread],
        { encoding: "utf8" },
      ),
    );
    expect(Object.values(counts).every((count) => count === 0)).toBe(true);
    await test
      .info()
      .attach("after-worker-exit", {
        body: JSON.stringify(counts),
        contentType: "application/json",
      });
    await page.screenshot({
      path: "artifacts/prepublication/CNV-14.png",
      fullPage: true,
    });
  } finally {
    if (worker.exitCode === null) worker.kill();
  }
});
