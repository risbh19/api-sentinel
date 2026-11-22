import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Alerts } from "../src/Alerts";
import { Incidents } from "../src/Incidents";
import { Overview } from "../src/Overview";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const access = {
  project: "first",
  role: "owner",
  token: "csrf-test",
  user: "actor",
  onExpiry: vi.fn(),
};
const stamp = "2026-10-01T00:00:00Z";
const totals = {
  since: stamp,
  until: stamp,
  events: 0,
  open_alerts: 2,
  active_incidents: 1,
  buckets: [],
};

it("drops a late project response and distinguishes an empty window from a failed request", async () => {
  let finish!: (res: Response) => void;
  const fetch = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValueOnce(Response.json(totals));
  vi.stubGlobal("fetch", fetch);
  const view = render(<Overview access={access} />);
  view.rerender(<Overview access={{ ...access, project: "second" }} />);
  await screen.findByRole("alert");
  finish(Response.json({ ...totals, events: 999 }));
  fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
  await screen.findByText("No events occurred in this window.");
  expect(screen.queryByText("999")).toBeNull();
  expect(screen.getByText("Currently open alerts").nextElementSibling?.textContent).toBe("2");
  expect(fetch.mock.calls.at(-1)?.[0]).toContain("/projects/second/");
});

it("keeps alert evidence hidden for a viewer", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      Response.json({
        entries: [
          {
            id: "a",
            rule_key: "authentication_failures",
            source_id: "gateway",
            severity: "medium",
            status: "open",
            last_seen: stamp,
          },
        ],
        next_cursor: null,
      }),
    ),
  );
  render(<Alerts access={{ ...access, role: "viewer" }} promote={() => {}} />);
  await screen.findByText("authentication failures");
  expect(screen.queryByRole("combobox", { name: "Alert status" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Inspect alert/ })).toBeNull();
});

it("refreshes after a conflicting note and keeps the draft for the investigator", async () => {
  const summary = {
    id: "case",
    status: "open",
    priority: "medium",
    version: 1,
    opened_at: stamp,
    resolved_at: null,
  };
  const detail = { ...summary, title: "Review", timeline: [], assignee_id: null };
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(Response.json([summary]))
    .mockResolvedValueOnce(Response.json(detail))
    .mockResolvedValueOnce(
      Response.json({ detail: "Incident changed; reload and retry" }, { status: 409 }),
    )
    .mockResolvedValueOnce(Response.json({ ...detail, version: 2 }))
    .mockResolvedValueOnce(Response.json({ ...summary, version: 3 }))
    .mockResolvedValueOnce(Response.json({ ...detail, version: 3 }));
  vi.stubGlobal("fetch", fetch);
  render(<Incidents access={access} fromAlert="" />);
  fireEvent.click(await screen.findByRole("button", { name: "View incident case" }));
  fireEvent.change(await screen.findByLabelText("Investigation note"), {
    target: { value: "Retain this draft" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add note" }));
  await screen.findByText("Incident changed; reload and retry");
  await screen.findByDisplayValue("Retain this draft");
  fireEvent.click(screen.getByRole("button", { name: "Add note" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/projects/first/incidents/case/notes",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ text: "Retain this draft", version: 2 }),
      }),
    ),
  );
});

it("checks the original timeline entry before retrying a note whose response was lost", async () => {
  const summary = {
    id: "case",
    status: "open",
    priority: "medium",
    version: 1,
    opened_at: stamp,
    resolved_at: null,
  };
  const detail = { ...summary, title: "Review", timeline: [], assignee_id: null };
  const saved = {
    ...detail,
    version: 2,
    timeline: [
      {
        version: 2,
        action: "note_added",
        actor_id: "actor",
        note: "Check once",
        occurred_at: stamp,
      },
    ],
  };
  let notes = 0;
  const fetch = vi.fn(async (url: string, opts?: RequestInit) => {
    if (opts?.method === "POST") {
      notes++;
      throw new TypeError("Connection lost");
    }
    if (url.includes("/case?")) return Response.json(notes ? saved : detail);
    return Response.json([summary]);
  });
  vi.stubGlobal("fetch", fetch);
  render(<Incidents access={access} fromAlert="" />);
  fireEvent.click(await screen.findByRole("button", { name: "View incident case" }));
  fireEvent.change(await screen.findByLabelText("Investigation note"), {
    target: { value: "Check once" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add note" }));
  await screen.findByText("The timeline confirms your note was saved.");
  expect(screen.queryByRole("button", { name: "Add note" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Write another note" }));
  expect(((await screen.findByLabelText("Investigation note")) as HTMLTextAreaElement).value).toBe(
    "",
  );
  expect(notes).toBe(1);
});
