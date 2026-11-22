// Playwright error call logs can contain the filled value or request headers.
export async function fillTestPassword(page, password) {
  try {
    await page.getByLabel("Password").fill(password);
  } catch {
    throw new Error("Could not fill the test account password.");
  }
}

export async function requestLocalApi(client, method, url, options = {}) {
  if (new URL(url).origin !== "http://127.0.0.1:8080") {
    throw new Error("Browser API checks require the local web proxy.");
  }
  try {
    return await client.fetch(url, { ...options, method, maxRedirects: 0 });
  } catch {
    throw new Error(`Local API ${method} request failed before a response was received.`);
  }
}
