import { test, expect } from "./isolation";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";

test("PDF-01/02/03/04/05/06/07/09 real rendering, controls, private download, local assets and hostile pages", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const python = path.resolve(
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const files = execFileSync(python, ["tests/e2e/ingest_fixture.py", "files"], {
    encoding: "utf8",
  }).trim();
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page.getByLabel("Your name", { exact: true }).fill("Publication PDF");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-pdf-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-pdf-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Documents", exact: true })).toBeVisible();
  for (const filename of [
    "Audit.pdf",
    "Audit-interactive.pdf",
    "Audit-huge-page.pdf",
  ]) {
    await page
      .locator('input[type="file"]')
      .setInputFiles(path.join(files, filename));
    await expect(
      page.getByRole("heading", { name: filename, exact: true }),
    ).toBeVisible();
  }
  const docs = await (await page.request.get("/api/documents")).json();
  for (const doc of docs)
    execFileSync(python, ["tests/e2e/ingest_fixture.py", doc.id], {
      timeout: 30_000,
    });
  await page.reload();
  const urls: string[] = [];
  const dialogs: string[] = [];
  const popups: string[] = [];
  page.on("request", (request) => urls.push(request.url()));
  page.on("dialog", async (dialog) => {
    dialogs.push(dialog.message());
    await dialog.dismiss();
  });
  page.on("popup", (popup) => popups.push(popup.url()));
  async function preview(filename: string) {
    await page
      .locator(".resource-card")
      .filter({
        has: page.getByRole("heading", { name: filename, exact: true }),
      })
      .getByRole("button", { name: "Preview PDF ↗", exact: true })
      .click();
    await expect(
      page.getByText("Rendering PDF page…", { exact: true }),
    ).not.toBeVisible({ timeout: 25_000 });
    await expect(
      page.getByRole("img", { name: "PDF page 1", exact: true }),
    ).toBeVisible();
  }
  await preview("Audit.pdf");
  await expect(
    page.getByRole("button", { name: "Previous page", exact: true }),
  ).toBeDisabled();
  const canvas = page.getByRole("img", { name: "PDF page 1", exact: true });
  expect(
    await canvas.evaluate((el) => {
      const c = el as HTMLCanvasElement,
        p = c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data;
      let ink = 0;
      for (let i = 0; i < p.length; i += 4)
        if (p[i] < 100 && p[i + 1] < 100 && p[i + 2] < 100) ink++;
      return ink;
    }),
  ).toBeGreaterThan(20);
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(page.getByText("Page 2 of 2", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Rendering PDF page…", { exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next page", exact: true }),
  ).toBeDisabled();
  await page.getByText("Page text", { exact: true }).click();
  await expect(
    page.getByText("Second audit page.", { exact: true }),
  ).toBeVisible();
  for (const zoom of ["2", "1.25", "1"]) {
    await page.getByLabel("PDF zoom", { exact: true }).selectOption(zoom);
    await expect(
      page.getByText("Rendering PDF page…", { exact: true }),
    ).not.toBeVisible();
    await expect(
      page.getByRole("img", { name: "PDF page 2", exact: true }),
    ).toBeVisible();
  }
  await page
    .getByRole("button", { name: "Previous page", exact: true })
    .click();
  await expect(page.getByText("Page 1 of 2", { exact: true })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "Download original PDF", exact: true })
    .click();
  const download = await downloadPromise;
  expect(await readFile((await download.path())!)).toEqual(
    await readFile(path.join(files, "Audit.pdf")),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("PDF zoom", { exact: true })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
  await page.screenshot({ path: "artifacts/prepublication/PDF-09-mobile.png" });
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
  await page.setViewportSize({ width: 1280, height: 900 });
  await preview("Audit-interactive.pdf");
  expect(dialogs).toEqual([]);
  expect(popups).toEqual([]);
  expect(urls.some((url) => url.includes("127.0.0.1:9/pdf-js"))).toBeFalsy();
  await expect(page.locator('input[name="synthetic-field"]')).toHaveCount(0);
  await page.getByRole("button", { name: "Close dialog", exact: true }).click();
  await preview("Audit-huge-page.pdf");
  const dimensions = await page
    .getByRole("img", { name: "PDF page 1", exact: true })
    .evaluate((el) => ({
      width: (el as HTMLCanvasElement).width,
      height: (el as HTMLCanvasElement).height,
    }));
  expect(dimensions.width).toBeLessThanOrEqual(8192);
  expect(dimensions.height).toBeLessThanOrEqual(8192);
  expect(dimensions.width * dimensions.height).toBeLessThanOrEqual(8_010_000);
  expect(
    urls.some((url) => url.includes("/pdf-assets/pdf.worker.min.mjs")),
  ).toBeTruthy();
  expect(
    urls
      .filter((url) => url.includes("/pdf-assets/"))
      .every((url) => new URL(url).origin === "http://127.0.0.1:3001"),
  ).toBeTruthy();
  await page.screenshot({
    path: "artifacts/prepublication/PDF-07-bounded.png",
  });
});
