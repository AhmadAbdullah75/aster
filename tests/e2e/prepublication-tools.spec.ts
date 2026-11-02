import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import path from "node:path";

for (const scenario of ["calculator", "read", "project", "budget"]) {
  test(`assistant tool boundaries ${scenario}`, async ({ page }) => {
    await page.goto("/");
    await page
      .getByRole("button", { name: "Create an account", exact: true })
      .click();
    await page
      .getByLabel("Your name", { exact: true })
      .fill("Publication Tools");
    await page
      .getByLabel("Email", { exact: true })
      .fill(`publication-tools-${Date.now()}@example.com`);
    await page
      .getByLabel("Password", { exact: true })
      .fill("synthetic-tools-password");
    await page
      .getByRole("button", { name: "Create account", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: /What’s on your mind/ }),
    ).toBeVisible();
    const user = await (await page.request.get("/api/me")).json();
    const python = path.resolve(
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
    const result = JSON.parse(
      execFileSync(python, ["tests/e2e/tool_fixture.py", scenario, user.id], {
        encoding: "utf8",
        timeout: 30_000,
      }).trim(),
    );
    expect(result.serial_pairs).toBeTruthy();
    await page.goto(`/chat/${result.thread_id}`);
    if (scenario === "budget") {
      expect(result.tool_calls).toBe(12);
      await expect(page.locator(".alert.error")).toContainText(
        "Tool budget exhausted. Narrow the request and retry.",
      );
      await expect(
        page.getByRole("button", { name: "Prepare retry", exact: true }),
      ).toBeVisible();
    } else if (scenario === "calculator") {
      await expect(page.locator(".message.assistant")).toContainText("351");
      await expect(page.locator(".message.assistant")).toContainText(
        "six unsafe/invalid expressions were rejected",
      );
      expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
    } else {
      await expect(page.locator(".message.assistant")).toContainText(
        "Partial task list:10items",
      );
      await expect(page.locator(".message.assistant")).toContainText(
        "Reader marker A",
      );
      if (scenario === "project")
        await expect(page.locator(".message.assistant")).not.toContainText(
          "Reader marker B",
        );
    }
    await expect(
      page.getByRole("button", { name: "Approve selection", exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: `artifacts/prepublication/tools-${scenario}.png`,
    });
  });
}
