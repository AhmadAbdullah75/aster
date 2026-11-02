import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import { writeFile } from "node:fs/promises";
import path from "node:path";

const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);

test("Aster branding and timestamped opposite-side messages persist across themes viewports and reload", async ({
  page,
}) => {
  const user = await account(page);
  const { thread_id } = JSON.parse(
    execFileSync(
      python,
      ["tests/e2e/layout_bulk_fixture.py", "branding", user],
      { encoding: "utf8", timeout: 60_000 },
    ),
  );
  await page.goto(`/chat/${thread_id}`);
  await expect(page).toHaveTitle("Aster · Your personal workspace");
  await expect(page.locator(".brand")).toContainText("Aster");
  await expect(page.getByLabel("Message Aster", { exact: true })).toBeVisible();
  const history = await (
    await page.request.get(`/api/conversations/${thread_id}/history`)
  ).json();
  const profile = await (await page.request.get("/api/me")).json();
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const theme of ["light", "dark"]) {
      await page.evaluate((theme) => {
        document.documentElement.dataset.theme = theme;
      }, theme);
      const human = page.locator(".message.user");
      const ai = page.locator(".message.assistant");
      await expect(ai).toContainText("A little clarity for your next step");
      const humanBox = (await human.boundingBox())!;
      const aiBox = (await ai.boundingBox())!;
      expect(humanBox.x).toBeGreaterThan(aiBox.x);
      expect((await ai.locator(".message-body").boundingBox())!.x).toBeLessThan(
        (await human.locator(".message-body").boundingBox())!.x,
      );
      expect(
        (await ai.locator(".message-avatar").boundingBox())!.x,
      ).toBeLessThan((await ai.locator(".message-body").boundingBox())!.x);
      await expect(human.locator(".message-avatar")).toBeHidden();
      const bubble = (await human.locator(".markdown").boundingBox())!;
      expect(
        (await human.locator(".message-heading").boundingBox())!.y,
      ).toBeGreaterThanOrEqual(bubble.y + bubble.height);
      for (const role of ["user", "assistant"]) {
        const message = history.messages.find(
          (m: { role: string }) => m.role === role,
        );
        const timestamp = page.locator(`.message.${role} time`);
        await expect(timestamp).toHaveAttribute("datetime", message.created_at);
        await expect(timestamp).toHaveText(
          new Intl.DateTimeFormat("en", {
            hour: "2-digit",
            minute: "2-digit",
            hour12: true,
            timeZone: profile.timezone,
          }).format(new Date(message.created_at)),
        );
        await expect(timestamp).toHaveAttribute("title", /.+/);
      }
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      ).toBeTruthy();
      await page.screenshot({
        path: `artifacts/prepublication/aster-chat-${width}-${theme}.png`,
      });
    }
  }
  const before = await page.locator(".message time").allTextContents();
  await page.reload();
  await expect(page.locator(".message")).toHaveCount(2);
  expect(await page.locator(".message time").allTextContents()).toEqual(before);
});

test("UI-02 short zoom-equivalent viewport keeps messages composer and account controls reachable", async ({
  page,
}) => {
  const user = await account(page);
  const { thread_id } = JSON.parse(
    execFileSync(
      python,
      ["tests/e2e/layout_bulk_fixture.py", "markdown", user],
      { encoding: "utf8", timeout: 60_000 },
    ),
  );
  await page.setViewportSize({ width: 641, height: 321 });
  await page.goto(`/chat/${thread_id}`);
  await expect(page.locator(".message.assistant")).toContainText(
    "Layout evidence",
  );
  const timeline = await page.locator(".chat-scroll").boundingBox();
  expect(timeline!.height).toBeGreaterThanOrEqual(159);
  const input = page.getByLabel("Message Aster", { exact: true });
  await input.focus();
  await expect(input).toBeInViewport();
  await input.press("Tab");
  await expect(
    page.getByRole("button", { name: "Attach a document", exact: true }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Open navigation", exact: true })
    .click();
  const logout = page.getByRole("button", { name: "Log out", exact: true });
  await logout.scrollIntoViewIfNeeded();
  await expect(logout).toBeInViewport();
  await page.locator('.sidebar a[href="/settings"]').click();
  await page
    .getByRole("button", { name: "Close navigation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  const save = page.getByRole("button", {
    name: "Save preferences",
    exact: true,
  });
  await save.scrollIntoViewIfNeeded();
  await expect(save).toBeInViewport();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
});

test("LIM-19 profile and shared resource editor enforce their saved name/title limits", async ({
  page,
}) => {
  await account(page);
  await page.goto("/settings");
  const name = page.getByLabel("Name", { exact: true });
  await expect(name).toHaveAttribute("maxlength", "120");
  await name.fill("n".repeat(121));
  await expect(name).toHaveValue("n".repeat(120));
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    page.getByText("Preferences saved", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(name).toHaveValue("n".repeat(120));
  for (const [screen, singular] of [
    ["projects", "project"],
    ["tasks", "task"],
    ["notes", "note"],
    ["memories", "memory"],
  ]) {
    await page.goto(`/${screen}`);
    await page
      .getByRole("button", { name: `New ${singular}`, exact: true })
      .click();
    const title = page.getByRole("dialog").getByLabel("Title", { exact: true });
    await expect(title).toHaveAttribute("maxlength", "200");
    await title.fill("t".repeat(201));
    await expect(title).toHaveValue("t".repeat(200));
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await page
      .getByRole("button", { name: "Discard changes", exact: true })
      .click();
  }
});

test("PERF-08 fifty authenticated SSE connections keep the server responsive", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page);
  const result = JSON.parse(
    execFileSync(python, ["tests/e2e/sse_load_fixture.py", user], {
      encoding: "utf8",
      timeout: 90_000,
    }),
  );
  expect(result.simultaneous_sse_connections).toBe(50);
  expect(result.each_received_authorized_event).toBe(true);
  expect(result.health_seconds_while_held).toHaveLength(5);
  await writeFile(
    "artifacts/prepublication/sse-performance.json",
    JSON.stringify(result, null, 2),
  );
});

test("PERF-10 record storage growth for one thousand persisted messages", async ({
  page,
}) => {
  const user = await account(page);
  const result = JSON.parse(
    execFileSync(
      python,
      ["tests/e2e/layout_bulk_fixture.py", "message_growth", user],
      { encoding: "utf8", timeout: 45_000 },
    ),
  );
  expect(result.messages).toBe(1000);
  expect(result.owned_projection_row_bytes).toBeGreaterThan(0);
  await writeFile(
    "artifacts/prepublication/message-growth.json",
    JSON.stringify(result, null, 2),
  );
});
async function account(page: import("@playwright/test").Page) {
  const response = await page.request.post("/api/auth/register", {
    headers: { Origin: "http://127.0.0.1:3001" },
    data: {
      name: "Publication Presentation",
      email: `publication-presentation-${Date.now()}@example.com`,
      password: "synthetic-presentation-password",
    },
  });
  expect(response.status()).toBe(200);
  return (await response.json()).id;
}

test("E2E-4 UI-05 PERF-01/02 combined bulk account navigates without replacing its shell", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const user = await account(page);
  execFileSync(python, ["tests/e2e/layout_bulk_fixture.py", "bulk", user], {
    timeout: 60_000,
  });
  const started = performance.now();
  await page.goto("/chat");
  await expect(page.locator(".conversation-list a")).toHaveCount(205);
  const coldSeconds = (performance.now() - started) / 1000;
  const renderSeconds = await page.evaluate(() => {
    const responses = performance
      .getEntriesByType("resource")
      .filter((item) =>
        item.name.includes("/api/conversations"),
      ) as PerformanceResourceTiming[];
    return (
      (performance.now() -
        Math.max(...responses.map((item) => item.responseEnd))) /
      1000
    );
  });
  const shell = await page.locator(".sidebar").elementHandle();
  await page
    .getByLabel("Search conversations", { exact: true })
    .fill("Bulk chat204");
  await page.getByRole("link", { name: "Bulk chat204", exact: true }).click();
  await expect(
    page.getByText("Bulk saved answer204", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Search conversations", { exact: true }).fill("");
  for (const screen of [
    "projects",
    "documents",
    "tasks",
    "notes",
    "memories",
    "settings",
  ]) {
    await page.locator(`a[href="/${screen}"]`).click();
    await expect(
      page.getByRole("heading", {
        name: screen[0].toUpperCase() + screen.slice(1),
        exact: true,
      }),
    ).toBeVisible();
    expect(
      await page
        .locator(".sidebar")
        .evaluate((current, previous) => current === previous, shell),
    ).toBeTruthy();
    if (screen === "tasks" || screen === "memories") {
      await expect(page.locator(".resource-card")).toHaveCount(100);
      const first = await page.locator(".resource-card h3").allTextContents();
      await page.getByRole("button", { name: "Next", exact: true }).click();
      await expect(page.locator(".resource-card")).toHaveCount(
        screen === "tasks" ? 50 : 1,
      );
      const second = await page.locator(".resource-card h3").allTextContents();
      expect(new Set([...first, ...second]).size).toBe(
        screen === "tasks" ? 150 : 101,
      );
      await page
        .getByLabel(`Search ${screen}`, { exact: true })
        .fill(screen === "tasks" ? "Bulk task149" : "Bulk memory100");
      await expect(page.locator(".resource-card")).toHaveCount(1);
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
  const report = {
    cold_browser_cache_seconds: coldSeconds,
    sidebar_render_after_last_response_seconds: renderSeconds,
    conversations: 205,
    tasks: 150,
    memories: 101,
    persistent_shell: true,
    scope:
      "Local production build; cold browser assets, already-running web server. Shared host workload recorded separately.",
  };
  await writeFile(
    "artifacts/prepublication/bulk-performance.json",
    JSON.stringify(report, null, 2),
  );
  await page.screenshot({
    path: "artifacts/prepublication/E2E-4-bulk-mobile.png",
  });
  expect(coldSeconds).toBeLessThan(3);
  expect(renderSeconds).toBeLessThan(2);
});

test("UI-10/11 long words URLs code and fifty-column table stay inside the viewport", async ({
  page,
}) => {
  const user = await account(page);
  const { thread_id } = JSON.parse(
    execFileSync(
      python,
      ["tests/e2e/layout_bulk_fixture.py", "markdown", user],
      { encoding: "utf8", timeout: 60_000 },
    ),
  );
  await page.goto(`/chat/${thread_id}`);
  await expect(page.locator(".message.assistant")).toContainText(
    "Layout evidence",
  );
  const report = [];
  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBeTruthy();
    const code = page.locator(".markdown pre");
    const table = page.locator(".markdown table");
    const codeScroll = await code.evaluate((el) =>
      [el, ...el.querySelectorAll("code")].map((node) => ({
        width: node.clientWidth,
        content: node.scrollWidth,
        overflow: getComputedStyle(node).overflowX,
      })),
    );
    // Syntax highlighting places its own horizontal scroller on the nested
    // code element; either block may correctly contain the overflow.
    expect(
      codeScroll.some(
        (box) =>
          box.content > box.width && ["auto", "scroll"].includes(box.overflow),
      ),
    ).toBeTruthy();
    expect(
      await table.evaluate((el) => el.scrollWidth > el.clientWidth),
    ).toBeTruthy();
    await code.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `artifacts/prepublication/UI-11-code-${width}.png`,
    });
    await table.scrollIntoViewIfNeeded();
    await page.screenshot({
      path: `artifacts/prepublication/UI-11-table-${width}.png`,
    });
    report.push({
      width,
      viewportContained: true,
      codeInnerScroll: true,
      codeScroll,
      tableInnerScroll: true,
    });
  }
  await writeFile(
    "artifacts/prepublication/markdown-layout.json",
    JSON.stringify(report, null, 2),
  );
});
