import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Events } from "../src/Events";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const row = { id: "one", source_id: "synthetic", occurred_at: "2026-11-21T00:00:00Z", received_at: "2026-11-21T00:01:00Z", event_type: "authentication_failure", method: "POST", route_template: "/api/login", status_code: 401 };

it("pins pagination to the selected query and withholds viewer details", async () => {
  const request = vi.fn().mockResolvedValueOnce(Response.json({ entries: [row], next_cursor: "signed-cursor" }))
    .mockResolvedValueOnce(Response.json({ entries: [], next_cursor: null }));
  vi.stubGlobal("fetch", request);
  render(<Events project="project" detailed={false} onExpiry={vi.fn()} />);
  await screen.findByText("/api/login");
  expect(screen.queryByText("View details")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Next events" }));
  await screen.findByText(/No accepted events/);
  expect(request.mock.calls[1][0]).toBe(request.mock.calls[0][0] + "&after=signed-cursor");
});

it("shows persisted pseudonyms, then clears a denied event detail", async () => {
  const request = vi.fn().mockResolvedValueOnce(Response.json({ entries: [row, { ...row, id: "two" }], next_cursor: null }))
    .mockResolvedValueOnce(Response.json({ ...row, external_event_id: "synthetic-event", actor_hash: "safe-pseudonym", client_hash: null, pseudonym_version: "version" }))
    .mockResolvedValueOnce(new Response(null, { status: 403 }));
  vi.stubGlobal("fetch", request);
  render(<Events project="project" detailed onExpiry={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "View event one" }));
  await screen.findByText("safe-pseudonym");
  fireEvent.click(screen.getByRole("button", { name: "View event two" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("safe-pseudonym")).toBeNull();
});

it("applies filters without mutating the loaded snapshot and handles expiry", async () => {
  const expired = vi.fn();
  const request = vi.fn().mockResolvedValueOnce(Response.json({ entries: [], next_cursor: null }))
    .mockResolvedValueOnce(new Response(null, { status: 401 }));
  vi.stubGlobal("fetch", request);
  render(<Events project="project" detailed onExpiry={expired} />);
  await screen.findByText(/No accepted events/);
  fireEvent.change(screen.getByLabelText("Event source"), { target: { value: "synthetic-api" } });
  expect(request).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Apply event filters" }));
  await vi.waitFor(() => expect(expired).toHaveBeenCalledOnce());
  expect(request.mock.calls[1][0]).toContain("source=synthetic-api");
});

it("advances a rolling refresh and preserves an applied custom range", async () => {
  const clock = vi.spyOn(Date, "now").mockReturnValue(Date.UTC(2026, 0, 5, 12));
  try {
    const request = vi.fn().mockImplementation(() => Promise.resolve(Response.json({ entries: [], next_cursor: null })));
    vi.stubGlobal("fetch", request);
    render(<Events project="demo" detailed={false} onExpiry={vi.fn()} />);
    const refresh = () => screen.findByRole("button", { name: "Refresh events" });
    await refresh();
    fireEvent.change(screen.getByLabelText("Event source"), {target:{value:"gateway"}});
    fireEvent.click(screen.getByText("Apply event filters"));
    await refresh();
    clock.mockReturnValue(Date.UTC(2026, 0, 5, 15));
    fireEvent.click(await refresh());
    await refresh();
    const latest = () => new URL(request.mock.calls.at(-1)![0], "http://localhost").searchParams;
    expect(latest().get("until")).toBe(new Date(Date.now() + 60000).toISOString());
    expect(latest().get("source")).toBe("gateway");
    const customEnd = (screen.getByLabelText("From (local time)") as HTMLInputElement).value;
    fireEvent.change(screen.getByLabelText("Until (local time)"), { target: { value: customEnd } });
    fireEvent.click(screen.getByText("Apply event filters"));
    await refresh();
    expect(latest().get("until")).toBe(new Date(customEnd).toISOString());
    const custom = latest().toString();
    clock.mockReturnValue(Date.UTC(2026, 0, 6, 15));
    fireEvent.click(await refresh());
    await refresh();
    expect(latest().toString()).toBe(custom);
  } finally {
    clock.mockRestore();
  }
});
