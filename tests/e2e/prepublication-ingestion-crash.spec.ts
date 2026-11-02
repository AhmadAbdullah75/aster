import { test, expect } from "./isolation";
import { spawn, execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

test("IDX-08 actual ingestion worker crash recovers natural lease and new worker completes", async ({
  page,
}) => {
  test.setTimeout(360_000);
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication ingestion crash");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-upload-crash-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-ingestion-crash-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.waitForURL("**/documents");
  await expect(
    page.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  await expect(page.locator('input[type="file"][multiple]')).toHaveCount(1);
  await page.locator('input[type="file"]').setInputFiles({
    name: "ingestion-crash.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Cedar Lantern real worker crash and recovery evidence.",
    ),
  });
  await expect(
    page.getByRole("heading", { name: "ingestion-crash.txt", exact: true }),
  ).toBeVisible();
  const doc = (await (await page.request.get("/api/documents")).json())[0];
  const status = (mode: string) =>
    JSON.parse(
      execFileSync(
        python,
        ["tests/e2e/ingestion_worker_fixture.py", mode, doc.id],
        { encoding: "utf8", timeout: 300_000 },
      ),
    );
  const first = spawn(
    python,
    ["tests/e2e/ingestion_worker_fixture.py", "slow", doc.id],
    { stdio: "ignore" },
  );
  let second: ReturnType<typeof spawn> | undefined;
  const killed = new WeakSet<ReturnType<typeof spawn>>();
  function kill(child: ReturnType<typeof spawn>) {
    if (child.exitCode !== null || killed.has(child)) return;
    killed.add(child);
    if (process.platform === "win32")
      execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
      });
    else child.kill("SIGKILL");
  }
  try {
    await expect
      .poll(
        async () =>
          readFile(
            `artifacts/prepublication/ingestion-active-${doc.id}.json`,
            "utf8",
          )
            .then(() => true)
            .catch(() => false),
        { timeout: 30_000 },
      )
      .toBe(true);
    const processing = status("status");
    expect(processing.job_status).toBe("processing");
    expect(processing.attempts).toBe(1);
    kill(first);
    const recovered = status("recover");
    expect(recovered.job_status).toBe("queued");
    await page.reload();
    await expect(page.locator(".resource-card")).toContainText("queued");
    second = spawn(
      python,
      ["tests/e2e/ingestion_worker_fixture.py", "fast", doc.id],
      { stdio: "ignore" },
    );
    await expect(
      page.locator(".resource-card").getByText("ready", { exact: true }),
    ).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => second!.exitCode).toBe(0);
    const completed = status("status");
    expect(completed.job_status).toBe("ready");
    expect(completed.attempts).toBe(2);
    await writeFile(
      "artifacts/prepublication/IDX-08-crash.json",
      JSON.stringify(
        { processing, recovered, completed, clockModified: false },
        null,
        2,
      ),
    );
    await page.screenshot({
      path: "artifacts/prepublication/IDX-08-crash.png",
      fullPage: true,
    });
  } finally {
    kill(first);
    if (second) kill(second);
  }
});
