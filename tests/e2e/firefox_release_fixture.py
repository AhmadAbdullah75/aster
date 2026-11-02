"""Current official Firefox UI flow using WebDriver, on isolated nexus_e2e only."""

import json
import subprocess
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv/Scripts/python.exe"
OUT = ROOT / "artifacts/prepublication/BRW-firefox-release-159"
assert not OUT.with_suffix(".json").exists(), "Preserve prior evidence"
ledger = json.loads((ROOT / "artifacts/prepublication/results.json").read_text())
assert not (ledger.get("halt") or ledger.get("external_blocker"))
options = webdriver.FirefoxOptions()
options.binary_location = str(ROOT / ".data/test-browsers/firefox-159/core/firefox.exe")
options.add_argument("-headless")
driver = webdriver.Firefox(options=options)
driver.set_window_size(1280, 900)
driver.set_script_timeout(30)
wait = WebDriverWait(driver, 40)


def element(xpath):
    return wait.until(EC.visibility_of_element_located((By.XPATH, xpath)))


def button(name):
    element(f"//button[normalize-space(.)='{name}' or @aria-label='{name}']").click()


def field(label, value):
    target = element(
        f"//label[normalize-space(.)='{label}']//input | "
        f"//label[normalize-space(.)='{label}']//textarea"
    )
    target.clear()
    target.send_keys(value)


def heading(name):
    return element(f"//*[self::h1 or self::h2 or self::h3][normalize-space(.)='{name}']")


def api(path):
    result = driver.execute_async_script(
        "const done=arguments[arguments.length-1]; fetch(arguments[0]).then(async r=>"
        "done({status:r.status,data:await r.json()})).catch(()=>done({status:0}));",
        path,
    )
    assert result["status"] == 200
    return result["data"]


def fixture(*args):
    return subprocess.check_output([str(PYTHON), *args], cwd=ROOT, text=True, timeout=60).strip()


try:
    assert driver.capabilities["browserVersion"] == "159.0"
    driver.get("http://127.0.0.1:3001/")
    button("Create an account")
    email = f"publication-firefox-release-{time.time_ns()}@example.com"
    password = "synthetic-browser-password"
    field("Your name", "Publication Browser")
    field("Email", email)
    field("Password", password)
    button("Create account")
    element("//h1[contains(., 'What’s on your mind')]")
    user = api("/api/me")["id"]
    element("//a[normalize-space(.)='Notes']").click()
    button("New note")
    title = "Browser persistence اردو"
    field("Title", title)
    field("Note · Markdown supported", "# Recovery evidence\n\nSaved **Markdown**.")
    button("Save note")
    heading(title)
    driver.refresh()
    heading(title)
    element("//a[normalize-space(.)='Documents']").click()
    heading("Documents")
    pdf = ROOT / ".data/prepublication-files/proposal.pdf"
    driver.find_element(By.CSS_SELECTOR, 'input[type="file"]').send_keys(str(pdf))
    wait.until(lambda _: len(api("/api/documents")) == 1)
    doc = api("/api/documents")[0]
    fixture("tests/e2e/ingest_fixture.py", doc["id"])
    driver.refresh()
    element("//button[contains(.,'Preview PDF')]").click()
    element("//span[normalize-space(.)='Page 1 of 5']")
    canvas = element("//canvas[@aria-label='PDF page 1']")
    ink = wait.until(
        lambda _: driver.execute_script(
            "let d=arguments[0].getContext('2d').getImageData(0,0,arguments[0].width,arguments[0].height).data;"
            "let n=0;for(let i=0;i<d.length;i+=4)if(d[i]<100&&d[i+1]<100&&d[i+2]<100)n++;return n>20?n:0;",
            canvas,
        )
    )
    button("Close dialog")
    thread = fixture("tests/e2e/graph_fixture.py", "seed", user).splitlines()[-1]
    driver.get(f"http://127.0.0.1:3001/chat/{thread}")
    button("Approve selection")
    fixture("tests/e2e/graph_fixture.py", "resume", thread)
    assert len(api("/api/tasks")) == 2
    button("Log out")
    heading("Welcome back")
    field("Email", email)
    field("Password", password)
    button("Sign in")
    element("//a[normalize-space(.)='Notes']").click()
    heading(title)
    driver.save_screenshot(str(OUT.with_suffix(".png")))
    OUT.with_suffix(".json").write_text(
        json.dumps(
            {
                "browser": "Official Firefox release",
                "version": driver.capabilities["browserVersion"],
                "registration": True,
                "persistedAfterLogin": True,
                "pdfCanvasInk": ink,
                "approvedTasks": 2,
                "logoutAndLogin": True,
            },
            indent=2,
        )
        + "\n"
    )
    print("Official Firefox159 UI flow passed.")
except Exception:
    driver.save_screenshot(str(OUT.with_suffix(".failure.png")))
    raise
finally:
    driver.quit()

