import { test } from "./isolation";
import { execFileSync } from "node:child_process";

test.skip(process.env.NEXUS_RELEASE_BROWSER !== "true", "Separate official release browser installation required.");

test("BRW-03 official current Firefox registration persistence PDF approval logout", async () => {
  test.setTimeout(300_000);
  execFileSync("python", ["-m", "uv", "run", "--with", "selenium", "python", "tests/e2e/firefox_release_fixture.py"], {
    encoding: "utf8", timeout: 280_000, stdio: "inherit",
  });
});
