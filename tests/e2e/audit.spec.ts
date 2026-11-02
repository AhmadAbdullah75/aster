import type { Page } from "@playwright/test";
import { test, expect } from "./isolation";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";

const password = "synthetic-audit-password";
async function account(page: Page) {
  const email = `audit-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page.getByLabel("Your name", { exact: true }).fill("Audit Tester");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  return email;
}
async function open(page: Page, name: string) {
  const menu = page.getByLabel("Open navigation", { exact: true });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("link", { name, exact: true }).click();
  await page.waitForURL(
    `**/${name === "Conversations" ? "chat" : name.toLowerCase()}`,
  );
  if (name !== "Conversations")
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
}
async function create(page: Page, kind: string, title: string) {
  await page.getByRole("button", { name: `New ${kind}`, exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill(title);
}
async function save(page: Page, kind: string) {
  await page.getByRole("button", { name: `Save ${kind}`, exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
}
async function remove(page: Page, title: string) {
  await page
    .getByRole("button", { name: `Delete ${title}`, exact: true })
    .click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
}

test("205 histories remain visible, new chat clears hiding filters, reopen/reload/logout/login preserve messages", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const email = await account(page);
  const user = await (await page.request.get("/api/me")).json();
  execFileSync(path.resolve(".venv/Scripts/python.exe"), [
    "tests/e2e/audit_fixture.py",
    user.id,
  ]);
  await page.reload();
  await page.getByLabel("Search conversations").fill("Audit history 000");
  await page
    .getByRole("link", { name: "Audit history 000", exact: true })
    .click();
  await expect(
    page.getByText("Saved audit reply 000", { exact: true }),
  ).toBeVisible();
  const savedThreadUrl = page.url();
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.waitForURL(
    (url) =>
      url.href !== savedThreadUrl && /^\/chat\/[a-f0-9-]+$/.test(url.pathname),
  );
  await expect(page.getByLabel("Search conversations")).toHaveValue("");
  await expect(page.locator(".conversation-list a")).toHaveCount(206);
  await page
    .getByRole("link", { name: "Audit history 000", exact: true })
    .click();
  await page.waitForURL(savedThreadUrl);
  await expect(
    page.getByText("Saved audit reply 000", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Saved audit message 000", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Saved audit reply 000", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back" }),
  ).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page
    .getByRole("link", { name: "Audit history 000", exact: true })
    .click();
  await expect(
    page.getByText("Saved audit reply 000", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/audit-history.png",
    fullPage: true,
  });
});

test("conversation rename, archive/unarchive, filter visibility, new chat from archive, deletion", async ({
  page,
}) => {
  await account(page);
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.getByLabel("Rename New conversation", { exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Audit renamed chat");
  await save(page, "conversation");
  await page.getByLabel("Archive Audit renamed chat", { exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Audit renamed chat", exact: true }),
  ).not.toBeVisible();
  await page.getByLabel("Toggle archived conversations").click();
  await expect(
    page.getByText("ARCHIVED CONVERSATIONS", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Audit renamed chat", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await expect(
    page.getByLabel("Toggle archived conversations"),
  ).toHaveAttribute("aria-pressed", "false");
  await expect(
    page.getByRole("link", { name: "New conversation", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Toggle archived conversations").click();
  await page
    .getByLabel("Unarchive Audit renamed chat", { exact: true })
    .click();
  await page
    .getByRole("button", { name: /Clear conversation filters/ })
    .click();
  await expect(
    page.getByRole("link", { name: "Audit renamed chat", exact: true }),
  ).toBeVisible();
  await remove(page, "Audit renamed chat");
  await expect(
    page.getByRole("link", { name: "Audit renamed chat", exact: true }),
  ).not.toBeVisible();
});

test("project instructions edit, scoped task and note, complete/reopen/filter and full deletion cascade", async ({
  page,
}) => {
  await account(page);
  await open(page, "Projects");
  await create(page, "project", "Audit project");
  await page
    .getByLabel("Project instructions")
    .fill("Use the project vocabulary.");
  await save(page, "project");
  await page.getByLabel("Edit Audit project").click();
  await page
    .getByLabel("Description", { exact: true })
    .fill("Edited project description");
  await save(page, "project");
  await expect(
    page.getByText("Edited project description", { exact: true }),
  ).toBeVisible();
  await open(page, "Tasks");
  await create(page, "task", "Audit task");
  await page
    .getByLabel("Item project")
    .selectOption({ label: "Audit project" });
  await page
    .getByRole("combobox", { name: "Priority", exact: true })
    .selectOption("high");
  await page
    .getByRole("combobox", { name: "Status", exact: true })
    .selectOption("in_progress");
  await page.getByLabel("Due date", { exact: true }).fill("2030-06-15");
  await save(page, "task");
  await page.getByLabel("Filter task status").selectOption("todo");
  await expect(
    page.getByRole("heading", { name: "Audit task", exact: true }),
  ).not.toBeVisible();
  await page.getByLabel("Filter task status").selectOption("in_progress");
  await expect(
    page.getByRole("heading", { name: "Audit task", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Switch to task board").click();
  await page.getByRole("button", { name: "Mark done", exact: true }).click();
  await page.getByLabel("Filter task status").selectOption("done");
  await page.getByRole("button", { name: "Reopen task", exact: true }).click();
  await page.getByLabel("Filter task status").selectOption("");
  await page.getByLabel("Edit Audit task").click();
  await page.getByLabel("Title", { exact: true }).fill("Edited audit task");
  await save(page, "task");
  await open(page, "Notes");
  await create(page, "note", "Audit note");
  await page
    .getByLabel("Item project")
    .selectOption({ label: "Audit project" });
  await page
    .getByLabel("Note · Markdown supported")
    .fill("## Decision\nUnique body-search needle");
  await save(page, "note");
  await expect(
    page.getByRole("heading", { name: "Decision", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Search notes").fill("body-search");
  await expect(
    page.getByRole("heading", { name: "Audit note", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Edit Audit note").click();
  await page
    .getByLabel("Note · Markdown supported")
    .fill("## Revised\nFinal decision.");
  await save(page, "note");
  await page.getByLabel("Search notes").fill("");
  await expect(
    page.getByRole("heading", { name: "Revised", exact: true }),
  ).toBeVisible();
  await open(page, "Projects");
  await remove(page, "Audit project");
  await open(page, "Tasks");
  await expect(
    page.getByRole("heading", { name: "Edited audit task", exact: true }),
  ).not.toBeVisible();
  await open(page, "Notes");
  await expect(
    page.getByRole("heading", { name: "Audit note", exact: true }),
  ).not.toBeVisible();
});

test("document limits, unsupported and empty input, duplicate handling, filename search and deletion", async ({
  page,
}) => {
  await account(page);
  await open(page, "Documents");
  await expect(page.getByText(/10 MiB per file/)).toBeVisible();
  const input = page.locator("input[type=file]");
  await input.setInputFiles({
    name: "unsupported.exe",
    mimeType: "application/octet-stream",
    buffer: Buffer.from("MZ"),
  });
  await expect(page.locator(".alert[role=alert]")).toContainText(
    "Supported formats",
  );
  await page.getByLabel("Dismiss error").click();
  await input.setInputFiles({
    name: "empty.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(0),
  });
  await expect(page.locator(".alert[role=alert]")).toContainText("empty");
  await page.getByLabel("Dismiss error").click();
  await input.setInputFiles({
    name: "oversize.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(10 * 1024 * 1024 + 1, 65),
  });
  await expect(page.locator(".alert[role=alert]")).toContainText("10 MiB");
  await page.getByLabel("Dismiss error").click();
  const file = {
    name: "Audit knowledge.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# Audit\nCopper Finch launches in June."),
  };
  await input.setInputFiles(file);
  await expect(
    page.getByRole("heading", { name: "Audit knowledge.md", exact: true }),
  ).toBeVisible();
  await input.setInputFiles(file);
  await expect(
    page.getByRole("heading", { name: "Audit knowledge.md", exact: true }),
  ).toHaveCount(1);
  await page.getByLabel("Search documents").fill("missing");
  await expect(
    page.getByRole("heading", { name: "Audit knowledge.md", exact: true }),
  ).not.toBeVisible();
  await page.getByLabel("Search documents").fill("knowledge");
  await expect(
    page.getByRole("heading", { name: "Audit knowledge.md", exact: true }),
  ).toBeVisible();
  await remove(page, "Audit knowledge.md");
  await expect(
    page.getByRole("heading", { name: "Audit knowledge.md", exact: true }),
  ).not.toBeVisible();
});

test("memory edit/toggle/reload/delete/clear and settings validation/persistence", async ({
  page,
}) => {
  await account(page);
  await open(page, "Memories");
  for (const title of ["Audit preference", "Audit goal"]) {
    await create(page, "memory", title);
    await page
      .getByLabel("What should Aster remember?")
      .fill("Prefer concise explanations.");
    await page
      .getByRole("combobox", { name: "Category", exact: true })
      .selectOption("goal");
    await save(page, "memory");
  }
  await page.getByLabel("Edit Audit preference", { exact: true }).click();
  await page
    .getByLabel("What should Aster remember?")
    .fill("Prefer detailed examples.");
  await save(page, "memory");
  await expect(
    page.getByText("Prefer detailed examples.", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Enable Audit preference", { exact: true }).uncheck();
  await expect(
    page.getByLabel("Enable Audit preference", { exact: true }),
  ).toBeEnabled();
  await page.reload();
  await expect(
    page.getByLabel("Enable Audit preference", { exact: true }),
  ).not.toBeChecked();
  await remove(page, "Audit goal");
  await page.getByRole("button", { name: "Clear all", exact: true }).click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Audit preference", exact: true }),
  ).not.toBeVisible();
  await page.getByRole("link", { name: /Audit Tester/ }).click();
  await page.getByLabel("Timezone", { exact: true }).fill("Invalid/Timezone");
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(page.locator(".alert[role=alert]")).toBeVisible();
  await page.getByLabel("Dismiss error").click();
  await page.getByLabel("Timezone", { exact: true }).fill("Asia/Karachi");
  await page.getByLabel("Name", { exact: true }).fill("Audit Renamed");
  await page
    .getByRole("combobox", { name: "Appearance", exact: true })
    .selectOption("dark");
  await page
    .getByLabel("Allow Aster to read and propose saved memories")
    .uncheck();
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    page.getByText("Preferences saved", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue(
    "Audit Renamed",
  );
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByLabel("Allow Aster to read and propose saved memories"),
  ).not.toBeChecked();
});

test("invalid sign-in and registration validation, sidebar collapse, keyboard dialog dismissal", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill("nobody@example.com");
  await page.getByLabel("Password", { exact: true }).fill("incorrect-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".alert[role=alert]")).toContainText(
    /Invalid|incorrect|credentials/i,
  );
  await account(page);
  await page.getByLabel("Collapse sidebar", { exact: true }).click();
  await expect(page.locator(".sidebar")).toHaveClass(/sidebar-collapsed/);
  await page.getByLabel("Expand sidebar", { exact: true }).click();
  await open(page, "Tasks");
  await create(page, "task", "Discard this draft");
  await page.getByLabel("Title", { exact: true }).press("Escape");
  await expect(
    page.getByRole("heading", {
      name: "Discard unsaved changes?",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Discard changes", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Discard this draft", exact: true }),
  ).not.toBeVisible();
});

for (const action of ["notes.create", "memories.create", "reject"])
  test(`approval ${action}: real graph, reload and collection outcome`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await account(page);
    const user = await (await page.request.get("/api/me")).json();
    const python = path.resolve(
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    );
    const thread = execFileSync(
      python,
      [
        "tests/e2e/graph_fixture.py",
        "seed",
        user.id,
        action === "reject" ? "tasks.create" : action,
      ],
      { encoding: "utf8" },
    )
      .trim()
      .split(/\r?\n/)
      .at(-1)!;
    await page.goto("/chat/" + thread);
    await page.reload();
    if (action === "reject") {
      await page.getByRole("button", { name: "Reject", exact: true }).click();
    } else {
      await page
        .getByRole("button", { name: "Edit proposal", exact: true })
        .click();
      await page
        .getByLabel("Title", { exact: true })
        .first()
        .fill("Edited approved item");
      await page
        .getByRole("textbox", { name: "Content", exact: true })
        .first()
        .fill("User-edited approved content");
      if (action === "memories.create") {
        await page
          .getByLabel("Memory category", { exact: true })
          .first()
          .selectOption("goal");
        await page
          .getByLabel("Enable proposed memory", { exact: true })
          .first()
          .uncheck();
      }
      await page.getByLabel("Include proposed item 2").uncheck();
      await page
        .getByRole("button", { name: "Approve edited selection", exact: true })
        .click();
    }
    await expect(
      page.getByRole("button", { name: "Approve selection", exact: true }),
    ).not.toBeVisible();
    execFileSync(python, ["tests/e2e/graph_fixture.py", "resume", thread], {
      encoding: "utf8",
    });
    await page.reload();
    if (action === "reject") {
      await expect(page.locator(".approval-card")).toHaveCount(0);
      expect(
        (
          await (
            await page.request.get("/api/conversations/" + thread + "/history")
          ).json()
        ).proposals.at(-1).status,
      ).toBe("rejected");
      await open(page, "Tasks");
      await expect(page.locator(".resource-card")).toHaveCount(0);
    } else {
      await expect(page.locator(".approval-card")).toHaveCount(0);
      expect(
        (
          await (
            await page.request.get("/api/conversations/" + thread + "/history")
          ).json()
        ).proposals.at(-1).status,
      ).toBe("completed");
      await open(page, action.startsWith("notes") ? "Notes" : "Memories");
      await expect(
        page.getByRole("heading", {
          name: "Edited approved item",
          exact: true,
        }),
      ).toBeVisible();
      await expect(
        page.getByText("User-edited approved content", { exact: true }),
      ).toBeVisible();
      await expect(page.locator(".resource-card")).toHaveCount(1);
      if (action === "memories.create") {
        await expect(
          page.getByLabel("Enable Edited approved item", { exact: true }),
        ).not.toBeChecked();
        await expect(page.locator(".resource-card")).toContainText("goal");
      }
    }
  });

test("PDF/DOCX/TXT/MD index, secure preview, reindex, failed extraction and retry", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await account(page);
  await open(page, "Documents");
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const files = execFileSync(python, ["tests/e2e/ingest_fixture.py", "files"], {
    encoding: "utf8",
  }).trim();
  for (const filename of ["Audit.pdf", "Audit.docx"]) {
    await page
      .locator("input[type=file]")
      .setInputFiles(path.join(files, filename));
    await expect(
      page.getByRole("heading", { name: filename, exact: true }),
    ).toBeVisible();
  }
  for (const extension of ["txt", "md"])
    await page.locator("input[type=file]").setInputFiles({
      name: `Audit.${extension}`,
      mimeType: extension === "txt" ? "text/plain" : "text/markdown",
      buffer: Buffer.from(`${extension} Copper Finch launches in June.`),
    });
  await expect(page.locator(".resource-card")).toHaveCount(4);
  const docs = await (await page.request.get("/api/documents")).json();
  for (const doc of docs)
    execFileSync(python, ["tests/e2e/ingest_fixture.py", doc.id]);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Reindex document", exact: true }),
  ).toHaveCount(4);
  const pdf = docs.find(
    (doc: { filename: string }) => doc.filename === "Audit.pdf",
  );
  const preview = await page.request.get(`/api/documents/${pdf.id}/preview`);
  expect(preview.headers()["content-type"]).toContain("application/pdf");
  expect(preview.status()).toBe(200);
  await page
    .getByRole("button", { name: "Preview PDF ↗", exact: true })
    .click();
  await expect(page.getByText("Page 1 of 2", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Rendering PDF page…", { exact: true }),
  ).not.toBeVisible({ timeout: 20_000 });
  const canvas = page.getByRole("img", { name: "PDF page 1", exact: true });
  expect(
    await canvas.evaluate((element) => {
      const image = element as HTMLCanvasElement;
      const pixels = image
        .getContext("2d")!
        .getImageData(0, 0, image.width, image.height).data;
      let ink = 0;
      for (let i = 0; i < pixels.length; i += 4)
        if (pixels[i] < 100 && pixels[i + 1] < 100 && pixels[i + 2] < 100)
          ink++;
      return ink > 20;
    }),
  ).toBeTruthy();
  await page.screenshot({
    path: "artifacts/audit-pdf-preview.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(page.getByText("Page 2 of 2", { exact: true })).toBeVisible();
  await page.getByText("Page text", { exact: true }).click();
  await expect(
    page.getByText("Second audit page.", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("PDF zoom", { exact: true }).selectOption("1.5");
  await expect(
    page.getByRole("button", { name: "Previous page", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Previous page", exact: true })
    .click();
  await expect(page.getByText("Page 1 of 2", { exact: true })).toBeVisible();
  const original = await page.request.get(
    `/api/documents/${pdf.id}/preview?download=true`,
  );
  expect(original.headers()["content-disposition"]).toContain("attachment");
  await page.getByLabel("Close dialog", { exact: true }).click();
  await page
    .locator(".resource-card")
    .filter({
      has: page.getByRole("heading", { name: "Audit.pdf", exact: true }),
    })
    .getByRole("button", { name: "Reindex document", exact: true })
    .click();
  execFileSync(python, ["tests/e2e/ingest_fixture.py", pdf.id]);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Reindex document", exact: true }),
  ).toHaveCount(4);
  await page.locator("input[type=file]").setInputFiles({
    name: "Malformed.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from(
      "%PDF-1.7\n1 0 obj\n<< /Type /Broken >>\nendobj\n%%EOF\n",
    ),
  });
  await expect(
    page.getByRole("heading", { name: "Malformed.pdf", exact: true }),
  ).toBeVisible();
  const malformed = (
    await (await page.request.get("/api/documents")).json()
  ).find((doc: { filename: string }) => doc.filename === "Malformed.pdf");
  execFileSync(python, ["tests/e2e/ingest_fixture.py", malformed.id]);
  await page.reload();
  await expect(
    page.getByText(
      "Malformed or corrupted PDF. Re-export the PDF and try again.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Retry indexing", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Retry indexing", exact: true }),
  ).not.toBeVisible();
  await expect(
    page.locator(".resource-card").filter({ hasText: "Malformed.pdf" }),
  ).toContainText("queued");
});

test("project workspace retains project through navigation and personal chat clears inherited scope", async ({
  page,
}) => {
  await account(page);
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page.waitForURL(/\/chat\/[a-f0-9-]+$/);
  const personal = page.url();
  await open(page, "Projects");
  await create(page, "project", "Audit scope");
  await save(page, "project");
  await page
    .getByRole("button", { name: "Open project workspace ↗", exact: true })
    .click();
  await expect(page.getByLabel("Chat project", { exact: true })).toHaveValue(
    /.+/,
  );
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await expect(page.locator(".chat-toolbar")).toContainText("Audit scope");
  await page
    .locator(`.conversation-list a[href="${new URL(personal).pathname}"]`)
    .click();
  await expect(page.locator(".chat-toolbar")).toContainText(
    "Personal conversation",
  );
});

for (const kind of ["tasks", "notes", "memories"])
  for (const operation of ["update", "delete"])
    test(`approval ${kind}.${operation} changes only approved existing item`, async ({
      page,
    }) => {
      test.setTimeout(120_000);
      await account(page);
      const user = await (await page.request.get("/api/me")).json();
      const target = await (
        await page.request.post("/api/" + kind, {
          headers: { origin: "http://127.0.0.1:3001" },
          data: {
            title: "Audit existing item",
            ...(kind !== "tasks" ? { content: "Original content" } : {}),
          },
        })
      ).json();
      const payload = [
        {
          id: target.id,
          version: target.version,
          title: operation === "update" ? "Audit updated item" : target.title,
          ...(kind !== "tasks" ? { content: "Updated approved content" } : {}),
        },
      ];
      const python = path.resolve(
        ".venv",
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      );
      const thread = execFileSync(
        python,
        [
          "tests/e2e/graph_fixture.py",
          "seed",
          user.id,
          `${kind}.${operation}`,
          JSON.stringify(payload),
        ],
        { encoding: "utf8" },
      )
        .trim()
        .split(/\r?\n/)
        .at(-1)!;
      await page.goto("/chat/" + thread);
      await page
        .getByRole("button", { name: "Approve selection", exact: true })
        .click();
      await expect(
        page.getByRole("button", { name: "Approve selection", exact: true }),
      ).not.toBeVisible();
      execFileSync(python, ["tests/e2e/graph_fixture.py", "resume", thread]);
      await page.reload();
      await expect(page.locator(".approval-card")).toHaveCount(0);
      expect(
        (
          await (
            await page.request.get("/api/conversations/" + thread + "/history")
          ).json()
        ).proposals.at(-1).status,
      ).toBe("completed");
      await open(page, kind[0].toUpperCase() + kind.slice(1));
      if (operation === "delete")
        await expect(page.locator(".resource-card")).toHaveCount(0);
      else
        await expect(
          page.getByRole("heading", {
            name: "Audit updated item",
            exact: true,
          }),
        ).toBeVisible();
    });

for (const width of [390, 768, 1440])
  test(`all navigation screens, drawer/logout, focus and overflow at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 850 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await account(page);
    for (const screen of [
      "Projects",
      "Documents",
      "Tasks",
      "Notes",
      "Memories",
      "Conversations",
    ]) {
      await open(page, screen);
      if (screen !== "Conversations")
        await expect(
          page.getByRole("heading", { name: screen, exact: true }),
        ).toBeVisible();
      else
        await expect(
          page.getByLabel("Message Aster", { exact: true }),
        ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
    }
    await page.getByLabel("Message Aster", { exact: true }).fill("First line");
    await page
      .getByLabel("Message Aster", { exact: true })
      .press("Shift+Enter");
    await page.getByLabel("Message Aster", { exact: true }).press("x");
    await expect(page.getByLabel("Message Aster", { exact: true })).toHaveValue(
      "First line\nx",
    );
    await expect(
      page.getByLabel("Send message", { exact: true }),
    ).toBeDisabled();
    for (const title of [
      "Explore an idea",
      "Understand a document",
      "Make a plan",
      "Build something",
    ]) {
      await page.getByRole("button", { name: new RegExp(`^${title}`) }).click();
      await expect(
        page.getByLabel("Message Aster", { exact: true }),
      ).not.toHaveValue("");
    }
    await page.getByRole("button", { name: "Sources", exact: true }).click();
    await expect(
      page.getByText("No documents yet. Attach a file to add one.", {
        exact: true,
      }),
    ).toBeVisible();
    await page.getByLabel("Close sources", { exact: true }).click();
    if (width <= 800) {
      await page.getByLabel("Open navigation", { exact: true }).click();
      await page.getByRole("link", { name: "Projects", exact: true }).focus();
      await page
        .getByRole("link", { name: "Projects", exact: true })
        .press("Escape");
      await expect(
        page.getByRole("link", { name: "Projects", exact: true }),
      ).not.toBeVisible();
      await expect(
        page.getByLabel("Open navigation", { exact: true }),
      ).toBeFocused();
      await page.getByLabel("Open navigation", { exact: true }).click();
    }
    await expect(
      page.getByRole("button", { name: "Log out", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `artifacts/audit-navigation-${width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Log out", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Welcome back", exact: true }),
    ).toBeVisible();
  });

test("attached document selection, indexing failure, clear scope and guarded keyboard send", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await account(page);
  await page.locator("input[type=file]").setInputFiles({
    name: "Audit broken.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.7\nnot a valid PDF cross-reference\n%%EOF\n"),
  });
  await expect(
    page.getByRole("button", { name: "Clear source selection", exact: true }),
  ).toBeVisible();
  const docs = await (await page.request.get("/api/documents")).json();
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  execFileSync(python, ["tests/e2e/ingest_fixture.py", docs[0].id]);
  await expect(
    page.getByText(/An attachment could not be processed/),
  ).toBeVisible({ timeout: 15_000 });
  await expect(
    page.getByText(
      "Malformed or corrupted PDF. Re-export the PDF and try again.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear source selection", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Clear source selection", exact: true }),
  ).not.toBeVisible();
  let submissions = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/runs"))
      submissions++;
  });
  await page
    .getByLabel("Message Aster", { exact: true })
    .fill("Do not send while unavailable");
  await page.getByLabel("Message Aster", { exact: true }).press("Enter");
  expect(submissions).toBe(0);
  await expect(page.getByLabel("Message Aster", { exact: true })).toHaveValue(
    "Do not send while unavailable",
  );
});

test("real streaming events, navigation/reload, jump to latest, stop and prepare retry", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await account(page);
  const user = await (await page.request.get("/api/me")).json();
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const thread = execFileSync(
    python,
    ["tests/e2e/stream_fixture.py", "seed", user.id],
    { encoding: "utf8" },
  ).trim();
  const worker = spawn(python, ["tests/e2e/stream_fixture.py", "run", thread], {
    stdio: "pipe",
  });
  let stderr = "";
  worker.stderr.on("data", (chunk) => (stderr += chunk.toString()));
  try {
    await page.goto("/chat/" + thread);
    await expect(page.getByText(/Audit stream paragraph 009/)).toBeVisible({
      timeout: 30_000,
    });
    await page.locator(".chat-scroll").hover();
    await page.mouse.wheel(0, -3000);
    await expect(
      page.getByRole("button", { name: "Latest", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Latest", exact: true }).click();
    await open(page, "Notes");
    await page.goBack();
    await page.waitForURL(`**/chat/${thread}`);
    await expect(
      page.getByLabel("Stop generation", { exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(page.getByText(/Audit stream paragraph 000/)).toBeAttached();
    await page.getByLabel("Stop generation", { exact: true }).click();
    await expect(page.locator(".alert[role=alert]")).toContainText(
      "Generation stopped. Your saved messages remain.",
      { timeout: 15_000 },
    );
    await expect(
      page.getByText("Interrupted · partial response", { exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Prepare retry", exact: true })
      .click();
    await expect(page.getByLabel("Message Aster", { exact: true })).toHaveValue(
      "Audit long response",
    );
    await page.reload();
    await expect(
      page.getByText("Interrupted · partial response", { exact: true }),
    ).toBeVisible();
    const history = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(history.runs.at(-1).status, stderr).toBe("canceled");
    expect(
      history.messages.filter((m: { role: string }) => m.role === "assistant"),
    ).toHaveLength(1);
    await page.screenshot({
      path: "artifacts/audit-cancellation.png",
      fullPage: true,
    });
  } finally {
    worker.kill();
  }
});

test("System appearance follows OS changes and quick toggle inverts resolved theme", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "light" });
  await account(page);
  await page.getByRole("link", { name: /Audit Tester/ }).click();
  await page
    .getByRole("combobox", { name: "Appearance", exact: true })
    .selectOption("system");
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    page.getByText("Preferences saved", { exact: true }),
  ).toBeVisible();
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByLabel("Toggle dark mode", { exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(
    page.getByRole("combobox", { name: "Appearance", exact: true }),
  ).toHaveValue("light");
  await page.reload();
  await expect(
    page.getByRole("combobox", { name: "Appearance", exact: true }),
  ).toHaveValue("light");
});

test("101 memories paginate without repeating rows and search resets the page", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await account(page);
  for (let number = 0; number < 101; number++) {
    const created = await page.request.post("/api/memories", {
      headers: { origin: "http://127.0.0.1:3001" },
      data: {
        title: `Audit pagination ${String(number).padStart(3, "0")}`,
        content: "Synthetic pagination preference",
      },
    });
    expect(created.ok()).toBeTruthy();
  }
  await open(page, "Memories");
  await expect(page.locator(".resource-card")).toHaveCount(100);
  const firstPage = await page.locator(".resource-card h3").allTextContents();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.locator(".resource-card")).toHaveCount(1);
  const last = await page.locator(".resource-card h3").innerText();
  expect(firstPage).not.toContain(last);
  await expect(page.getByText("101–101", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.locator(".resource-card")).toHaveCount(100);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page
    .getByLabel("Search memories", { exact: true })
    .fill("Audit pagination 000");
  await expect(page.locator(".resource-card")).toHaveCount(1);
  await expect(
    page.getByRole("heading", { name: "Audit pagination 000", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next", exact: true }),
  ).not.toBeVisible();
});
