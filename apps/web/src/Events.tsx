import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";

type Event = { id: string; source_id: string; occurred_at: string; received_at: string; event_type: string; method: string; route_template: string; status_code: number };
type Detail = Event & { external_event_id: string; actor_hash: string | null; client_hash: string | null; pseudonym_version: string };
type Page = { entries: Event[]; next_cursor: string | null };

function localTime(date: Date) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function Events({ project, detailed, onExpiry }: { project: string; detailed: boolean; onExpiry: () => void }) {
  const [until, setUntil] = useState(() => localTime(new Date(Date.now() + 60000)));
  const [since, setSince] = useState(() => localTime(new Date(Date.now() - 24 * 3600000)));
  const [source, setSource] = useState("");
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const [filters, setFilters] = useState(() => new URLSearchParams({ since: new Date(Date.now() - 24 * 3600000).toISOString(), until: new Date(Date.now() + 60000).toISOString(), limit: "25" }).toString());
  const [cursor, setCursor] = useState("");
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailRevision, setDetailRevision] = useState(0);
  const base = "/projects/" + project + "/events";

  useEffect(() => {
    const controller = new AbortController();
    const query = filters + (cursor ? "&after=" + encodeURIComponent(cursor) : "");
    void api(base + "?" + query, { signal: controller.signal }).then(async (response) => {
      if (controller.signal.aborted) return;
      if (response.status === 401) { onExpiry(); return; }
      if (!response.ok) throw new Error(response.status === 403 || response.status === 404 ? "Access to these events is unavailable." : "Could not load events. Check the time range and retry.");
      const result: Page = await response.json();
      if (!controller.signal.aborted) setPage(result);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Could not load events.");
    });
    return () => controller.abort();
  }, [base, filters, cursor, revision, onExpiry]);

  useEffect(() => {
    if (!selected || !detailed) return;
    const controller = new AbortController();
    void api(base + "/" + selected, { signal: controller.signal }).then(async (response) => {
      if (controller.signal.aborted) return;
      if (response.status === 401) { onExpiry(); return; }
      if (!response.ok) throw new Error();
      const result: Detail = await response.json();
      if (!controller.signal.aborted) setDetail(result);
    }).catch(() => { if (!controller.signal.aborted) setDetailError("Event details are unavailable. Your permission may have changed."); });
    return () => controller.abort();
  }, [base, selected, detailed, detailRevision, onExpiry]);

  function load(after = "") {
    setCursor(after); setPage(null); setError(""); setSelected(""); setDetail(null); setDetailError(""); setRevision((v) => v + 1);
  }
  function apply(event: FormEvent) {
    event.preventDefault();
    const start = new Date(since), end = new Date(until);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end < start || end.getTime() - start.getTime() > 30 * 86400000) {
      setError("Choose an ordered time range of at most 30 days."); return;
    }
    const query = new URLSearchParams({ since: start.toISOString(), until: end.toISOString(), limit: "25" });
    if (source) query.set("source", source);
    if (category) query.set("event_type", category);
    if (status) query.set("status_code", status);
    setFilters(query.toString()); load();
  }

  return <section aria-label="Security events"><h3>Security events</h3>
    <p>Application observations, newest received first. Times below are UTC. These events do not establish a vulnerability.</p>
    <form onSubmit={apply}>
      <label>From (local time)<input required type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} /></label>
      <label>Until (local time)<input required type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
      <label>Event source<input maxLength={64} pattern="[A-Za-z][A-Za-z0-9_\-]*" value={source} onChange={(e) => setSource(e.target.value)} /></label>
      <label>Event category<select value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option><option value="request">Request</option><option value="authentication_failure">Authentication failure</option><option value="authorization_denial">Authorization denial</option></select></label>
      <label>HTTP status<input type="number" min={100} max={599} value={status} onChange={(e) => setStatus(e.target.value)} /></label>
      <button>Apply event filters</button>
    </form>
    {error ? <><p role="alert">{error}</p><button onClick={() => load()}>Retry events</button></> : !page ? <p role="status">Loading events…</p> : <>
      {!page.entries.length ? <p>No accepted events match this time range. Send a synthetic batch with a project ingestion key.</p> :
        <div className="inventory-table"><table><thead><tr><th>Occurred (UTC)</th><th>Source</th><th>Category</th><th>Method</th><th>Route</th><th>Status</th>{detailed && <th>Details</th>}</tr></thead>
          <tbody>{page.entries.map((row) => <tr key={row.id}><td><time dateTime={row.occurred_at}>{new Date(row.occurred_at).toISOString()}</time></td><td>{row.source_id}</td><td>{row.event_type}</td><td>{row.method}</td><td><code>{row.route_template}</code></td><td>{row.status_code}</td>{detailed && <td><button aria-label={"View event " + row.id} onClick={() => { setDetail(null); setDetailError(""); setSelected(row.id); setDetailRevision((v) => v + 1); }}>View details</button></td>}</tr>)}</tbody></table></div>}
      {page.next_cursor && <button onClick={() => load(page.next_cursor!)}>Next events</button>}
      {cursor && <button onClick={() => load()}>First events</button>}
      <button onClick={() => load()}>Refresh events</button>
    </>}
    {selected && detailed && <section aria-label="Event details"><h4>Event details</h4>
      {detailError ? <p role="alert">{detailError}</p> : detail ? <dl>
        <dt>Event ID</dt><dd>{detail.id}</dd><dt>Emitter event ID</dt><dd>{detail.external_event_id}</dd>
        <dt>Received (UTC)</dt><dd>{new Date(detail.received_at).toISOString()}</dd>
        <dt>Actor pseudonym</dt><dd><code>{detail.actor_hash ?? "Not supplied"}</code></dd>
        <dt>Client pseudonym</dt><dd><code>{detail.client_hash ?? "Not supplied"}</code></dd>
        <dt>Pseudonym key version</dt><dd>{detail.pseudonym_version}</dd>
      </dl> : <p role="status">Loading event details…</p>}
      <button onClick={() => { setSelected(""); setDetail(null); }}>Close event details</button>
    </section>}
  </section>;
}
