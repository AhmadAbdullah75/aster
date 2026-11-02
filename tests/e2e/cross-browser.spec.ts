import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

test.skip(
  process.env.NEXUS_CROSS_BROWSER !== "true",
  "Dedicated installed-browser matrix required.",
);
const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);

test("BRW desktop browser registration persistence PDF rendering approval and logout", async ({
  page,
  browser,
}) => {
  test.setTimeout(150_000);
  const email = `publication-browser-${Date.now()}@example.com`;
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Browser");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-browser-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  const user = (await (await page.request.get("/api/me")).json()).id;
  await page.getByRole("link", { name: "Notes", exact: true }).click();
  await page.getByRole("button", { name: "New note", exact: true }).click();
  await page
    .getByLabel("Title", { exact: true })
    .fill("Browser persistence اردو 🌿");
  await page
    .getByLabel("Note · Markdown supported", { exact: true })
    .fill("# Recovery evidence\n\nSaved **Markdown** in this browser.");
  await page.getByRole("button", { name: "Save note", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("heading", {
      name: "Browser persistence اردو 🌿",
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  const pdfPath = path.resolve(".data/prepublication-files/proposal.pdf");
  await page.locator('input[type="file"]').setInputFiles(pdfPath);
  await expect
    .poll(
      async () =>
        (await (await page.request.get("/api/documents")).json()).length,
    )
    .toBe(1);
  const doc = (await (await page.request.get("/api/documents")).json())[0];
  execFileSync(python, ["tests/e2e/ingest_fixture.py", doc.id], {
    timeout: 60_000,
  });
  await page.reload();
  await page
    .getByRole("button", { name: "Preview PDF ↗", exact: true })
    .click();
  await expect(page.getByText("Page 1 of 5", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Rendering PDF page…", { exact: true }),
  ).toHaveCount(0, { timeout: 25_000 });
  expect(
    await page
      .getByRole("img", { name: "PDF page 1", exact: true })
      .evaluate((el) => {
        const canvas = el as HTMLCanvasElement;
        const pixels = canvas
          .getContext("2d")!
          .getImageData(0, 0, canvas.width, canvas.height).data;
        let ink = 0;
        for (let i = 0; i < pixels.length; i += 4)
          if (pixels[i] < 100 && pixels[i + 1] < 100 && pixels[i + 2] < 100)
            ink++;
        return ink;
      }),
  ).toBeGreaterThan(20);
  const original = await page.request.get(
    `/api/documents/${doc.id}/preview?download=true`,
  );
  expect((await original.body()).equals(await readFile(pdfPath))).toBeTruthy();
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
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
    .click();
  execFileSync(python, ["tests/e2e/graph_fixture.py", "resume", thread], {
    timeout: 60_000,
  });
  expect(await (await page.request.get("/api/tasks")).json()).toHaveLength(2);
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-browser-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "Notes", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Browser persistence اردو 🌿",
      exact: true,
    }),
  ).toBeVisible();
  await page.screenshot({
    path: `artifacts/prepublication/BRW-${test.info().project.name}.png`,
  });
  await writeFile(
    `artifacts/prepublication/BRW-${test.info().project.name}.json`,
    JSON.stringify(
      {
        browser: test.info().project.name,
        version: browser.version(),
        registration: true,
        persistedAfterLogin: true,
        pdfCanvasInk: true,
        originalBytesEqual: true,
        approvedTasks: 2,
      },
      null,
      2,
    ),
  );
});
