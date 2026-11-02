import { test, expect } from "./isolation";
async function account(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await page
    .getByLabel("Your name", { exact: true })
    .fill("Publication Settings");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`publication-settings-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-settings-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  await page.goto("/settings");
}
test("SET-01/03/04/05/06/08 profile, invalid timezone, system appearance and stale settings", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.emulateMedia({ colorScheme: "light" });
  await account(page);
  const other = await page.context().newPage();
  await other.goto("/settings");
  await expect(other.getByLabel("Name", { exact: true })).toHaveValue(
    "Publication Settings",
  );
  await page.getByLabel("Name", { exact: true }).fill("Updated profile");
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(
    page.getByText("Preferences saved", { exact: true }),
  ).toBeVisible();
  await other.getByLabel("Name", { exact: true }).fill("Stale profile");
  await other
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(other.locator(".alert.error")).toContainText(/changed|version/i);
  expect((await (await page.request.get("/api/me")).json()).name).toBe(
    "Updated profile",
  );
  await page.getByLabel("Timezone", { exact: true }).fill("Mars/Base");
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(page.locator(".alert.error")).toContainText("IANA timezone");
  await page
    .getByRole("button", { name: "Dismiss error", exact: true })
    .click();
  await page.getByLabel("Timezone", { exact: true }).fill("Asia/Karachi");
  for (const theme of ["dark", "light", "system"]) {
    await page
      .getByRole("combobox", { name: "Appearance", exact: true })
      .selectOption(theme);
    await page
      .getByRole("button", { name: "Save preferences", exact: true })
      .click();
    await expect(page.locator("html")).toHaveAttribute(
      "data-theme",
      theme === "system" ? "light" : theme,
    );
    await page.reload();
    await expect(
      page.getByRole("combobox", { name: "Appearance", exact: true }),
    ).toHaveValue(theme);
  }
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("button", { name: "Save preferences", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Toggle dark mode", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(
    page.getByRole("combobox", { name: "Appearance", exact: true }),
  ).toHaveValue("light");
  await page.goto("/chat");
  await expect(
    page.getByRole("heading", { name: /What’s on your mind, Updated/ }),
  ).toBeVisible();
});
test("SET-09 saved dark appearance applies while profile fetch is deliberately held", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await account(page);
  await page
    .getByRole("combobox", { name: "Appearance", exact: true })
    .selectOption("dark");
  await page
    .getByRole("button", { name: "Save preferences", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/me", async (route) => {
    await gate;
    await route.continue();
  });
  try {
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(
      page.getByText("Opening your workspace…", { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: "artifacts/prepublication/SET-09-dark-first-load.png",
    });
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
});
test("SET-10 unsupported account security actions are not advertised", async ({
  page,
}) => {
  await account(page);
  await expect(
    page.getByRole("heading", {
      name: "Connections & capabilities",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: /change password|enable mfa|delete account/i,
    }),
  ).toHaveCount(0);
});
