import { useEffect, useState } from "react";
import { api } from "./api";

const labels: Record<string, string> = {
  "key.created": "Ingestion key created",
  "key.revoked": "Ingestion key revoked",
  "incident.changed": "Incident updated",
  "inventory.imported": "Inventory imported",
  "project.created": "Project created",
  "project.deleted": "Project deleted",
  "member.added": "Member added",
  "member.role_changed": "Member role changed",
  "member.removed": "Member removed",
};

type Entry = {
  id: string; occurred_at: string; action: string; actor_id: string | null;
  key_id: string | null; project_id: string | null; subject_user_id: string | null;
  old_role: string | null; new_role: string | null; request_id: string | null;
};
type Page = { entries: Entry[]; next_cursor: string | null };

function History({ orgId, onExpiry }: { orgId: string; onExpiry: () => void }) {
  const [cursor, setCursor] = useState("");
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    const path = "/organizations/" + orgId + "/audit?limit=20" + (cursor ? "&before=" + encodeURIComponent(cursor) : "");
    void api(path, { signal: controller.signal }).then(async (res) => {
      if (controller.signal.aborted) return;
      if (res.status === 401) { onExpiry(); return; }
      if (!res.ok) {
        setError(res.status === 403 || res.status === 404 ? "Access to this audit history is unavailable." : "Unable to load audit activity.");
        return;
      }
      const result: Page = await res.json();
      if (!controller.signal.aborted) setPage(result);
    }).catch(() => { if (!controller.signal.aborted) setError("Unable to load audit activity."); });
    return () => controller.abort();
  }, [orgId, cursor, revision, onExpiry]);

  function load(before: string) {
    setPage(null);
    setError("");
    setCursor(before);
    setRevision((current) => current + 1);
  }

  if (error) return <><p role="alert">{error}</p><button onClick={() => load("")}>Retry audit history</button></>;
  if (!page) return <p role="status">Loading audit activity…</p>;
  return <>
    {page.entries.length ? <ol className="audit-entries">{page.entries.map((entry) => <li key={entry.id}>
      <strong>{labels[entry.action] ?? entry.action}</strong>{" · "}
      <time dateTime={entry.occurred_at}>{new Date(entry.occurred_at).toLocaleString()}</time>
      <dl>
        <dt>Actor</dt><dd>{entry.actor_id ?? "Local operator"}</dd>
        {entry.key_id && <><dt>Key ID</dt><dd>{entry.key_id}</dd></>}
        {entry.project_id && <><dt>Project</dt><dd>{entry.project_id}</dd></>}
        {entry.subject_user_id && <><dt>Member</dt><dd>{entry.subject_user_id}</dd></>}
        {entry.old_role && <><dt>Previous role</dt><dd>{entry.old_role}</dd></>}
        {entry.new_role && <><dt>New role</dt><dd>{entry.new_role}</dd></>}
        {entry.request_id && <><dt>Request ID</dt><dd>{entry.request_id}</dd></>}
      </dl>
    </li>)}</ol> : <p>No audit activity recorded for this organization.</p>}
    {page.next_cursor && <button onClick={() => load(page.next_cursor!)}>Older activity</button>}
    {cursor && <button onClick={() => load("")}>Latest activity</button>}
  </>;
}

export function AuditActivity(props: { orgId: string; onExpiry: () => void }) {
  const [open, setOpen] = useState(false);
  return <section aria-label="Audit activity">
    <button aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide audit activity" : "View audit activity"}</button>
    {open && <History {...props} />}
  </section>;
}
