import { test, expect } from "./isolation";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
import path from "node:path";

async function account(page: import("@playwright/test").Page) {
  const response = await page.request.post("/api/auth/register", {
    headers: { Origin: "http://127.0.0.1:3001" },
    data: {
      name: "Publication Layout",
      email: `publication-layout-${Date.now()}@example.com`,
      password: "synthetic-layout-password",
    },
  });
  expect(response.status()).toBe(200);
  await page.goto("/chat");
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
}

test("UI-03 sidebar collapse survives reload", async ({ page }) => {
  await account(page);
  await page
    .getByRole("button", { name: "Collapse sidebar", exact: true })
    .click();
  await expect(page.locator(".sidebar")).toHaveClass(/sidebar-collapsed/);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Expand sidebar", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".sidebar")).toHaveClass(/sidebar-collapsed/);
});

test("UI-13 unknown route has a clear way back", async ({ page }) => {
  await account(page);
  await page.goto("/this-page-does-not-exist");
  await expect(
    page.getByRole("heading", { name: "Page not found", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Back to workspace", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
});

test("UI-01/04/05/08/09/12/14/15 seven screens in both themes and three widths", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()))
      failures.push(message.text());
  });
  await account(page);
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"]) {
      const me = await (await page.request.get("/api/me")).json();
      expect(
        (
          await page.request.put("/api/me", {
            headers: { Origin: "http://127.0.0.1:3001" },
            data: {
              name: me.name,
              timezone: me.timezone,
              theme,
              memory_enabled: me.memory_enabled,
              version: me.version,
            },
          })
        ).ok(),
      ).toBeTruthy();
      for (const screen of [
        "chat",
        "projects",
        "documents",
        "tasks",
        "notes",
        "memories",
        "settings",
      ]) {
        await page.goto(`/${screen}`);
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        if (screen === "chat")
          await expect(
            page.getByRole("heading", { name: /What’s on your mind/ }),
          ).toBeVisible();
        else
          await expect(
            page.getByRole("heading", {
              name: screen[0].toUpperCase() + screen.slice(1),
              exact: true,
            }),
          ).toBeVisible();
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth + 1,
          ),
          `${screen} ${width} ${theme}`,
        ).toBeTruthy();
        if (!["chat", "settings"].includes(screen))
          await expect(
            page.getByRole("heading", {
              name: `A fresh space for your ${screen}`,
              exact: true,
            }),
          ).toBeVisible();
      }
      await page.screenshot({
        path: `artifacts/prepublication/UI-${width}-${theme}.png`,
      });
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("button", { name: "Open navigation", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Workspace navigation", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Open navigation", exact: true }),
  ).toBeFocused();
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(
    await page
      .locator("button")
      .first()
      .evaluate((el) => getComputedStyle(el).transitionDuration),
  ).toBe("0s");
  expect(failures).toEqual([]);
});

test("UI-06/07 list loading and API failure states recover without false empty", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await account(page);
  for (const kind of [
    "projects",
    "documents",
    "tasks",
    "notes",
    "memories",
    "conversations",
  ]) {
    const pattern = (url: URL) => url.pathname === `/api/${kind}`;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    let state = "loading";
    let intercepted = 0;
    let failureRequests = 0;
    const handler = async (route: import("@playwright/test").Route) => {
      intercepted++;
      if (state === "loading") await gate;
      if (state === "failure") {
        failureRequests++;
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Synthetic API unavailable" }),
        });
        return;
      }
      await route.continue();
    };
    await page.route(pattern, handler);
    try {
      await page.goto(kind === "conversations" ? "/chat" : `/${kind}`);
      await expect.poll(() => intercepted).toBeGreaterThan(0);
      await expect(
        page.getByText(
          kind === "conversations"
            ? "Loading saved conversations…"
            : `Loading ${kind}…`,
          { exact: true },
        ),
      ).toBeVisible();
      if (kind !== "conversations")
        await expect(
          page.getByRole("heading", {
            name: `A fresh space for your ${kind}`,
            exact: true,
          }),
        ).toHaveCount(0);
    } finally {
      state = "success";
      release();
    }
    if (kind !== "conversations")
      await expect(
        page.getByRole("heading", {
          name: `A fresh space for your ${kind}`,
          exact: true,
        }),
      ).toBeVisible();
    else
      await expect(
        page.getByText("Your conversations will appear here.", { exact: true }),
      ).toBeVisible();
    state = "failure";
    await page.reload();
    await expect.poll(() => failureRequests).toBeGreaterThan(0);
    await expect(
      page.getByRole("button", { name: "Retry", exact: true }).first(),
    ).toBeVisible();
    state = "success";
    await page
      .getByRole("button", { name: "Retry", exact: true })
      .first()
      .click();
    if (kind === "conversations")
      await expect(
        page.getByText("Your conversations will appear here.", { exact: true }),
      ).toBeVisible();
    else
      await expect(
        page.getByRole("heading", {
          name: `A fresh space for your ${kind}`,
          exact: true,
        }),
      ).toBeVisible();
    await page.unroute(pattern, handler);
  }
  await page.route("**/api/me", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Synthetic API unavailable" }),
    }),
  );
  await page.goto("/settings");
  await expect(
    page.getByRole("button", { name: "Retry connection", exact: true }),
  ).toBeVisible();
  await page.unrouteAll({ behavior: "wait" });
  await page
    .getByRole("button", { name: "Retry connection", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
});

test("A11Y-04/06 seven screens have labels and AA contrast in both themes", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await account(page);
  const reports = [];
  for (const theme of ["light", "dark"]) {
    const me = await (await page.request.get("/api/me")).json();
    await page.request.put("/api/me", {
      headers: { Origin: "http://127.0.0.1:3001" },
      data: {
        name: me.name,
        timezone: me.timezone,
        theme,
        memory_enabled: me.memory_enabled,
        version: me.version,
      },
    });
    for (const screen of [
      "chat",
      "projects",
      "documents",
      "tasks",
      "notes",
      "memories",
      "settings",
    ]) {
      await page.goto(`/${screen}`);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      await expect(
        page.getByRole("button", { name: "Log out", exact: true }),
      ).toBeVisible();
      const result = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      reports.push({
        screen,
        theme,
        violations: result.violations,
        incomplete: result.incomplete,
      });
    }
  }
  await writeFile(
    "artifacts/prepublication/accessibility-axe.json",
    JSON.stringify(reports, null, 2),
  );
  expect(
    reports.flatMap((report) =>
      report.violations.map(
        (v) => `${report.screen}/${report.theme}: ${v.id} (${v.nodes.length})`,
      ),
    ),
  ).toEqual([]);
});

test("A11Y-01/02/03 keyboard login upload approval and dialog focus", async ({
  page,
}) => {
  test.setTimeout(150_000);
  const email = `publication-keyboard-${Date.now()}@example.com`;
  const response = await page.request.post("/api/auth/register", {
    headers: { Origin: "http://127.0.0.1:3001" },
    data: {
      name: "Publication Keyboard",
      email,
      password: "synthetic-keyboard-password",
    },
  });
  expect(response.status()).toBe(200);
  const user = (await response.json()).id;
  await page.request.post("/api/auth/logout", {
    headers: { Origin: "http://127.0.0.1:3001" },
  });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).focus();
  await page.keyboard.type(email);
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password", { exact: true })).toBeFocused();
  await page.keyboard.type("synthetic-keyboard-password");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Attach a document", exact: true })
    .focus();
  const choosing = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  await (
    await choosing
  ).setFiles({
    name: "Keyboard evidence.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Keyboard upload acceptance evidence."),
  });
  await expect
    .poll(
      async () =>
        (await (await page.request.get("/api/documents")).json()).length,
    )
    .toBe(1);
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const thread = execFileSync(
    python,
    ["tests/e2e/graph_fixture.py", "seed", user],
    { encoding: "utf8", timeout: 60_000 },
  )
    .trim()
    .split(/\r?\n/)
    .at(-1)!;
  await page.goto(`/chat/${thread}`);
  await page
    .getByRole("button", { name: "Approve selection", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  execFileSync(python, ["tests/e2e/graph_fixture.py", "resume", thread], {
    timeout: 60_000,
  });
  expect(await (await page.request.get("/api/tasks")).json()).toHaveLength(2);
  await page.goto("/notes");
  await page.getByRole("button", { name: "New note", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  for (let index = 0; index < 12; index++) {
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(
        () => !!document.activeElement?.closest('[role="dialog"]'),
      ),
    ).toBeTruthy();
  }
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "New note", exact: true }),
  ).toBeFocused();
});
