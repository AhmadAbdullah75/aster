import { test, expect } from "./isolation";

test("draft navigation, immediate saved theme, and readable dark options", async ({
  page,
}) => {
  await page.goto("/");
  const authTheme = page.getByRole("button", {
    name: "Toggle dark mode",
    exact: true,
  });
  await authTheme.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page
    .getByRole("button", { name: "Create an account", exact: true })
    .click();
  await authTheme.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByLabel("Your name", { exact: true }).fill("UI Review");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`ui-review-${Date.now()}@example.com`);
  await page
    .getByLabel("Password", { exact: true })
    .fill("synthetic-ui-password");
  await page
    .getByRole("button", { name: "Create account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: /What’s on your mind/ }),
  ).toBeVisible();
  for (const path of ["/chat", "/"]) {
    await page.goto(path);
    await page.reload();
    const heading = page.getByRole("heading", { name: /What’s on your mind/ });
    await expect(heading).toBeInViewport();
    await expect(page.locator(".chat-scroll")).toHaveJSProperty("scrollTop", 0);
    await expect(
      page.getByRole("button", { name: "Latest", exact: true }),
    ).toHaveCount(0);
  }
  expect(
    (await page.locator(".sidebar").boundingBox())!.width,
  ).toBeGreaterThanOrEqual(300);
  expect(
    await page
      .locator(".sidebar")
      .evaluate((el) => getComputedStyle(el).scrollbarWidth),
  ).toBe("thin");
  const newButton = await page
    .getByRole("button", { name: "New conversation", exact: true })
    .boundingBox();
  const scope = await page.locator(".new-chat-scope").boundingBox();
  expect(scope!.y - (newButton!.y + newButton!.height)).toBeGreaterThanOrEqual(
    10,
  );
  for (let i = 0; i < 3; i++)
    await page
      .getByRole("button", { name: "New conversation", exact: true })
      .click();
  expect(
    await (await page.request.get("/api/conversations")).json(),
  ).toHaveLength(0);
  await page.locator('a[href="/settings"]').click();
  for (const theme of ["dark", "light"]) {
    await page.getByLabel("Appearance", exactOption()).selectOption(theme);
    await expect
      .poll(
        async () => (await (await page.request.get("/api/me")).json()).theme,
      )
      .toBe(theme);
    await page.getByRole("link", { name: "Notes", exact: true }).click();
    await page.locator('a[href="/settings"]').click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  }
  await page.emulateMedia({ colorScheme: "dark" });
  await page.getByLabel("Appearance", exactOption()).selectOption("system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const optionColors = await page
    .getByLabel("Appearance")
    .locator("option")
    .first()
    .evaluate((el) => ({
      color: getComputedStyle(el).color,
      background: getComputedStyle(el).backgroundColor,
    }));
  expect(optionColors.color).not.toBe(optionColors.background);
  expect(optionColors.background).not.toBe("rgba(0, 0, 0, 0)");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const project = await (
    await page.request.post("/api/projects", {
      headers: { origin: "http://127.0.0.1:3001" },
      data: { title: "Navigation QA" },
    })
  ).json();
  await page.goto("/chat");
  await page.getByLabel("New conversation workspace").selectOption(project.id);
  await expect(page.getByLabel("Chat project")).toHaveValue(project.id);
  await page.getByLabel("New conversation workspace").selectOption("");
  await expect(page.getByLabel("Chat project")).toHaveValue("");
  expect(
    await (await page.request.get("/api/conversations")).json(),
  ).toHaveLength(0);
  await page.route("**/api/memories*", (route) =>
    route.fulfill({
      json: [
        {
          id: "memory-preview",
          title: "Explanation preference",
          content: "Use short bullet points.",
          enabled: true,
          category: "preference",
          provenance: "Conversation 7e1a4acd-c408-4970-81a4-5fff35c5502b",
          version: 1,
        },
      ],
    }),
  );
  await page.goto("/memories");
  await expect(page.getByText(/Saved from a conversation/)).toBeVisible();
  await expect(page.getByText(/7e1a4acd/)).toHaveCount(0);
  let memoryReviewStatus = "pending";
  await page.route("**/api/conversations/ui-preview/history", (route) =>
    route.fulfill({
      json: {
        messages: [
          {
            id: "user",
            role: "user",
            content: "Help me prepare my portfolio.",
            sources: [],
            created_at: "2026-11-02T17:50:18Z",
          },
          {
            id: "assistant",
            role: "assistant",
            content:
              'Start with a concise README, screenshots, and clear setup instructions.\n\nPractice: $S = \\frac{120}{20} = 6$.\n\n$$\nE = \\frac{6}{8} = 0.75\n$$\n\n```cpp\n#include <iostream>\n// Print the root of the binary tree\nint main() {\n  int tree[] = {1, 2, 3};\n  std::cout << "Root: " << tree[0];\n  return 0;\n}\n```\n\n[source:11111111-1111-1111-1111-111111111111]',
            sources: [
              {
                id: "11111111-1111-1111-1111-111111111111",
                filename: "Lecture.pdf",
                page: 7,
              },
            ],
            created_at: "2026-11-02T17:50:23Z",
          },
        ],
        runs: [],
        proposals: [
          {
            id: "memory-review",
            run_id: "preview",
            version: 1,
            action: "memories.create",
            status: memoryReviewStatus,
            expires_at: "2099-01-01T00:00:00Z",
            payload: {
              items: [
                {
                  include: true,
                  title: "Response format",
                  content: "Use short bullets.",
                },
              ],
            },
          },
        ].flatMap((proposal) =>
          ["memories.create", "tasks.create", "notes.create"].map((action) => ({
            ...proposal,
            id: action + "-review",
            action,
          })),
        ),
      },
    }),
  );
  await page.goto("/chat/ui-preview");
  await page.route(
    "**/api/sources/11111111-1111-1111-1111-111111111111",
    (route) =>
      route.fulfill({
        json: {
          filename: "Lecture.pdf",
          page: 7,
          excerpt: "Speedup equals serial time divided by parallel time.",
        },
      }),
  );
  await expect(page.locator(".message")).toHaveCount(2);
  await page.getByRole("button", { name: "Source ↗", exact: true }).click();
  await expect(
    page.getByText("Speedup equals serial time divided by parallel time.", {
      exact: true,
    }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".message.assistant .katex-display")).toHaveCount(
    1,
  );
  await expect(page.locator(".approval-card")).toHaveCount(3);
  for (const status of ["approved", "completed", "rejected"]) {
    memoryReviewStatus = status;
    await page.reload();
    await expect(page.locator(".message")).toHaveCount(2);
    await expect(page.locator(".approval-card")).toHaveCount(0);
  }
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const theme of ["dark", "light"]) {
      await page.emulateMedia({ colorScheme: theme as "dark" | "light" });
      if (theme === "dark") {
        const minimumContrast = await page
          .locator(".code-wrap pre")
          .evaluate((pre) => {
            const luminance = (color: string) => {
              const channels = color
                .match(/[\d.]+/g)!
                .slice(0, 3)
                .map(Number)
                .map((n) => n / 255)
                .map((n) =>
                  n <= 0.04045 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4),
                );
              return (
                channels[0] * 0.2126 +
                channels[1] * 0.7152 +
                channels[2] * 0.0722
              );
            };
            const background = luminance(getComputedStyle(pre).backgroundColor);
            return Math.min(
              ...Array.from(pre.querySelectorAll("code, span"))
                .filter((el) => el.textContent?.trim())
                .map((el) => {
                  const foreground = luminance(getComputedStyle(el).color);
                  return (
                    (Math.max(foreground, background) + 0.05) /
                    (Math.min(foreground, background) + 0.05)
                  );
                }),
            );
          });
        expect(minimumContrast).toBeGreaterThanOrEqual(4.5);
      }
      if (theme === "light") {
        await expect(page.locator("html")).toHaveAttribute(
          "data-theme",
          "light",
        );
        expect(
          await page
            .locator(".message.user .markdown")
            .evaluate((el) => getComputedStyle(el).backgroundColor),
        ).toBe("rgb(35, 107, 89)");
      }
      const human = await page.locator(".message.user").boundingBox();
      const assistant = await page.locator(".message.assistant").boundingBox();
      const bubble = await page
        .locator(".message.user .markdown")
        .boundingBox();
      const metadata = await page
        .locator(".message.user .message-heading")
        .boundingBox();
      expect(metadata!.y).toBeGreaterThanOrEqual(bubble!.y + bubble!.height);
      expect(human!.x).toBeGreaterThan(assistant!.x);
      await expect(page.locator(".message.user time")).toHaveText(
        /^\d{1,2}:\d{2} [AP]M$/,
      );
      await page.screenshot({
        path: `artifacts/prepublication/ui-refinement-${width}-${theme}.png`,
      });
    }
  }
});
function exactOption() {
  return { exact: true };
}
