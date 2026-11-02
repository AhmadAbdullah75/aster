import { test, expect } from "./isolation";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";
import { writeFile } from "node:fs/promises";

for (const entry of ["composer", "sidebar"] as const) {
  test(`STR-01 first-message history race from ${entry} does not hide saved streaming`, async ({
    page,
  }) => {
    test.setTimeout(150_000);
    await page.route("**/api/capabilities", async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        response,
        json: { ...(await response.json()), chat: true, reason: null },
      });
    });
    await page.goto("/");
    await page
      .getByRole("button", { name: "Create an account", exact: true })
      .click();
    await page
      .getByLabel("Your name", { exact: true })
      .fill("Publication Race");
    await page
      .getByLabel("Email", { exact: true })
      .fill(`publication-race-${entry}-${Date.now()}@example.com`);
    await page
      .getByLabel("Password", { exact: true })
      .fill("synthetic-race-password");
    await page
      .getByRole("button", { name: "Create account", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: /What’s on your mind/ }),
    ).toBeVisible();
    await page.goto("/chat");
    const user = await (await page.request.get("/api/me")).json();
    const python = path.resolve(
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
    let accepted!: () => void;
    const acceptance = new Promise<void>((resolve) => {
      accepted = resolve;
    });
    let heldEmpty = false;
    let worker: ReturnType<typeof spawn> | undefined;
    let workerOutput = "";
    let starts = 0;
    await page.route("**/api/conversations/*/history", async (route) => {
      const response = await route.fetch();
      const snapshot = await response.json();
      if (!heldEmpty && snapshot.runs.length === 0) {
        heldEmpty = true;
        await acceptance;
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      await route.fulfill({ response, json: snapshot });
    });
    await page.route("**/api/conversations/*/runs", async (route) => {
      starts++;
      // Controlled write latency lets a pre-commit initial history snapshot exist.
      await new Promise((resolve) => setTimeout(resolve, 1000));
      const thread = route.request().url().split("/").at(-2)!;
      execFileSync(python, [
        "tests/e2e/stream_fixture.py",
        "seed",
        user.id,
        thread,
      ]);
      const history = await (
        await page.request.get(`/api/conversations/${thread}/history`)
      ).json();
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify(history.runs.at(-1)),
      });
      accepted();
      worker = spawn(python, ["tests/e2e/stream_fixture.py", "run", thread], {
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
      worker.stderr?.on("data", (data) => {
        workerOutput += data.toString();
      });
    });
    try {
      if (entry === "sidebar") {
        await page
          .getByRole("button", { name: "New conversation", exact: true })
          .click();
        await page.waitForURL("**/chat/*");
      }
      await page
        .getByLabel("Message Aster", { exact: true })
        .fill("Audit long response");
      await page
        .getByRole("button", { name: "Send message", exact: true })
        .click();
      await expect(
        page.getByText("Audit long response", { exact: true }),
      ).toBeVisible({ timeout: 20_000 });
      await expect
        .poll(
          async () => {
            if (worker?.exitCode !== null && worker?.exitCode !== undefined)
              throw new Error(
                `Worker exited before first output (${worker.exitCode}): ${workerOutput}`,
              );
            return page.getByText(/Audit stream paragraph 000/).isVisible();
          },
          { timeout: 60_000 },
        )
        .toBeTruthy();
      if (entry === "sidebar") expect(heldEmpty).toBe(true);
      expect(starts).toBe(1);
      await page
        .getByRole("button", { name: "Stop generation", exact: true })
        .click();
      const thread = page.url().split("/").at(-1)!;
      await expect
        .poll(
          async () =>
            (
              await (
                await page.request.get(`/api/conversations/${thread}/history`)
              ).json()
            ).runs.at(-1).status,
        )
        .toBe("canceled");
      const history = await (
        await page.request.get(`/api/conversations/${thread}/history`)
      ).json();
      expect(
        history.messages.filter(
          (message: { role: string }) => message.role === "user",
        ),
      ).toHaveLength(1);
    } finally {
      accepted();
      await writeFile(
        `artifacts/prepublication/stream-race-${entry}-worker.log`,
        workerOutput,
      );
      if (worker && worker.exitCode === null) worker.kill();
    }
  });
}
