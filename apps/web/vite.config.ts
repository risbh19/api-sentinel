import { createLogger } from "vite";
import { defineConfig } from "vitest/config";

const logger = createLogger();
const writeError = logger.error.bind(logger);
logger.error = (message, options) => {
  if (message.includes("/api/v1/")) writeError("Local API proxy unavailable");
  else writeError(message, options);
};

export default defineConfig({
  customLogger: logger,
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api/v1/": { target: "http://127.0.0.1:8000" },
      "^/health/ready(?:\\?.*)?$": {
        target: "http://127.0.0.1:8000",
        bypass(request) {
          // Vite uses this URL in its upstream connection error log.
          request.url = "/health/ready";
          const hasBody = request.headers["transfer-encoding"] !== undefined ||
            Number(request.headers["content-length"] ?? 0) !== 0;
          if (request.method !== "GET" || hasBody) return false;
          request.headers = { host: "127.0.0.1:8000" };
        },
      },
    },
  },
  test: { environment: "jsdom" },
});
