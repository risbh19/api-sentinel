import { fillTestPassword, requestLocalApi } from "./browser-requests.mjs";
import assert from "node:assert/strict";

export async function checkViewerAccess(browser, ownerPage, origin, project, account) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  try {
    await context.route("**/*", route =>
      new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    const page = await context.newPage();
    await page.goto(origin + "/#workspace");
    await page.getByLabel("Email").fill(account.email);
    await fillTestPassword(page, account.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    const empty = page.getByText("This organization has no projects yet.");
    await empty.waitFor();

    const api = origin + "/api/v1";
    const detail = api + "/projects/" + project;
    const admin = ownerPage.request;
    const self = await requestLocalApi(context.request, "GET", api + "/auth/me");
    assert.equal(self.status(), 200);
    const member = (await self.json()).id;
    const ownProject = await requestLocalApi(admin, "GET", detail);
    assert.equal(ownProject.status(), 200);
    const org = (await ownProject.json()).organization_id;
    const session = await requestLocalApi(admin, "GET", api + "/auth/me");
    assert.equal(session.status(), 200);
    const headers = { Origin: origin, "X-CSRF-Token": (await session.json()).csrf_token };
    const membership = api + "/organizations/" + org + "/members/" + member;
    assert.equal((await requestLocalApi(context.request, "GET", detail)).status(), 404);

    assert.equal((await requestLocalApi(admin, "PUT", membership, { headers, data: { role: "viewer" } })).status(), 204);
    await page.reload();
    await page.getByLabel("Organization", { exact: true }).selectOption(org);
    await page.getByLabel("Project", { exact: true }).selectOption(project);
    await page.getByRole("button", { name: "Incidents for Synthetic login demo" }).click();
    const summaryResponse = page.waitForResponse(response =>
      response.url().startsWith(detail + "/incidents/") && response.request().method() === "GET");
    await page.getByRole("button", { name: /^View incident / }).click();
    const response = await summaryResponse;
    assert.equal(response.status(), 200);
    const summary = await response.json();
    for (const privateField of ["title", "timeline", "assignee_id"]) {
      assert.equal(Object.hasOwn(summary, privateField), false);
    }
    await page.getByRole("heading", { name: "Incident summary" }).waitFor();
    assert.equal(await page.getByText("Browser login investigation", { exact: true }).count(), 0);
    assert.equal(await page.getByText("Verified the synthetic browser observations.", { exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "Assign to me" }).count(), 0);
    assert.equal(await page.getByRole("button", { name: /^Integrations for / }).count(), 0);
    assert.equal((await requestLocalApi(context.request, "GET", detail + "/ingestion-keys")).status(), 403);

    assert.equal((await requestLocalApi(admin, "DELETE", membership, { headers })).status(), 204);
    assert.equal((await requestLocalApi(context.request, "GET", detail + "/incidents")).status(), 404);
    await page.getByRole("button", { name: "Back to incidents" }).click();
    await page.getByText("This record is unavailable or your access has changed.").waitFor();
    await page.reload();
    await empty.waitFor();
    assert.equal(await page.getByLabel("Project", { exact: true }).count(), 0);
    assert.equal(await page.getByRole("heading", { name: "Incident summary" }).count(), 0);
    console.log("Browser verified tenant isolation, viewer redaction and membership removal in the same session.");
  } finally {
    await context.close();
  }
}
