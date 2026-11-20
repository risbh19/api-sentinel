import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import { createLogger, createServer as createVite, loadConfigFromFile } from "vite";

async function listen(server) {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return `http://127.0.0.1:${server.address().port}`;
}

async function close(server) {
  await new Promise((resolve) => server.close(resolve));
}

test("development readiness proxy keeps request details out of upstream traffic and outage logs", async (t) => {
  const marker = "synthetic-proxy-regression-marker";
  let received;
  const upstream = createServer((request, response) => {
    received = { url: request.url, headers: request.headers };
    response.writeHead(200, { "Content-Type": "application/json" }).end('{"status":"ready"}');
  });
  const target = await listen(upstream);
  t.after(async () => { if (upstream.listening) await close(upstream); });

  const { config } = await loadConfigFromFile({ command: "serve", mode: "development" });
  const proxy = Object.fromEntries(Object.entries(config.server.proxy).map(([key, options]) =>
    [key, { ...(typeof options === "string" ? {} : options), target }]
  ));
  const logs = [];
  const logger = createLogger();
  logger.error = (message) => logs.push(message);
  const vite = await createVite({
    configFile: false,
    customLogger: logger,
    server: { middlewareMode: true, hmr: false, watch: null, proxy },
  });
  t.after(() => vite.close());
  const server = createServer(vite.middlewares);
  const url = await listen(server);
  t.after(() => close(server));
  const probe = () => fetch(`${url}/health/ready?token=${marker}`, {
    headers: { Cookie: marker, Authorization: marker, "X-Custom": marker },
  });

  assert.equal((await probe()).status, 200);
  assert.equal(received.url, "/health/ready");
  assert.equal(JSON.stringify(received.headers).includes(marker), false);
  await close(upstream);
  assert.equal((await probe()).status, 502);
  assert.ok(logs.some((message) => message.includes("http proxy error")));
  assert.equal(logs.join("\n").includes(marker), false);
});
