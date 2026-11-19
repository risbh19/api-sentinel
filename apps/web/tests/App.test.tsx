import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { App } from "../src/App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("reports a database outage and rechecks the API on request", async () => {
  const request = vi.fn()
    .mockResolvedValueOnce(Response.json({ status: "unavailable" }, { status: 503 }))
    .mockResolvedValueOnce(Response.json({ status: "ready" }));
  vi.stubGlobal("fetch", request);
  render(<App />);
  expect(screen.getByText("Checking readiness")).toBeDefined();
  await screen.findByText("Database unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Check again" }));
  await screen.findByText("Ready");
  expect(request).toHaveBeenCalledTimes(2);
  expect(request).toHaveBeenCalledWith("/health/ready", expect.objectContaining({ cache: "no-store" }));
});

it.each([
  () => Promise.reject(new Error("offline")),
  () => Promise.resolve(new Response("<html>")),
  () => Promise.resolve(Response.json({ status: "ready" }, { status: 503 })),
])("shows an inconclusive result for an invalid or missing response", async (respond) => {
  vi.stubGlobal("fetch", respond);
  render(<App />);
  await screen.findByText("Readiness unknown");
});
