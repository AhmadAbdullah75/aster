import { test, expect } from "./isolation";
import type { Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const python = path.resolve(
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const files = path.resolve(".data/prepublication-files");
test.beforeAll(() => {
  execFileSync(python, [
    "scripts/prepublication_fixtures.py",
    "--full",
    "--extended",
  ]);
});
async function account(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Upload");
  await page
    .getByLabel("Email", { exact: true })
    .fill(
      `publication-upload-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`,
    );
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-upload-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  const user = (await (await page.request.get("/api/me")).json()).id as string;
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.waitForURL("**/documents");
  await expect(
    page.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  await expect(page.locator('input[type="file"]')).toHaveAttribute(
    "multiple",
    "",
  );
  return user;
}
const card = (page: Page, name: string) =>
  page
    .locator(".resource-card")
    .filter({ has: page.getByRole("heading", { name, exact: true }) });
async function ingest(page: Page, user: string) {
  execFileSync(python, ["tests/e2e/ingest_fixture.py", "user", user], {
    timeout: 60_000,
  });
  await page.reload();
}

test("UPL-01/02/18 PDF picker and drop both index, anonymous original denied", async ({
  page,
  browser,
}) => {
  test.setTimeout(100_000);
  const user = await account(page);
  await page
    .locator('input[type="file"]')
    .setInputFiles(path.join(files, "proposal.pdf"));
  await expect(card(page, "proposal.pdf")).toBeVisible();
  const bytes = Buffer.concat([
    readFileSync(path.join(files, "proposal.pdf")),
    Buffer.from("\n% Synthetic drag/drop variant\n"),
  ]);
  const dataTransfer = await page.evaluateHandle((encoded) => {
    const transfer = new DataTransfer();
    transfer.items.add(
      new File(
        [
          Uint8Array.from(atob(encoded), (character) =>
            character.charCodeAt(0),
          ),
        ],
        "drop-proposal.pdf",
        { type: "application/pdf" },
      ),
    );
    return transfer;
  }, bytes.toString("base64"));
  await page
    .locator(".upload-zone")
    .dispatchEvent("dragover", { dataTransfer });
  await expect(page.locator(".upload-zone")).toHaveClass(/dragging/);
  await page.locator(".upload-zone").dispatchEvent("drop", { dataTransfer });
  await expect(card(page, "drop-proposal.pdf")).toBeVisible();
  await ingest(page, user);
  await expect(
    card(page, "proposal.pdf").getByText("ready", { exact: true }),
  ).toBeVisible();
  await expect(
    card(page, "drop-proposal.pdf").getByText("ready", { exact: true }),
  ).toBeVisible();
  const docs = await (await page.request.get("/api/documents")).json();
  const anonymous = await browser.newContext();
  try {
    const response = await anonymous.request.get(
      `http://127.0.0.1:3001/api/documents/${docs[0].id}/preview?download=true`,
    );
    expect(response.status()).toBe(401);
  } finally {
    await anonymous.close();
  }
});

test("UPL-03/PRS-07/11/14/17 real DOCX table, TXT/BOM, Urdu and Markdown parse to ready", async ({
  page,
}) => {
  test.setTimeout(100_000);
  const user = await account(page);
  const names = [
    "notes.docx",
    "plain.txt",
    "bom.txt",
    "urdu.txt",
    "guide.md",
    "textbox.docx",
    "mixed.pdf",
  ];
  await page
    .locator('input[type="file"]')
    .setInputFiles(names.map((name) => path.join(files, name)));
  await expect(page.locator(".resource-card")).toHaveCount(names.length);
  await ingest(page, user);
  for (const name of names)
    await expect(
      card(page, name).getByText("ready", { exact: true }),
    ).toBeVisible();
  expect(
    await page.locator("script").filter({ hasText: "alert(1)" }).count(),
  ).toBe(0);
});

test("UPL-04/05/07/08 exact upload limit and rejected over-limit/empty/unsupported files", async ({
  page,
}) => {
  test.setTimeout(100_000);
  const user = await account(page);
  const input = page.locator('input[type="file"]');
  await input.setInputFiles(path.join(files, "exactly_10MiB.txt"));
  await expect(card(page, "exactly_10MiB.txt")).toBeVisible();
  await ingest(page, user);
  await expect(card(page, "exactly_10MiB.txt")).toContainText(
    "two million character limit",
  );
  for (const [name, buffer, expected] of [
    ["over.txt", Buffer.alloc(10 * 1024 * 1024 + 1), /10 MiB/],
    ["empty.txt", Buffer.alloc(0), /empty/i],
    ...["exe", "zip", "png", "xlsx"].map((extension) => [
      `unsupported.${extension}`,
      Buffer.from("Synthetic unsupported bytes"),
      /Supported formats/,
    ]),
  ] as [string, Buffer, RegExp][]) {
    await input.setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer,
    });
    await expect(page.locator(".alert.error")).toContainText(expected);
    await page
      .getByRole("button", { name: "Dismiss error", exact: true })
      .click();
  }
  expect(await (await page.request.get("/api/documents")).json()).toHaveLength(
    1,
  );
});

test("UPL-11 exact 250-character Unicode filename keeps its extension and indexes", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const user = await account(page);
  const name = "اردو🧭" + "x".repeat(241) + ".txt";
  await page.locator('input[type="file"]').setInputFiles({
    name,
    mimeType: "text/plain",
    buffer: Buffer.from("Synthetic long-name document."),
  });
  // Python limits Unicode code points, whereas JS length includes surrogate pairs.
  const display = Array.from(name).slice(0, 216).join("") + ".txt";
  await expect(card(page, display)).toBeVisible();
  await ingest(page, user);
  await expect(
    card(page, display).getByText("ready", { exact: true }),
  ).toBeVisible();
});

test("UPL-12/13/14 duplicates deduplicate within scope and stay independent across project/user", async ({
  page,
}) => {
  const user = await account(page);
  const input = page.locator('input[type="file"]');
  await input.setInputFiles(path.join(files, "plain.txt"));
  await expect(card(page, "plain.txt")).toBeVisible();
  await input.setInputFiles(path.join(files, "plain.txt"));
  await expect(page.locator(".resource-card")).toHaveCount(1);
  const first = (await (await page.request.get("/api/documents")).json())[0];
  const project = await (
    await page.request.post("/api/projects", {
      headers: { origin: "http://127.0.0.1:3001" },
      data: { title: "Upload scope project" },
    })
  ).json();
  await page.reload();
  await page
    .getByLabel("Filter project", { exact: true })
    .selectOption(project.id);
  await input.setInputFiles(path.join(files, "plain.txt"));
  await expect(page.locator(".resource-card")).toHaveCount(1);
  const all = await (await page.request.get("/api/documents")).json();
  expect(all).toHaveLength(2);
  expect(
    all.map((doc: { project_id: string | null }) => doc.project_id),
  ).toContain(project.id);
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  const otherUser = await account(page);
  expect(otherUser).not.toBe(user);
  await input.setInputFiles(path.join(files, "plain.txt"));
  await expect(page.locator(".resource-card")).toHaveCount(1);
  expect(
    (await (await page.request.get("/api/documents")).json())[0].id,
  ).not.toBe(first.id);
  expect(
    (await page.request.get(`/api/documents/${first.id}/preview`)).status(),
  ).toBe(404);
});

test("UPL-15 storage quota error stays visible and does not add a ghost document", async ({
  page,
}) => {
  const user = await account(page);
  execFileSync(python, ["tests/e2e/upload_usage_fixture.py", user]);
  await page.reload();
  await page
    .locator('input[type="file"]')
    .setInputFiles(path.join(files, "plain.txt"));
  await expect(page.locator(".alert.error")).toContainText(
    "Storage quota exceeded",
  );
  expect(await (await page.request.get("/api/documents")).json()).toHaveLength(
    20,
  );
});

test("UPL-16 five files selected together keep distinct bytes and all become ready", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const user = await account(page);
  const names = Array.from({ length: 5 }, (_, index) => `batch-${index}.txt`);
  await page.locator('input[type="file"]').setInputFiles(
    names.map((name, index) => ({
      name,
      mimeType: "text/plain",
      buffer: Buffer.from(`Independent batch document ${index}.`),
    })),
  );
  await expect(page.locator(".resource-card")).toHaveCount(5);
  await ingest(page, user);
  for (const name of names)
    await expect(
      card(page, name).getByText("ready", { exact: true }),
    ).toBeVisible();
  const docs = await (await page.request.get("/api/documents")).json();
  expect(new Set(docs.map((doc: { sha256: string }) => doc.sha256)).size).toBe(
    5,
  );
});

for (const group of [
  [
    ["scanned.pdf", /OCR not supported/],
    ["encrypted.pdf", /Encrypted/],
    ["large_pages.pdf", /500 pages/],
    ["corrupt.pdf", /Malformed or corrupted PDF/],
    ["empty.docx", /no usable text/],
  ],
  [
    ["zipbomb.docx", /decompression limit/],
    ["binary.txt", /without binary/],
    ["latin1.txt", /codec/],
    ["huge_text.txt", /two million/],
    ["many_chunks.txt", /1200|1,200/],
  ],
] as [string, RegExp][][]) {
  test(`PRS parser failures show readable errors and retry; next valid document survives (${group[0][0]})`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const user = await account(page);
    const names = [...group.map(([name]) => name), "plain.txt"];
    await page
      .locator('input[type="file"]')
      .setInputFiles(names.map((name) => path.join(files, name)));
    await expect(page.locator(".resource-card")).toHaveCount(names.length);
    await ingest(page, user);
    for (const [name, reason] of group) {
      await expect(
        card(page, name).getByText("failed", { exact: true }),
      ).toBeVisible();
      await expect(card(page, name).getByRole("alert")).toContainText(reason);
      await expect(
        card(page, name).getByRole("button", {
          name: "Retry indexing",
          exact: true,
        }),
      ).toBeEnabled();
    }
    await expect(
      card(page, "plain.txt").getByText("ready", { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: `artifacts/prepublication/PRS-${group[0][0]}.png`,
      fullPage: true,
    });
  });
}
