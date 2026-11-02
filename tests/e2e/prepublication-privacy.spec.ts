import { test, expect } from "./isolation";

test("DEP-18 privacy notice identifies assistant document and search destinations", async ({
  page,
}) => {
  const registered = await page.request.post("/api/auth/register", {
    headers: { Origin: "http://127.0.0.1:3001" },
    data: {
      name: "Publication Privacy",
      email: `publication-privacy-${Date.now()}@example.com`,
      password: "synthetic-privacy-password",
    },
  });
  expect(registered.status()).toBe(200);
  await page.goto("/settings");
  const privacy = page
    .locator("section")
    .filter({
      has: page.getByRole("heading", { name: "Your data", exact: true }),
    });
  await expect(privacy).toContainText("Gemini");
  await expect(privacy).toContainText("Extracted document text");
  await expect(privacy).toContainText("relevant saved memories");
  await expect(privacy).toContainText("DuckDuckGo");
  await expect(privacy).toContainText("stored on your Aster server");
  await page.screenshot({
    path: "artifacts/prepublication/DEP-18-privacy.png",
  });
});
