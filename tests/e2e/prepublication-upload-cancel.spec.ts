import { test, expect } from "./isolation";
import { connect } from "node:net";
import { execFileSync } from "node:child_process";
import { readdir, writeFile } from "node:fs/promises";
import path from "node:path";

test("UPL-17 interrupted multipart and closing uploading tab leave no half-created ghost", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication upload cancellation");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-upload-cancel-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-upload-cancel-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Documents", exact: true }).click();
  await page.waitForURL("**/documents");
  await expect(
    page.getByRole("heading", {
      name: "A fresh space for your documents",
      exact: true,
    }),
  ).toBeVisible();
  const blobs = path.resolve(".data/e2e/blobs");
  const before = new Set(await readdir(blobs).catch(() => []));
  const cookies = (await context.cookies()).filter(
    (cookie) => cookie.name === "nexus_session",
  );
  expect(cookies).toHaveLength(1);
  const user = await (await page.request.get("/api/me")).json();
  const cookie = `${cookies[0].name}=${cookies[0].value}`;
  const partial =
    '--nexus-partial\r\nContent-Disposition: form-data; name="file"; filename="interrupted.txt"\r\nContent-Type: text/plain\r\n\r\n' +
    "x".repeat(1024);
  for (const port of [8001, 3001]) {
    const socket = connect(port, "127.0.0.1");
    await new Promise<void>((resolve, reject) => {
      socket.once("connect", resolve);
      socket.once("error", reject);
    });
    const closed = new Promise<void>((resolve) => {
      socket.once("close", () => resolve());
    });
    socket.on("error", () => {});
    socket.setTimeout(5000, () => socket.destroy());
    socket.write(
      `POST ${port === 3001 ? "/api/documents" : "/documents"} HTTP/1.1\r\nHost: 127.0.0.1:${port}\r\nOrigin: http://127.0.0.1:3001\r\nCookie: ${cookie}\r\nContent-Type: multipart/form-data; boundary=nexus-partial\r\nContent-Length: 1048576\r\nConnection: close\r\n\r\n${partial}`,
    );
    socket.end();
    await closed;
    const afterPartial = await page.request.get("/api/documents");
    expect(afterPartial.status()).toBe(200);
    expect(await afterPartial.json()).toEqual([]);
  }

  // Throttle the real transport. Disposing an intercepted route while closing
  // its page can forward the held request, which is not an interrupted upload.
  const network = await context.newCDPSession(page);
  await network.send("Network.enable");
  await network.send("Network.emulateNetworkConditionsByRule", {
    matchedNetworkConditions: [
      {
        urlPattern: "",
        latency: 100,
        downloadThroughput: -1,
        uploadThroughput: 16 * 1024,
      },
    ],
  });
  let acceptedBeforeClose = false;
  page.on("response", (response) => {
    if (
      response.url().endsWith("/api/documents") &&
      response.request().method() === "POST" &&
      response.status() === 202
    )
      acceptedBeforeClose = true;
  });
  const requestStarted = page.waitForRequest(
    (request) =>
      request.url().endsWith("/api/documents") && request.method() === "POST",
  );
  const uploadStarted = performance.now();
  let secondsBeforeClose = 0;
  try {
    await page.locator('input[type="file"]').setInputFiles({
      name: "closed-tab.txt",
      mimeType: "text/plain",
      buffer: Buffer.alloc(1024 * 1024, 65),
    });
    await requestStarted;
    await expect(
      page.getByText("Uploading your documents…", { exact: true }),
    ).toBeVisible();
    secondsBeforeClose = (performance.now() - uploadStarted) / 1000;
    expect(secondsBeforeClose).toBeLessThan(10);
    expect(acceptedBeforeClose).toBe(false);
  } finally {
    await page.close();
  }
  const reopened = await context.newPage();
  await reopened.goto("/documents");
  await expect(
    reopened.getByRole("heading", { name: "Documents", exact: true }),
  ).toBeVisible();
  const current = await reopened.request.get("/api/documents");
  expect(current.status()).toBe(200);
  const documents = await current.json();
  // The plan requires no HALF-created ghost. A complete atomic commit may
  // legitimately beat a tab close even when its response is never received.
  const integrity = JSON.parse(
    execFileSync(
      path.resolve(
        ".venv",
        process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
      ),
      ["tests/e2e/upload_atomicity_fixture.py", user.id],
      { encoding: "utf8", timeout: 30_000 },
    ),
  );
  expect(documents).toHaveLength(integrity.documents);
  expect(integrity.half_created_records).toBe(0);
  if (documents.length) {
    expect(integrity.complete_bytes_verified).toBe(true);
    await expect(
      reopened.getByRole("heading", { name: "closed-tab.txt", exact: true }),
    ).toBeVisible();
  } else {
    await expect(
      reopened.getByRole("heading", {
        name: "A fresh space for your documents",
        exact: true,
      }),
    ).toBeVisible();
  }
  const addedBlobs = (await readdir(blobs).catch(() => [])).filter(
    (name) => !before.has(name),
  );
  expect(addedBlobs.sort()).toEqual(integrity.complete_blobs.sort());
  await writeFile(
    "artifacts/prepublication/UPL-17.json",
    JSON.stringify(
      {
        partialMultipartBytesSent: partial.length,
        declaredBodyBytes: 1048576,
        interruptedMultipartPorts: [8001, 3001],
        documentsAfterPartial: 0,
        documentsAfterTabClose: documents.length,
        newBlobs: addedBlobs.length,
        uploadBytesPerSecond: 16 * 1024,
        secondsBeforeClose,
        acceptedBeforeClose,
        transportThrottled: true,
        integrity,
      },
      null,
      2,
    ),
  );
  await reopened.screenshot({
    path: "artifacts/prepublication/UPL-17.png",
    fullPage: true,
  });
  await reopened.close();
});
