import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AuditActivity } from "../src/AuditActivity";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("pages recorded activity and clears stale entries when access changes", async () => {
  const request = vi.fn().mockResolvedValueOnce(Response.json({
    entries: [{ id: "e", action: "member.role_changed", actor_id: "owner-id", subject_user_id: "member-id",
      old_role: "viewer", new_role: "analyst", occurred_at: "2026-11-20T10:00:00Z", request_id: "request-id" }],
    next_cursor: "next",
  })).mockResolvedValueOnce(new Response(null, { status: 403 }));
  vi.stubGlobal("fetch", request);
  render(<AuditActivity orgId="team" onExpiry={vi.fn()} />);
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "View audit activity" }));
  await screen.findByText("Member role changed");
  expect(screen.getByText("owner-id")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Older activity" }));
  await screen.findByText("Access to this audit history is unavailable.");
  expect(screen.queryByText("owner-id")).toBeNull();
  expect(request).toHaveBeenLastCalledWith("/api/v1/organizations/team/audit?limit=20&before=next", expect.anything());
});
