import { fileURLToPath } from "node:url";
import axe from "axe-core";
import assert from "node:assert/strict";
import { stdin } from "node:process";
import { chromium } from "playwright-core";

let input = "";
for await (const chunk of stdin) input += chunk;
const { email, password } = JSON.parse(input);
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
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Overview for Smoke API" }).waitFor();
  const project = await page.getByRole("combobox", { name: "Project", exact: true }).inputValue();
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
  await page.getByRole("button", { name: "Inventory for Smoke API" }).click();
  await page.getByLabel(/OpenAPI file/).setInputFiles(fileURLToPath(new URL("../../../examples/petstore.yaml", import.meta.url)));
  await page.getByRole("button", { name: "Import file" }).click();
  await page.getByText("/pets/{petId}", { exact: true }).waitFor();
  await page.getByText("localSession", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Integrations for Smoke API" }).click();
  await page.getByLabel("Emitter name").fill("Browser emitter");
  await page.getByRole("button", { name: "Create key" }).click();
  await page.getByLabel("New ingestion key").waitFor();
  const ingestionKey = await page.getByLabel("New ingestion key").inputValue();
  const payload = { source_id: "synthetic-browser", events: [{ event_id: "browser-event", occurred_at: new Date().toISOString(), event_type: "authentication_failure", method: "POST", route_template: "/api/login", status_code: 401, actor_token: "synthetic-browser-actor" }] };
  const submit = () => page.request.post(origin + "/api/v1/ingest/events", { headers: { Authorization: "Bearer " + ingestionKey }, data: payload });
  const accepted = await submit();
  assert.equal(accepted.status(), 200);
  assert.equal((await accepted.json()).accepted, 1);
  assert.equal((await (await submit()).json()).duplicate, 1);
  await page.getByRole("button", { name: "Hide key" }).click();
  await page.getByRole("button", { name: "Events for Smoke API" }).click();
  await page.getByLabel("Event source").fill("synthetic-browser");
  await page.getByRole("button", { name: "Apply event filters" }).click();
  await page.getByRole("region", { name: "Security events", exact: true }).getByText("/api/login", { exact: true }).waitFor();
  await page.getByRole("button", { name: /^View event / }).click();
  await page.getByText("browser-event", { exact: true }).waitFor();
  assert.equal(await page.getByText("synthetic-browser-actor", { exact: true }).count(), 0);
  await page.getByText("Actor pseudonym", { exact: true }).waitFor();
  const rest = Array.from({length:7}, (_,i)=>({...payload.events[0],event_id:"browser-peer-"+i}));
  const batch = await page.request.post(origin + "/api/v1/ingest/events", {
    headers:{Authorization:"Bearer "+ingestionKey}, data:{source_id:payload.source_id,events:rest}
  });
  assert.equal((await batch.json()).accepted,7);
  // The worker runs independently of ingestion. Await each API response before
  // opening the list so the rendered page includes this source's new alert.
  const deadline = Date.now() + 45000;
  let alertId;
  while (!alertId && Date.now() < deadline) {
    const response = await page.request.get(origin + "/api/v1/projects/" + project + "/alerts");
    assert.equal(response.status(), 200);
    alertId = (await response.json()).entries.find(row => row.source_id === payload.source_id)?.id;
    if (!alertId) await new Promise(resolve => setTimeout(resolve, 400));
  }
  assert.ok(alertId, "The worker must produce the browser source's alert");
  await page.getByRole("button", { name: "Alerts for Smoke API" }).click();
  await page.getByRole("button", { name: "Inspect alert " + alertId, exact: true }).click();
  const evidence = page.getByRole("article",{name:"Alert evidence"});
  await evidence.getByRole("button",{name:/^[a-f0-9-]{36}$/}).first().click();
  await evidence.getByText(/HTTP 401/).waitFor();
  await checkAccessibility("Alert evidence");
  await evidence.getByRole("button",{name:"Create incident from alert"}).click();
  await page.getByLabel("Incident title").fill("Browser login investigation");
  await page.getByRole("button",{name:"Create incident",exact:true}).click();
  await page.getByRole("heading",{name:"Browser login investigation"}).waitFor();
  await page.getByRole("button",{name:"Assign to me"}).click();
  await page.getByText("Assigned to you",{exact:true}).waitFor();
  await page.getByRole("button",{name:"Move to acknowledged"}).click();
  await page.getByRole("button",{name:"Move to investigating"}).waitFor();
  await page.getByLabel("Investigation note").fill("Verified the synthetic browser observations.");
  await page.getByRole("button",{name:"Add note"}).click();
  await page.getByText("Verified the synthetic browser observations.",{exact:true}).waitFor();
  await page.getByRole("button",{name:"Move to investigating"}).click();
  await page.getByRole("button",{name:"Move to resolved"}).click();
  await page.getByRole("button",{name:"Move to reopened"}).waitFor();
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth));
  await checkAccessibility("Mobile incident detail");
  await page.setViewportSize({width:1280,height:800});
  console.log("Browser verified alert evidence, incident promotion, assignment, note and resolution. Three accessibility scans passed.");
  await page.getByRole("button", { name: "Integrations for Smoke API" }).click();
  await page.getByRole("button", { name: "Rotate", exact: true }).click();
  await page.getByRole("button", { name: "Confirm rotate" }).click();
  await page.getByLabel("New ingestion key").waitFor();
  await page.reload();
  await page.getByRole("button", { name: "Integrations for Smoke API" }).click();
  await page.getByRole("button", { name: "Revoke", exact: true }).click();
  assert.equal(await page.getByLabel("New ingestion key").count(), 0);
  await page.getByRole("button", { name: "Confirm revoke" }).click();
  const browserKeys = page.getByRole("region", { name: "Project integrations" }).getByRole("listitem").filter({hasText: "Browser emitter"});
  await browserKeys.getByText(/^Revoked ·/).nth(1).waitFor();
  await page.getByRole("button", { name: "Rotate", exact: true }).waitFor({state:"detached"});
  await page.getByRole("button", { name: "View audit activity" }).click();
  await page.getByText("Inventory imported", { exact: true }).waitFor();
  const creation = page.getByText("Project created", {exact:true});
  if (!(await creation.count())) await page.getByRole("button",{name:"Older activity"}).click();
  await creation.waitFor();
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
