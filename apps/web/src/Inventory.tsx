import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "./api";

type Revision = { id: string; revision: number; version: string; count: number; warnings: string[]; created_at: string };
type Security = Record<string, string[]>[];
type Endpoint = { id: string; method: string; path: string; operation_id: string | null; security: Security | null };
type Page = { revision: Revision | null; entries: Endpoint[]; next_offset: number | null };

function declaration(security: Security | null) {
  if (security === null) return "Unspecified";
  if (!security.length) return "None declared";
  return security.map((group) => Object.entries(group).map(([scheme, scopes]) =>
    scopes.length ? scheme + " (" + scopes.join(", ") + ")" : scheme
  ).join(" and ") || "Anonymous").join(" or ");
}

export function Inventory({ project, writable, token, onExpiry }: {
  project: string; writable: boolean; token: string; onExpiry: () => void;
}) {
  const [revision, setRevision] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [method, setMethod] = useState("");
  const [reload, setReload] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploading, setUploading] = useState(false);
  const upload = useRef<AbortController | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const base = "/projects/" + project;
  useEffect(() => () => upload.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ limit: "25", offset: String(offset) });
    if (method) query.set("method", method);
    if (revision !== null) query.set("revision", String(revision));
    void api(base + "/endpoints?" + query, { signal: controller.signal }).then(async (response) => {
      if (controller.signal.aborted) return;
      if (response.status === 401) { onExpiry(); return; }
      if (!response.ok) throw new Error();
      const data: Page = await response.json();
      if (!controller.signal.aborted) setPage(data);
    }).catch(() => { if (!controller.signal.aborted) setError("Could not load endpoint inventory."); });
    return () => controller.abort();
  }, [base, revision, method, offset, reload, onExpiry]);

  function load(version: number | null, start = 0) {
    setPage(null); setError(""); setRevision(version); setOffset(start); setReload((n) => n + 1);
  }
  async function importFile(event: FormEvent) {
    event.preventDefault();
    const selected = file.current?.files?.[0];
    if (!selected) return;
    if (selected.size > 128 * 1024) { setNotice("Choose a file of 128 KiB or less."); return; }
    const controller = new AbortController();
    upload.current = controller;
    setUploading(true); setNotice("");
    try {
      const response = await api(base + "/imports", { method: "POST", signal: controller.signal,
        headers: { "Content-Type": /\.json$/i.test(selected.name) ? "application/json" : "application/yaml", "X-CSRF-Token": token }, body: selected });
      if (controller.signal.aborted) return;
      if (response.status === 401) { onExpiry(); return; }
      if (!response.ok) {
        let message = "Could not import this file.";
        if (response.status === 422) message = (await response.json()).detail;
        if (response.status === 413) message = "Choose a file of 128 KiB or less.";
        if (response.status === 403) message = "Import permission or session details changed. Reload the workspace.";
        if (!controller.signal.aborted) setNotice(message);
        return;
      }
      const result: Revision = await response.json();
      if (controller.signal.aborted) return;
      setNotice(response.status === 200 ? "This file already exists as revision " + result.revision + "." : "Imported revision " + result.revision + ".");
      if (file.current) file.current.value = "";
      setMethod(""); load(result.revision);
    } catch { if (!controller.signal.aborted) setNotice("Could not reach the import service."); }
    finally { if (!controller.signal.aborted) setUploading(false); }
  }

  return <section aria-label="Endpoint inventory"><h3>Endpoint inventory</h3>
    {writable && <form onSubmit={importFile}><label>OpenAPI file (JSON or YAML, up to 128 KiB)
      <input type="file" accept=".json,.yaml,.yml" ref={file} required /></label>
      <button disabled={uploading}>{uploading ? "Importing…" : "Import file"}</button></form>}
    {notice && <p role="status">{notice}</p>}
    {error ? <><p role="alert">{error}</p><button onClick={() => load(revision, offset)}>Retry inventory</button></> :
      !page ? <p role="status">Loading inventory…</p> :
      !page.revision ? <p>No OpenAPI file has been imported for this project.</p> :
      <><p>Revision {page.revision.revision} · OpenAPI {page.revision.version} · {page.revision.count} endpoints</p>
        {page.revision.warnings.map((warning) => <p key={warning}>{warning}</p>)}
        {page.revision.revision > 1 && <button onClick={() => load(page.revision!.revision - 1)}>Previous revision</button>}
        {revision !== null && <button onClick={() => load(null)}>Latest revision</button>}
        <label>HTTP method<select value={method} onChange={(e) => { setMethod(e.target.value); load(page.revision!.revision); }}>
          <option value="">All methods</option>{["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD","TRACE"].map((m) => <option key={m}>{m}</option>)}</select></label>
        {page.entries.length ? <div className="inventory-table"><table><thead><tr><th>Method</th><th>Path</th><th>Operation ID</th><th>Declared security</th></tr></thead>
          <tbody>{page.entries.map((e) => <tr key={e.id}><td>{e.method}</td><td><code>{e.path}</code></td><td>{e.operation_id ?? "—"}</td><td>{declaration(e.security)}</td></tr>)}</tbody></table></div> :
          <p>No endpoints match this view.</p>}
        {offset > 0 && <button onClick={() => load(page.revision!.revision, Math.max(0, offset - 25))}>Previous endpoints</button>}
        {page.next_offset !== null && <button onClick={() => load(page.revision!.revision, page.next_offset!)}>Next endpoints</button>}
      </>}
  </section>;
}
