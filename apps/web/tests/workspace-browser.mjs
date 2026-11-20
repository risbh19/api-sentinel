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
  await page.getByText("Smoke API", { exact: false }).waitFor();
  await page.reload();
  await page.getByText(email, { exact: true }).waitFor();
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Password").waitFor();
  await page.reload();
  await page.getByLabel("Password").waitFor();
  assert.equal(await page.getByText(email, { exact: true }).count(), 0);
  console.log("Browser sign-in, project listing, session refresh and logout passed.");
} finally {
  await browser.close();
}
