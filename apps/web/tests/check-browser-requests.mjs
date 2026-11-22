import assert from "node:assert/strict";
import test from "node:test";
import { fillTestPassword, requestLocalApi } from "./browser-requests.mjs";

const endpoint = "http://127.0.0.1:8080/api/v1/auth/me";

test("browser API checks stop at redirects and reject other origins before sending", async () => {
  let requests = 0;
  const client = {
    async fetch(url, options) {
      requests++;
      assert.equal(url, endpoint);
      assert.equal(options.method, "GET");
      assert.equal(options.maxRedirects, 0);
      return { status: () => 307 };
    },
  };
  assert.equal((await requestLocalApi(client, "GET", endpoint)).status(), 307);
  await assert.rejects(requestLocalApi(client, "GET", "https://outside.invalid/"),
    { message: "Browser API checks require the local web proxy." });
  assert.equal(requests, 1);
});

test("browser failures omit sensitive Playwright diagnostics", async () => {
  const marker = "synthetic-private-marker";
  function fail() { throw new Error("Playwright call log: " + marker); }
  const page = { getByLabel: () => ({ fill: fail }) };
  const client = { fetch: fail };
  await assert.rejects(fillTestPassword(page, marker), {
    message: "Could not fill the test account password.",
  });
  await assert.rejects(requestLocalApi(client, "PUT", endpoint, {
    headers: { "X-CSRF-Token": marker },
  }), { message: "Local API PUT request failed before a response was received." });
});
