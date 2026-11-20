import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Integrations } from "../src/Integrations";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const key = { id: "id", label: "Orders", prefix: "asi_example", last_used_at: null, revoked_at: null };
const listing = () => Response.json({entries:[key], next_cursor:null});

it("displays the issued value once and keeps it out of browser storage", async () => {
  const secret = "synthetic-one-time-value";
  const request = vi.fn().mockResolvedValueOnce(Response.json({entries:[], next_cursor:null}))
    .mockResolvedValueOnce(Response.json({key,secret}, {status:201})).mockResolvedValueOnce(listing())
    .mockResolvedValueOnce(listing());
  vi.stubGlobal("fetch", request);
  const props = {project:"project", writable:true, csrf:"test-csrf", onExpiry:vi.fn()};
  const view = render(<Integrations {...props} />);
  await screen.findByText("No ingestion keys on this page.");
  fireEvent.change(screen.getByLabelText("Emitter name"), {target:{value:"Orders"}});
  fireEvent.click(screen.getByRole("button", {name:"Create key"}));
  expect((await screen.findByLabelText<HTMLInputElement>("New ingestion key")).value).toBe(secret);
  expect(request).toHaveBeenCalledWith("/api/v1/projects/project/ingestion-keys", expect.objectContaining({
    method:"POST", headers:{"X-CSRF-Token":"test-csrf","Content-Type":"application/json"}, body:JSON.stringify({label:"Orders"}),
  }));
  expect(JSON.stringify([localStorage,sessionStorage])).not.toContain(secret);
  fireEvent.click(screen.getByRole("button", {name:"Hide key"}));
  expect(screen.queryByLabelText("New ingestion key")).toBeNull();
  view.unmount();
  render(<Integrations {...props} />);
  await screen.findByText("asi_example…");
  expect(screen.queryByDisplayValue(secret)).toBeNull();
});

it("requires confirmation before revocation and keeps analyst metadata read-only", async () => {
  const request = vi.fn().mockResolvedValueOnce(listing())
    .mockResolvedValueOnce(new Response(null,{status:204}))
    .mockResolvedValueOnce(Response.json({entries:[{...key,revoked_at:"2026-11-20T00:00:00Z"}],next_cursor:null}));
  vi.stubGlobal("fetch",request);
  const props = {project:"project",csrf:"csrf",onExpiry:vi.fn()};
  const view = render(<Integrations {...props} writable={false} />);
  await screen.findByText("Orders");
  expect(screen.queryByRole("button",{name:"Create key"})).toBeNull();
  expect(screen.queryByRole("button",{name:"Revoke"})).toBeNull();
  view.rerender(<Integrations {...props} writable />);
  fireEvent.click(screen.getByRole("button",{name:"Revoke"}));
  expect(request).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button",{name:"Confirm revoke"}));
  await waitFor(() => expect(screen.getByText(/Revoked · Last used/)).toBeDefined());
  expect(request.mock.calls[1][0]).toBe("/api/v1/projects/project/ingestion-keys/id/revoke");
});

it("keeps an issued key available when the metadata refresh fails temporarily", async () => {
  const request = vi.fn().mockResolvedValueOnce(listing())
    .mockResolvedValueOnce(Response.json({key, secret:"one-time-replacement"}, {status:201}))
    .mockResolvedValueOnce(new Response(null, {status:503}));
  vi.stubGlobal("fetch", request);
  render(<Integrations project="project" writable csrf="csrf" onExpiry={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button",{name:"Rotate"}));
  fireEvent.click(screen.getByRole("button",{name:"Confirm rotate"}));
  await screen.findByText("Could not load ingestion keys.");
  expect(screen.getByDisplayValue("one-time-replacement")).toBeDefined();
});
