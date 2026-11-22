import { fillTestPassword, requestLocalApi } from "./browser-requests.mjs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import axe from "axe-core";
import { checkViewerAccess } from "./workspace-permissions.mjs";
import assert from "node:assert/strict";
import { stdin } from "node:process";
import { chromium } from "playwright-core";

let input = "";
for await (const chunk of stdin) input += chunk;
const { email, password, viewer } = JSON.parse(input);
const origin = "http://127.0.0.1:8080";
const browser = await chromium.launch({
  executablePath: process.env.CHROME_BIN,
  args: ["--no-proxy-server"],
});
try {
  const page = await browser.newPage();
  // Only the disposable local stack may receive this test account's credentials.
  await page.route("**/*", (route) => new URL(route.request().url()).origin === origin
    ? route.continue() : route.abort());
  await page.goto(origin);
  await page.getByRole("link", { name: "Open your project workspace" }).click();
  await page.getByLabel("Email").fill(email);
  await fillTestPassword(page, password);
  await page.getByRole("button", { name: "Sign in" }).click();
  const selector = page.getByRole("combobox", { name: "Project", exact: true });
  await selector.selectOption({ label: "Synthetic login demo" });
  await page.getByRole("button", { name: "Overview for Synthetic login demo" }).waitFor();
  const project = await selector.inputValue();
  async function checkAccessibility(view) {
    await page.evaluate(axe.source);
    const issues = await page.evaluate(async () => {
      const result = await window.axe.run(document, { runOnly: {type:"tag", values:["wcag2a","wcag2aa","wcag21a","wcag21aa"]} });
      return result.violations.filter(v => v.impact === "serious" || v.impact === "critical")
        .map(v => ({id:v.id, targets:v.nodes.map(n=>n.target)}));
    });
    assert.deepEqual(issues, [], view + " accessibility findings: " + JSON.stringify(issues));
  }
  await page.getByRole("button", {name:"Refresh overview"}).waitFor();
  await checkAccessibility("Overview");
  await page.getByRole("button", { name: "Inventory for Synthetic login demo" }).click();
  await page.getByLabel(/OpenAPI file/).setInputFiles(fileURLToPath(new URL("../../../examples/login-demo.yaml", import.meta.url)));
  await page.getByRole("button", { name: "Import file" }).click();
  await page.getByText("/api/login", { exact: true }).waitFor();
  await page.getByText("demoSession", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Integrations for Synthetic login demo" }).click();
  await page.getByLabel("Emitter name").fill("Browser emitter");
  await page.getByRole("button", { name: "Create key" }).click();
  await page.getByLabel("New ingestion key").waitFor();
  const ingestionKey = await page.getByLabel("New ingestion key").inputValue();
  const demoSource = "synthetic-login-demo";
  const emitter = fileURLToPath(new URL("../../../scripts/emit_event.py", import.meta.url));
  const runDemo = () => execFileSync(process.env.SMOKE_PYTHON, [emitter, "--demo"], {
    encoding: "utf8",
    env: { ...process.env, SENTINEL_INGESTION_KEY: ingestionKey },
  }).trim().split(/\r?\n/);
  const replay = "Synthetic events: 0 accepted, 9 duplicate, 0 rejected.";
  assert.deepEqual(runDemo(), ["Synthetic events: 9 accepted, 0 duplicate, 0 rejected.", replay]);
  assert.deepEqual(runDemo(), [replay, replay]);
  await page.getByRole("button", { name: "Hide key" }).click();
  await page.getByRole("button", { name: "Events for Synthetic login demo" }).click();
  await page.getByLabel("Event source").fill(demoSource);
  await page.getByRole("button", { name: "Apply event filters" }).click();
  const events = page.getByRole("region", { name: "Security events", exact: true });
  const normal = events.getByRole("row").filter({ hasText: "/api/users/{id}" });
  await normal.getByRole("button", { name: /^View event / }).click();
  assert.equal(await events.getByText("/api/login", { exact: true }).count(), 8);
  await page.getByText("demo-normal", { exact: true }).waitFor();
  assert.equal(await page.getByText("synthetic-demo-user", { exact: true }).count(), 0);
  await page.getByText("Actor pseudonym", { exact: true }).waitFor();
  // The worker runs independently of ingestion. Await each API response before
  // opening the list so the rendered page includes this source's new alert.
  const deadline = Date.now() + 45000;
  let alertId;
  while (!alertId && Date.now() < deadline) {
    const response = await requestLocalApi(page.request, "GET", origin + "/api/v1/projects/" + project + "/alerts");
    assert.equal(response.status(), 200);
    const alerts = (await response.json()).entries.filter(row => row.source_id === demoSource);
    assert.ok(alerts.length <= 1);
    alertId = alerts[0]?.id;
    if (!alertId) await new Promise(resolve => setTimeout(resolve, 400));
  }
  assert.ok(alertId, "The worker must produce the browser source's alert");
  await page.getByRole("button", { name: "Alerts for Synthetic login demo" }).click();
  await page.getByRole("button", { name: "Inspect alert " + alertId, exact: true }).click();
  const evidence = page.getByRole("article",{name:"Alert evidence"});
  const linkedEvents = evidence.getByRole("button", {name:/^[a-f0-9-]{36}$/});
  await evidence.getByText(/Rule version 1/).waitFor();
  await evidence.getByText(/at least 8 observations in 300 seconds/).waitFor();
  await linkedEvents.first().waitFor();
  assert.equal(await linkedEvents.count(), 8);
  const eventId = (await linkedEvents.first().textContent()).trim();
  await linkedEvents.first().click();
  await evidence.getByText(/HTTP 401/).waitFor();
  await checkAccessibility("Alert evidence");
  await evidence.getByRole("button",{name:"Create incident from alert"}).click();
  await page.getByLabel("Incident title").fill("Browser login investigation");
  await page.getByRole("button",{name:"Create incident",exact:true}).click();
  await page.getByRole("heading",{name:"Browser login investigation"}).waitFor();
  const incidentId = (await page.locator("article.investigation > p > code").textContent()).trim();
  await page.getByRole("button",{name:"Assign to me"}).click();
  await page.getByText("Assigned to you",{exact:true}).waitFor();
  await page.getByRole("button",{name:"Move to acknowledged"}).click();
  await page.getByRole("button",{name:"Move to investigating"}).waitFor();
  await page.getByLabel("Investigation note").fill("Verified the synthetic browser observations.");
  await page.getByRole("button",{name:"Add note"}).click();
  await page.getByText("Verified the synthetic browser observations.",{exact:true}).waitFor();
  await page.getByRole("button",{name:"Move to investigating"}).click();
  await page.getByRole("button",{name:"Move to resolved"}).click();
  await page.getByRole("button",{name:"Move to reopened"}).click();
  await page.getByText("reopened", {exact:true}).first().waitFor();
  await page.getByRole("button",{name:"Move to investigating"}).waitFor();
  await page.setViewportSize({width:390,height:844});
  const mobileLayout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    pageWidth: document.documentElement.scrollWidth,
    overflowingElements: Array.from(document.querySelectorAll("main *"))
      .filter(element => element.getBoundingClientRect().right > window.innerWidth)
      .map(element => element.tagName.toLowerCase()).slice(0, 12),
  }));
  assert.ok(mobileLayout.pageWidth <= mobileLayout.viewport, JSON.stringify(mobileLayout));
  await checkAccessibility("Mobile incident detail");
  await page.setViewportSize({width:1280,height:800});
  console.log("Browser verified alert evidence, incident promotion, assignment, note, resolution and reopening. Three accessibility scans passed.");
  await page.getByRole("button", { name: "Integrations for Synthetic login demo" }).click();
  await page.getByRole("button", { name: "Rotate", exact: true }).click();
  await page.getByRole("button", { name: "Confirm rotate" }).click();
  await page.getByLabel("New ingestion key").waitFor();
  await page.reload();
  await selector.selectOption({ label: "Synthetic login demo" });
  await page.getByRole("button", { name: "Integrations for Synthetic login demo" }).click();
  await page.getByRole("button", { name: "Revoke", exact: true }).click();
  assert.equal(await page.getByLabel("New ingestion key").count(), 0);
  await page.getByRole("button", { name: "Confirm revoke" }).click();
  const browserKeys = page.getByRole("region", { name: "Project integrations" }).getByRole("listitem").filter({hasText: "Browser emitter"});
  await browserKeys.getByText(/^Revoked ·/).nth(1).waitFor();
  await page.getByRole("button", { name: "Rotate", exact: true }).waitFor({state:"detached"});
  await page.getByRole("button", { name: "View audit activity" }).click();
  await page.getByText("Inventory imported", { exact: true }).waitFor();
  const creation = page.getByRole("listitem").filter({ hasText: project })
    .getByText("Project created", { exact: true });
  if (!(await creation.count())) await page.getByRole("button", {name:"Older activity"}).click();
  await creation.waitFor();
  await checkViewerAccess(browser, page, origin, project, viewer, eventId, incidentId);
  await page.reload();
  await page.getByText(email, { exact: true }).waitFor();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Password").waitFor();
  await page.reload();
  await page.getByLabel("Password").waitFor();
  assert.equal(await page.getByText(email, { exact: true }).count(), 0);
  console.log("Browser inventory, event ingestion and replay, pseudonym details, key lifecycle and audit history passed.");
} finally {
  await browser.close();
}
