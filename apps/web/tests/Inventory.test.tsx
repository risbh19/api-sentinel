import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Inventory } from "../src/Inventory";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("shows a viewer the persisted revision and pins pagination to it", async () => {
  const row = { id: "row", method: "GET", path: "/widgets", operation_id: null, security: [{ bearer: [] }, {}] };
  const revision = { id: "r", revision: 3, version: "3.1.1", count: 26, warnings: [] };
  const request = vi.fn()
    .mockResolvedValueOnce(Response.json({ revision, entries: [row], next_offset: 25 }))
    .mockResolvedValueOnce(Response.json({ revision, entries: [{ ...row, path: "/z" }], next_offset: null }));
  vi.stubGlobal("fetch", request);
  render(<Inventory project="proj" writable={false} token="test" onExpiry={vi.fn()} />);
  await screen.findByText("bearer or Anonymous");
  expect(screen.queryByRole("button", { name: "Import file" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Next endpoints" }));
  await screen.findByText("/z");
  expect(request.mock.calls[1][0]).toContain("offset=25&revision=3");
});

it("uploads only the selected file and reports an existing revision", async () => {
  const revision = { id: "r", revision: 1, version: "3.0.3", count: 0, warnings: [] };
  const request = vi.fn().mockResolvedValueOnce(Response.json({ revision: null, entries: [], next_offset: null }))
    .mockResolvedValueOnce(Response.json(revision)).mockResolvedValueOnce(Response.json({ revision, entries: [], next_offset: null }));
  vi.stubGlobal("fetch", request);
  render(<Inventory project="proj" writable token="test" onExpiry={vi.fn()} />);
  await screen.findByText("No OpenAPI file has been imported for this project.");
  const selected = new File(["{}"], "example.json", { type: "application/json" });
  fireEvent.change(screen.getByLabelText(/OpenAPI file/), { target: { files: [selected] } });
  // jsdom does not populate the native FileList for a synthetic change event.
  fireEvent.submit(screen.getByRole<HTMLButtonElement>("button", { name: "Import file" }).form!);
  await screen.findByText("This file already exists as revision 1.");
  expect(request).toHaveBeenCalledWith("/api/v1/projects/proj/imports", expect.objectContaining({
    body: selected, headers: { "Content-Type": "application/json", "X-CSRF-Token": "test" },
  }));
});
