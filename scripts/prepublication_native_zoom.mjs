// An isolated visible Chrome window for native browser-zoom inputs via Computer Use.
// This fixture only authenticates a known synthetic account and records DOM geometry.
import { chromium } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const folder = path.join(root, "artifacts/prepublication");
const statePath = path.join(folder, "native-zoom-state.json");
const commandPath = path.join(folder, "native-zoom-command.json");
const ledgerPath = path.join(folder, "results.json");
const base = process.env.NEXUS_ZOOM_BASE || "http://127.0.0.1:3000";
if (!["http://127.0.0.1:3000", "http://127.0.0.1:3003"].includes(base))
  throw new Error("Only the native app or isolated layout server is allowed");
async function stopped() {
  const state = JSON.parse(await readFile(ledgerPath, "utf8"));
  return Boolean(state.halt || state.external_blocker);
}
if (await stopped()) throw new Error("Testing is stopped");
const browser = await chromium.launch({
  channel: "chrome",
  headless: false,
  args: ["--window-size=1440,1000"],
});
try {
  const context = await browser.newContext({ viewport: null });
  const login = await context.request.post(
    "http://127.0.0.1:3000/api/auth/login",
    {
      headers: { Origin: "http://127.0.0.1:3000" },
      data: {
        email: "nexus-smoke-publication-20261024a@example.com",
        password: "synthetic-publication-password",
      },
    },
  );
  if (
    login.status() !== 200 ||
    (await login.json()).id !== "15c1d056-30cd-4772-be15-713e487df802"
  )
    throw new Error("Synthetic account unavailable");
  const page = await context.newPage();
  await page.goto(`${base}/chat/b1a130be-c1b9-4ef2-aa58-d1df47bfe6ce`);
  await page.getByLabel("Message Aster", { exact: true }).waitFor();
  const report = {
    started: new Date().toISOString(),
    isolatedProfile: true,
    base,
    captures: [],
  };
  async function capture(stage) {
    if (!/^[a-z0-9-]+$/i.test(stage)) throw new Error("Invalid capture stage");
    const geometry = await page.evaluate(() => ({
      width: innerWidth,
      height: innerHeight,
      pixelRatio: devicePixelRatio,
      documentWidth: document.documentElement.scrollWidth,
      pathname: location.pathname,
      panels: Object.fromEntries(
        [".chat-workspace", ".chat-scroll", ".composer-area"].map(
          (selector) => {
            const element = document.querySelector(selector);
            const rect = element?.getBoundingClientRect();
            return [
              selector,
              rect
                ? {
                    top: rect.top,
                    bottom: rect.bottom,
                    height: rect.height,
                    scrollHeight: element.scrollHeight,
                    clientHeight: element.clientHeight,
                  }
                : null,
            ];
          },
        ),
      ),
      headings: [...document.querySelectorAll("h1,h2")].map(
        (element) => element.textContent,
      ),
    }));
    await page.screenshot({
      path: path.join(folder, `native-zoom-${stage}.png`),
    });
    report.captures.push({ stage, ...geometry });
    await writeFile(statePath, JSON.stringify(report, null, 2));
  }
  await capture("baseline");
  console.log(
    "Isolated Chrome ready; native zoom keys must come from Computer Use.",
  );
  let last = "";
  const deadline = Date.now() + 15 * 60_000;
  while (Date.now() < deadline && !(await stopped())) {
    const raw = await readFile(commandPath, "utf8").catch(() => "");
    if (raw && raw !== last) {
      last = raw;
      const command = JSON.parse(raw);
      if (command.action === "close") break;
      if (command.action === "capture") await capture(command.stage);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
} finally {
  await browser.close();
}
