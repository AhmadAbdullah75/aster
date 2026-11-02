import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import path from "node:path";

const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);

test("LIM-17 output limit preserves long partial response and offers explicit retry", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const registered = await page.request.post("/api/auth/register", {
    headers: { Origin: "http://127.0.0.1:3001" },
    data: {
      name: "Publication Provider",
      email: `publication-provider-${Date.now()}@example.com`,
      password: "synthetic-provider-password",
    },
  });
  expect(registered.status()).toBe(200);
  const user = (await registered.json()).id;
  const data = JSON.parse(
    execFileSync(
      python,
      ["tests/e2e/provider_failure_fixture.py", user, "output_limit"],
      { encoding: "utf8", timeout: 60_000 },
    ),
  );
  await page.goto(`/chat/${data.thread_id}`);
  await expect(page.locator(".alert.error")).toContainText("output limit");
  await expect(
    page.getByText("Interrupted · partial response", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Prepare retry", exact: true }),
  ).toBeVisible();
  await page.reload();
  const history = await (
    await page.request.get(`/api/conversations/${data.thread_id}/history`)
  ).json();
  expect(history.messages[1].content).toBe(
    "Saved partial response. ".repeat(1500),
  );
  expect(history.messages[1].interrupted).toBe(true);
  expect(history.runs).toHaveLength(1);
  await page.screenshot({
    path: "artifacts/prepublication/LIM-17-output-limit.png",
  });
});

test("PRV-03/04/08/10/12 controlled provider failures are honest, bounded and sanitized", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Provider");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-provider-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-provider-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  const user = (await (await page.request.get("/api/me")).json()).id;
  for (const scenario of [
    "invalid_key",
    "missing_model",
    "simulated_429",
    "empty",
    "no_chunks",
    "malformed",
  ]) {
    await test.step(scenario, async () => {
      const data = JSON.parse(
        execFileSync(
          python,
          ["tests/e2e/provider_failure_fixture.py", user, scenario],
          { encoding: "utf8", timeout: 45_000 },
        ),
      );
      await page.goto(`/chat/${data.thread_id}`);
      await expect(
        page.getByRole("button", { name: "Prepare retry", exact: true }),
      ).toBeVisible();
      await expect(page.locator(".alert.error")).toContainText(
        scenario.startsWith("invalid")
          ? "HTTP 400"
          : scenario === "missing_model"
            ? "HTTP 404"
            : scenario === "simulated_429"
              ? "HTTP 429"
              : "Provider returned",
      );
      await expect(
        page.getByRole("button", { name: "Stop generation", exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: "Approve selection", exact: true }),
      ).toHaveCount(0);
      const history = await (
        await page.request.get(`/api/conversations/${data.thread_id}/history`)
      ).json();
      expect(history.runs).toHaveLength(1);
      expect(history.runs[0].status).toBe("failed");
      expect(history.messages[0].content).toBe(
        "Synthetic provider failure check",
      );
      expect(JSON.stringify(history)).not.toContain("SYNTHETIC-SECRET");
      await page.screenshot({
        path: `artifacts/prepublication/PRV-${scenario}.png`,
      });
    });
  }
  expect(await (await page.request.get("/api/tasks")).json()).toEqual([]);
  await page.getByRole("link", { name: "Notes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Notes", exact: true }),
  ).toBeVisible();
});
