import type { Page } from "@playwright/test";
import { test, expect } from "./isolation";
import { execFileSync, spawn } from "node:child_process";
import path from "node:path";

const password = "synthetic-publication-password";
async function registration(
  page: Page,
  email: string,
  name = "Publication Tester",
  pass = password,
) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page.getByLabel("Your name", { exact: true }).fill(name);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(pass);
}
async function submitRegistration(page: Page) {
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
}
async function workspace(page: Page) {
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
}
async function login(page: Page, email: string, pass = password) {
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(pass);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

test("AUTH-01 AUTH-02 AUTH-03 AUTH-06 AUTH-07 registration boundaries in browser", async ({
  page,
}) => {
  const email = `publication-boundary-${Date.now()}@example.com`;
  await registration(page, email, "Publication Boundary", "123456789");
  await submitRegistration(page);
  await expect(
    page.getByText("Use at least 10 characters.", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill("1234567890");
  for (const value of ["abc", "a@", "@b.com", "a b@c.com"]) {
    await page.getByLabel("Email", { exact: true }).fill(value);
    await submitRegistration(page);
    expect(
      await page
        .getByLabel("Email", { exact: true })
        .evaluate((input: HTMLInputElement) => input.validity.valid),
    ).toBe(false);
  }
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Your name", { exact: true }).fill("");
  await submitRegistration(page);
  expect(
    await page
      .getByLabel("Your name", { exact: true })
      .evaluate((input: HTMLInputElement) => input.validity.valueMissing),
  ).toBe(true);
  await page.getByLabel("Your name", { exact: true }).fill("   ");
  await submitRegistration(page);
  await expect(
    page.getByText("Enter your name.", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Boundary");
  await submitRegistration(page);
  await workspace(page);
});

test("AUTH-04 AUTH-05 duplicate and case-equivalent registration", async ({
  page,
}) => {
  const email = `publication-duplicate-${Date.now()}@example.com`;
  await registration(page, email);
  await submitRegistration(page);
  await workspace(page);
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  for (const value of [email, email.toUpperCase()]) {
    await page.getByLabel("Email", { exact: true }).fill(value);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await submitRegistration(page);
    await expect(page.locator(".auth-form .alert")).toContainText(
      "already exists",
    );
  }
});

test("AUTH-08 long display name has visible validation", async ({ page }) => {
  await registration(
    page,
    `publication-name-${Date.now()}@example.com`,
    "x".repeat(1000),
  );
  await submitRegistration(page);
  await expect(
    page.locator(".auth-form .error-text, .auth-form .alert"),
  ).toContainText(/120|too long|maximum/i);
});

test("AUTH-08 AUTH-09 Unicode names and extended passwords survive login", async ({
  page,
}) => {
  for (const [index, name, pass] of [
    [0, "احمد 🌿", "spaces inside a password"],
    [1, "Mira 🌿", "اردو پاس ورڈ 🌿"],
    [2, "Publication Long", "p".repeat(200)],
  ] as const) {
    const email = `publication-unicode-${Date.now()}-${index}@example.com`;
    await registration(page, email, name, pass);
    await submitRegistration(page);
    await workspace(page);
    await expect(
      page.getByRole("link", { name: new RegExp(name) }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Log out", exact: true }).click();
    await login(page, email, pass);
    await workspace(page);
    await page.getByRole("button", { name: "Log out", exact: true }).click();
  }
});

test("LOG-01 LOG-02 LOG-03 LOG-04 LOG-05 LOG-06 LOG-07 LOG-09 LOG-13 LOG-14", async ({
  page,
  context,
}) => {
  const email = `publication-login-${Date.now()}@example.com`;
  await registration(page, email);
  await submitRegistration(page);
  await workspace(page);
  const cookie = (await context.cookies()).find(
    (item) => item.name === "nexus_session",
  );
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Lax");
  expect(cookie?.path).toBe("/");
  expect(cookie!.expires).toBeGreaterThan(Date.now() / 1000);
  expect(
    await page.evaluate(() =>
      Object.keys(localStorage)
        .concat(Object.keys(sessionStorage))
        .filter((key) => /token|session|auth/i.test(key)),
    ),
  ).toEqual([]);
  await page.getByRole("link", { name: "Projects", exact: true }).click();
  await page.waitForURL("**/projects");
  await page.getByRole("button", { name: "Log out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back", exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("button", { name: "Log out", exact: true }),
  ).not.toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Welcome back", exact: true }),
  ).toBeVisible();
  await login(page, email, "wrong-password");
  await expect(page.locator(".auth-form .alert")).toHaveText(
    "Incorrect email or password.",
  );
  await login(page, "not-an-account@example.com", "wrong-password");
  await expect(page.locator(".auth-form .alert")).toHaveText(
    "Incorrect email or password.",
  );
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Welcome back", exact: true }),
  ).toBeVisible();
  await login(page, email);
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Welcome back", exact: true }),
  ).toBeVisible();
  await login(page, email);
  await workspace(page);
  await page.goto("/");
  await workspace(page);
});

test("LOG-10 independent browser sessions survive the other session logout", async ({
  page,
  browser,
}) => {
  const email = `publication-sessions-${Date.now()}@example.com`;
  await registration(page, email);
  await submitRegistration(page);
  await workspace(page);
  const second = await browser.newContext();
  try {
    const other = await second.newPage();
    await other.goto("http://127.0.0.1:3001");
    await login(other, email);
    await workspace(other);
    await page.getByRole("button", { name: "Log out", exact: true }).click();
    await other.reload();
    await workspace(other);
  } finally {
    await second.close();
  }
});

test("SES-01 expired session returns to sign-in and can sign in again", async ({
  page,
}) => {
  const email = `publication-expiry-${Date.now()}@example.com`;
  await registration(page, email);
  await submitRegistration(page);
  await workspace(page);
  execFileSync(
    path.resolve(
      ".venv",
      process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
    ),
    ["tests/e2e/session_fixture.py", email],
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Welcome back", exact: true }),
  ).toBeVisible();
  await login(page, email);
  await workspace(page);
});

test("RL-04 authentication rate limit has a friendly browser error", async ({
  page,
}) => {
  await page.goto("/");
  const email = `publication-limit-${Date.now()}@example.com`;
  for (let index = 0; index < 11; index++) {
    await login(page, email, "wrong-password");
    await expect(page.locator(".auth-form .alert")).toHaveText(
      index < 10
        ? "Incorrect email or password."
        : "Too many requests. Please wait and try again.",
    );
    await expect(
      page.getByRole("button", { name: "Sign in", exact: true }),
    ).toBeEnabled();
  }
});

test("SES-02 expiry during actual worker streaming is visible and saved work survives", async ({
  page,
}) => {
  test.setTimeout(100_000);
  const email = `publication-stream-expiry-${Date.now()}@example.com`;
  await registration(page, email);
  await submitRegistration(page);
  await workspace(page);
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
  let errors = "";
  worker.stderr.on("data", (chunk) => {
    errors += chunk.toString();
  });
  try {
    await page.goto(`/chat/${thread}`);
    await expect(page.getByText(/Audit stream paragraph 000/)).toBeVisible({
      timeout: 30_000,
    });
    execFileSync(python, ["tests/e2e/session_fixture.py", email]);
    await expect(
      page.locator(".alert").filter({ hasText: "Please sign in." }),
    ).toBeVisible({ timeout: 15_000 });
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "Welcome back", exact: true }),
    ).toBeVisible();
    await login(page, email);
    await expect(page.getByText(/Audit stream paragraph 000/)).toBeVisible();
    await expect(page.getByText(/Audit stream paragraph 149/)).toBeVisible({
      timeout: 60_000,
    });
    await expect
      .poll(
        async () =>
          (
            await (
              await page.request.get(`/api/conversations/${thread}/history`)
            ).json()
          ).runs.at(-1).status,
      )
      .toBe("completed");
    const history = await (
      await page.request.get(`/api/conversations/${thread}/history`)
    ).json();
    expect(history.runs.at(-1).status).toBe("completed");
    expect(
      history.messages.filter(
        (item: { role: string }) => item.role === "assistant",
      ),
    ).toHaveLength(1);
    expect(errors).not.toContain("Traceback");
  } finally {
    if (worker.exitCode === null) worker.kill();
  }
});
