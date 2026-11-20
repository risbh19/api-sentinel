import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "./api";

type Key = { id: string; prefix: string; label: string; last_used_at: string | null; revoked_at: string | null };
type KeyPage = { entries: Key[]; next_cursor: string | null };
type Change = "rotate" | "revoke";

export function Integrations({ project, writable, csrf, onExpiry }: {
  project: string; writable: boolean; csrf: string; onExpiry: () => void;
}) {
  const base = "/projects/" + project + "/ingestion-keys";
  const [page, setPage] = useState<KeyPage | null>(null);
  const [cursor, setCursor] = useState("");
  const [revision, setRevision] = useState(0);
  const [secret, setSecret] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<{id: string; action: Change} | null>(null);
  const mutation = useRef<AbortController | null>(null);

  useEffect(() => {
    function forget() { mutation.current?.abort(); setSecret(""); setBusy(false); }
    window.addEventListener("pagehide", forget);
    return () => { mutation.current?.abort(); window.removeEventListener("pagehide", forget); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const query = cursor ? "?after=" + encodeURIComponent(cursor) : "";
    void api(base + query, {signal: controller.signal}).then(async (response) => {
      if (controller.signal.aborted) return;
      if (response.status === 401) { setSecret(""); onExpiry(); return; }
      if (response.status === 403 || response.status === 404) {
        setPage(null); setSecret(""); setError("Access to these ingestion keys is unavailable.");
        return;
      }
      if (!response.ok) throw new Error();
      const result: KeyPage = await response.json();
      if (!controller.signal.aborted) setPage(result);
    }).catch(() => {
      if (!controller.signal.aborted) { setPage(null); setError("Could not load ingestion keys."); }
    });
    return () => controller.abort();
  }, [base, cursor, revision, onExpiry]);

  function refresh(next = "") {
    setConfirmation(null); setPage(null); setCursor(next); setRevision((v) => v + 1);
  }
  async function change(key?: Key, action?: Change) {
    if (mutation.current && !mutation.current.signal.aborted) return;
    const controller = new AbortController();
    mutation.current = controller;
    setBusy(true); setError(""); setSecret(""); setConfirmation(null);
    try {
      const path = key ? "/" + key.id + "/" + action : "";
      const response = await api(base + path, {method: "POST", signal: controller.signal,
        headers: {"X-CSRF-Token": csrf, "Content-Type": "application/json"},
        body: key ? undefined : JSON.stringify({label})});
      if (controller.signal.aborted) return;
      if (response.status === 401) { onExpiry(); return; }
      if (!response.ok) {
        setError(response.status === 403 ? "Permission or session changed. Reload the workspace." :
          response.status === 409 ? "This key was already revoked." : "Could not change this key. Check the list before retrying.");
      } else if (action !== "revoke") {
        const issued = await response.json();
        if (controller.signal.aborted) return;
        setSecret(issued.secret); setLabel("");
      }
      refresh();
    } catch {
      if (!controller.signal.aborted) { setError("The change could not be confirmed. Check the key list before retrying."); refresh(); }
    } finally {
      if (!controller.signal.aborted) setBusy(false);
      if (mutation.current === controller) mutation.current = null;
    }
  }
  function create(event: FormEvent) { event.preventDefault(); void change(); }
  return <section aria-label="Project integrations"><h3>Ingestion keys</h3>
    {writable && <form onSubmit={create}><label>Emitter name<input required maxLength={48} pattern="[A-Za-z0-9][A-Za-z0-9 ._\-]*" value={label} onChange={(e) => setLabel(e.target.value)} /></label>
      <button disabled={busy}>Create key</button></form>}
    {secret && <div><p>Save this key in your emitter’s secret store. It is shown once.</p>
      <label>New ingestion key<input readOnly autoComplete="off" spellCheck={false} value={secret} onFocus={(e) => e.target.select()} /></label>
      <button onClick={() => setSecret("")}>Hide key</button></div>}
    {error && <p role="alert">{error}</p>}
    {page ? <>{!page.entries.length && <p>No ingestion keys on this page.</p>}
      <ul>{page.entries.map((key) => <li key={key.id}><strong>{key.label}</strong> <code>{key.prefix}…</code>
        <p>{key.revoked_at ? "Revoked" : "Active"} · Last used {key.last_used_at ? new Date(key.last_used_at).toLocaleString() : "never"}</p>
        {writable && !key.revoked_at && (confirmation?.id === key.id ? <>
          <p>{confirmation.action === "rotate" ? "Rotate this key and immediately revoke its current credential?" : "Revoke this key immediately?"}</p>
          <button disabled={busy} onClick={() => void change(key, confirmation.action)}>Confirm {confirmation.action}</button>
          <button onClick={() => setConfirmation(null)}>Cancel</button></> : <>
          <button disabled={busy} onClick={() => setConfirmation({id:key.id,action:"rotate"})}>Rotate</button>
          <button disabled={busy} onClick={() => setConfirmation({id:key.id,action:"revoke"})}>Revoke</button></>)}
      </li>)}</ul>
      {page.next_cursor && <button onClick={() => refresh(page.next_cursor!)}>More keys</button>}</> :
      !error && <p role="status">Loading ingestion keys…</p>}
    <button disabled={busy} onClick={() => {setError(""); refresh();}}>Refresh keys</button>
    <p>Check your emitter connection with a bearer key at <code>/api/v1{base}/check</code> using POST.</p>
  </section>;
}
