import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Workspace } from "../src/Workspace";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("signs in, switches organization, and signs out with the session's CSRF token", async () => {
  const request = vi.fn()
    .mockResolvedValueOnce(new Response(null, { status: 401 }))
    .mockResolvedValueOnce(Response.json({ email: "owner@example.test", csrf_token: "session-test",
      organizations: [{ id: "alpha", name: "Alpha", role: "owner" }, { id: "beta", name: "Beta", role: "viewer" }] }))
    .mockResolvedValueOnce(Response.json([{ id: "p", name: "Primary API", slug: "primary" }]))
    .mockResolvedValueOnce(Response.json([]))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", request);
  render(<Workspace />);
  fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "owner@example.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "local-test-input" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByText("Primary API");
  fireEvent.change(screen.getByLabelText("Organization"), { target: { value: "beta" } });
  await screen.findByText("This organization has no projects yet.");
  expect(screen.queryByText("Primary API")).toBeNull();
  expect(request).toHaveBeenCalledWith("/api/v1/organizations/beta/projects", expect.anything());
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await screen.findByLabelText("Password");
  expect(request).toHaveBeenLastCalledWith("/api/v1/auth/logout", expect.objectContaining({
    method: "POST", headers: { "X-CSRF-Token": "session-test" },
  }));
});

it("clears the workspace when the session expires during a project query", async () => {
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(Response.json({ email: "viewer@example.test", csrf_token: "token",
      organizations: [{ id: "alpha", name: "Alpha", role: "viewer" }] }))
    .mockResolvedValueOnce(new Response(null, { status: 401 })));
  render(<Workspace />);
  await screen.findByText("Your session expired. Sign in again.");
  expect(screen.queryByText("viewer@example.test")).toBeNull();
  expect(screen.getByLabelText("Password")).toBeDefined();
});

it("refreshes the account and CSRF token when another tab rotates the session", async () => {
  const identity = (email: string, csrf_token: string) => Response.json({ email, csrf_token, organizations: [] });
  const requests = vi.fn().mockResolvedValueOnce(identity("first@example.test", "first"))
    .mockResolvedValueOnce(new Response(null, { status: 403 }))
    .mockResolvedValueOnce(identity("second@example.test", "second"))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", requests);
  render(<Workspace />);
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  await screen.findByText("second@example.test");
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await screen.findByLabelText("Password");
  expect(requests).toHaveBeenLastCalledWith("/api/v1/auth/logout", expect.objectContaining({
    headers: { "X-CSRF-Token": "second" },
  }));
});
