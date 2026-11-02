// Capture the real production UI with a disposable local account; no model calls.
import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import path from "node:path";

const browser = await chromium.launch();
const page = await browser.newPage({viewport:{width:1440,height:1000}});
const email = "nexus-smoke-ui-" + Date.now() + "@example.com";
let user;
try {
  const response = await page.request.post("http://127.0.0.1:3000/api/auth/register", {
    headers:{origin:"http://127.0.0.1:3000"},
    data:{email,password:"synthetic-ui-capture-password",name:"Alex"},
  });
  if (!response.ok()) throw new Error("Synthetic capture registration failed: " + response.status());
  user=await response.json();
  await page.goto("http://127.0.0.1:3000/chat");
  await page.getByRole("heading",{name:"What’s on your mind, Alex?",exact:true}).waitFor();
  await page.getByText("AI configured",{exact:true}).waitFor();
  await page.screenshot({path:"artifacts/audit-production-workspace.png",fullPage:true,animations:"disabled"});
  console.log("Production UI captured after transitions; no model requests made.");
} finally {
  await browser.close();
  if (user) execFileSync(path.resolve(".venv",process.platform === "win32"?"Scripts/python.exe":"bin/python"),["scripts/cleanup_smoke.py",user.id,email]);
}
