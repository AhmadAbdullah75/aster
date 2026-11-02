import type { Page } from "@playwright/test";
import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import path from "node:path";

async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Security");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-security-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-security-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
}

test("XSS-01 XSS-02 XSS-03 XSS-04 task and Markdown injection stay inert", async ({
  page,
}) => {
  const dialogs: string[] = [];
  const remoteImages: string[] = [];
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.message());
    await dialog.dismiss();
  });
  page.on("request", (request) => {
    if (request.url().startsWith("https://nexus-xss.invalid/"))
      remoteImages.push(request.url());
  });
  await account(page);
  await page.getByRole("link", { name: "Tasks", exact: true }).click();
  await page.getByRole("button", { name: "New task", exact: true }).click();
  const title = "<script>alert(1)</script>";
  await page.getByLabel("Title", { exact: true }).fill(title);
  await page.getByRole("button", { name: "Save task", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Notes", exact: true }).click();
  await page.getByRole("button", { name: "New note", exact: true }).click();
  await page
    .getByLabel("Title", { exact: true })
    .fill("Hostile Markdown fixture");
  await page
    .getByLabel("Note · Markdown supported")
    .fill(
      "<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))\n\n![remote](https://nexus-xss.invalid/image.png)\n\n<script>alert(2)</script>",
    );
  await page.getByRole("button", { name: "Save note", exact: true }).click();
  await expect(page.locator(".note-preview")).toContainText(
    "<img src=x onerror=alert(1)>",
  );
  expect(await page.locator('a[href^="javascript:"]').count()).toBe(0);
  expect(await page.locator('img[src*="nexus-xss.invalid"]').count()).toBe(0);
  expect(dialogs).toEqual([]);
  expect(remoteImages).toEqual([]);
});

test("XSS-06 XSS-07 HTML in project, instructions, title and name is escaped", async ({
  page,
}) => {
  const dialogs: string[] = [];
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.message());
    await dialog.dismiss();
  });
  await account(page);
  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await page.getByRole("button", { name: "New project", exact: true }).click();
  const projectTitle = "<svg onload=alert(1)>Project</svg>";
  await page.getByLabel("Title", { exact: true }).fill(projectTitle);
  await page
    .getByLabel("Project instructions")
    .fill("<script>alert(2)</script>");
  await page.getByRole("button", { name: "Save project", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: projectTitle, exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: /Publication Security Personal account/ })
    .click();
  const displayName = "<script>alert(3)</script>";
  await page.getByLabel("Name", { exact: true }).fill(displayName);
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: new RegExp("script.*Personal account") }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Conversations", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind.*script/ }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.waitForURL("**/chat/*");
  await page
    .getByRole("button", { name: "Rename New conversation", exact: true })
    .click();
  await page
    .getByLabel("Title", { exact: true })
    .fill("<img src=x onerror=alert(4)>");
  await page
    .getByRole("button", { name: "Save conversation", exact: true })
    .click();
  await expect(
    page.getByRole("link", {
      name: "<img src=x onerror=alert(4)>",
      exact: true,
    }),
  ).toBeVisible();
  expect(dialogs).toEqual([]);
});

test("HDR-01 HDR-02 response policy prevents framing and unsafe destinations", async ({
  page,
}) => {
  const response = await page.goto("/");
  const headers = response!.headers();
  const policy = headers["content-security-policy"];
  expect(policy).toContain("frame-ancestors 'none'");
  expect(policy).toContain("object-src 'none'");
  expect(policy).toContain("connect-src 'self'");
  expect(policy).toContain("form-action 'self'");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  const parent = await page.context().newPage();
  await parent.setContent('<iframe src="http://127.0.0.1:3001/"></iframe>');
  await expect
    .poll(
      async () =>
        parent.frames().filter((frame) => frame.url().includes("3001")).length,
    )
    .toBe(0);
  await parent.close();
});

test("XSS-05 XSS-08 XSS-09 uploaded HTML, assistant projection and hostile filename stay inert", async ({
  page,
}) => {
  const dialogs: string[] = [];
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.message());
    await dialog.dismiss();
  });
  await account(page);
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.waitForURL("**/documents");
  await expect(
    page.getByRole("heading", {
      name: "A fresh space for your documents",
      exact: true,
    }),
  ).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({
    name: "guide.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "# Synthetic source\n<script>alert(1)</script>\n<img src=x onerror=alert(2)>",
    ),
  });
  await expect(
    page.getByRole("heading", { name: "guide.md", exact: true }),
  ).toBeVisible();
  const documents = await (await page.request.get("/api/documents")).json();
  const document = documents.find(
    (item: { filename: string }) => item.filename === "guide.md",
  );
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  execFileSync(python, ["tests/e2e/ingest_fixture.py", document.id]);
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.waitForURL("**/chat/*");
  const thread = page.url().split("/").at(-1)!;
  execFileSync(python, ["tests/e2e/security_fixture.py", thread, document.id]);
  await page.reload();
  await expect(
    page.getByText("<script>alert(1)</script>", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Source ↗", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "<script>alert(1)</script>",
  );
  await page.getByLabel("Close dialog", { exact: true }).click();
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.waitForURL("**/documents");
  await expect(
    page.getByRole("heading", { name: "guide.md", exact: true }),
  ).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({
    name: '"><svg onload=alert(3)>.pdf',
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.7 Synthetic hostile filename fixture"),
  });
  await expect
    .poll(
      async () =>
        (await (await page.request.get("/api/documents")).json()).length,
    )
    .toBe(2);
  const updated = await (await page.request.get("/api/documents")).json();
  const hostile = updated.find(
    (item: { filename: string }) => item.filename !== "guide.md",
  );
  expect(hostile.filename).not.toMatch(/[<>:"/\\|?*]/);
  await expect(
    page.getByRole("heading", { name: hostile.filename, exact: true }),
  ).toBeVisible();
  expect(dialogs).toEqual([]);
});

test("PI-03 real Gemini treats controlled hostile web results as evidence", async ({
  page,
}) => {
  test.skip(
    process.env.NEXUS_LIVE_PREPUBLICATION !== "true",
    "Opt in explicitly for the real provider; default browser suites stay deterministic.",
  );
  test.setTimeout(180_000);
  await account(page);
  const user = await (await page.request.get("/api/me")).json();
  const output = execFileSync(
    path.resolve(
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    ),
    ["tests/e2e/live_injection_fixture.py", user.id],
    { encoding: "utf8", timeout: 150_000 },
  );
  const result = JSON.parse(output.trim());
  expect(result.real_model).toBe(true);
  expect(result.tasks).toBe(0);
  expect(result.proposals).toBe(0);
  await page.goto(`/chat/${result.thread_id}`);
  await expect(
    page.getByText(/20 November 2026|November 20, 2026/),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Approve selection", exact: true }),
  ).toHaveCount(0);
  const history = await (
    await page.request.get(`/api/conversations/${result.thread_id}/history`)
  ).json();
  expect(history.runs.at(-1).status).toBe("completed");
});

test("MOD-05 real Gemini reports controlled web-search failure without claiming verification", async ({
  page,
}) => {
  test.skip(
    process.env.NEXUS_LIVE_PREPUBLICATION !== "true",
    "Explicit real-provider opt-in required.",
  );
  test.setTimeout(180_000);
  await account(page);
  const user = await (await page.request.get("/api/me")).json();
  const output = execFileSync(
    path.resolve(".venv/Scripts/python.exe"),
    ["tests/e2e/live_injection_fixture.py", user.id, "web-failure"],
    { encoding: "utf8", timeout: 150_000 },
  );
  const result = JSON.parse(output.trim());
  await page.goto(`/chat/${result.thread_id}`);
  await expect(page.locator(".message.assistant")).toContainText(
    /unavailable|could not|unable|cannot|failed|couldn't/i,
  );
  const history = await (
    await page.request.get(`/api/conversations/${result.thread_id}/history`)
  ).json();
  expect(history.runs.at(-1).status).toBe("completed");
  expect(
    history.messages
      .filter((message: { role: string }) => message.role === "assistant")
      .every((message: { sources: unknown[] }) => message.sources.length === 0),
  ).toBe(true);
  expect(result.tasks).toBe(0);
  expect(result.proposals).toBe(0);
  await test.info().attach("controlled-backend-failure", {
    body: JSON.stringify({ result, history }),
    contentType: "application/json",
  });
  await page.screenshot({
    path: "artifacts/prepublication/MOD-05.png",
    fullPage: true,
  });
});

test("SECR-05 browser shows a generic retriable error for a 500 response", async ({
  page,
}) => {
  await page.route("**/api/projects?**", (route) =>
    route.fulfill({
      status: 500,
      contentType: "text/plain",
      body: "Internal Server Error",
    }),
  );
  await account(page);
  const alert = page
    .locator(".alert")
    .filter({ hasText: "Workspace data failed to load." });
  await expect(alert).toBeVisible({ timeout: 15_000 });
  await expect(
    page.getByText(/Traceback|RuntimeError|Synthetic internal diagnostic/),
  ).toHaveCount(0);
  await page.unroute("**/api/projects?**");
  await alert.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(alert).not.toBeVisible();
});
