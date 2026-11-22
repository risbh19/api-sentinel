import { useRef, useState, type FormEvent } from "react";
import {
  canInvestigate,
  ReadState,
  useIncidentWrite,
  useProjectRead,
  utc,
  words,
  type Access,
} from "./projectData";

const nextStatus: Record<string, string> = {
  open: "acknowledged",
  acknowledged: "investigating",
  investigating: "resolved",
  resolved: "reopened",
  reopened: "investigating",
};
const uuidPattern = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
type Summary = {
  id: string;
  status: string;
  priority: string;
  version: number;
  opened_at: string;
  resolved_at: string | null;
};
type Entry = {
  version: number;
  actor_id: string;
  action: string;
  old_value: string | null;
  new_value: string | null;
  note: string | null;
  occurred_at: string;
};
type Detail = Summary & {
  title?: string;
  assignee_id?: string | null;
  timeline?: Entry[];
  next_version?: number | null;
};

function NewIncident({
  access,
  alert,
  open,
}: {
  access: Access;
  alert: string;
  open: (id: string) => void;
}) {
  const save = useIncidentWrite(access);
  const key = useRef<{ payload: string; key: string } | null>(null);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fields = new FormData(e.currentTarget);
    const body = {
      title: String(fields.get("title")).trim(),
      priority: fields.get("priority"),
      alert_id: alert || null,
    };
    const payload = JSON.stringify(body);
    if (key.current?.payload !== payload) key.current = { payload, key: crypto.randomUUID() };
    const created = await save.write("/projects/" + access.project + "/incidents", "POST", {
      ...body,
      request_key: key.current.key,
    });
    if (created && created !== "uncertain") open(created.id);
  }
  return (
    <form onSubmit={submit}>
      <h3>{alert ? "Promote alert to incident" : "New incident"}</h3>
      {alert && (
        <p>
          Linked alert <code>{alert}</code>
        </p>
      )}
      <label>
        Incident title
        <input name="title" maxLength={120} required />
      </label>
      <label>
        Priority
        <select name="priority" defaultValue="medium">
          {["low", "medium", "high"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <button disabled={save.busy}>Create incident</button>
      {save.error && <p role="alert">{save.error}</p>}
    </form>
  );
}

type PendingNote = { version: number; text: string };

function ConfirmNote({
  access,
  path,
  pending,
  finish,
  retry,
}: {
  access: Access;
  path: string;
  pending: PendingNote;
  finish: (saved: boolean) => void;
  retry: () => void;
}) {
  const check = useProjectRead<Detail>(
    path + "?after_version=" + pending.version + "&limit=1",
    access.onExpiry,
  );
  return (
    <ReadState read={check}>
      {(detail) => {
        if (!detail.timeline) return <p>Investigator access is required to check this note.</p>;
        const next = detail.timeline[0];
        if (!next)
          return (
            <>
              <p>The note has not appeared in the timeline.</p>
              <button onClick={retry}>Retry original note submission</button>
            </>
          );
        const saved =
          next.version === pending.version + 1 &&
          next.action === "note_added" &&
          next.actor_id === access.user &&
          next.note === pending.text.trim();
        return (
          <>
            <p role="status">
              {saved
                ? "The timeline confirms your note was saved."
                : "Another change used that incident version. Your draft is available."}
            </p>
            <button onClick={() => finish(saved)}>
              {saved ? "Write another note" : "Return to draft"}
            </button>
          </>
        );
      }}
    </ReadState>
  );
}

function Investigation({ access, id, back }: { access: Access; id: string; back: () => void }) {
  const [after, setAfter] = useState(0);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<PendingNote | null>(null);
  const [target, setTarget] = useState("");
  const [alert, setAlert] = useState("");
  const [notice, setNotice] = useState("");
  const path = "/projects/" + access.project + "/incidents/" + id;
  const read = useProjectRead<Detail>(path + "?after_version=" + after, access.onExpiry);
  const save = useIncidentWrite(access);
  async function change(method: string, suffix: string, body: object, version: number) {
    setNotice("");
    const updated = await save.write(path + suffix, method, { ...body, version });
    if (updated === "uncertain" && suffix === "/notes") {
      setPending({ version, text: note });
    } else if (updated && updated !== "uncertain") {
      if (suffix === "/notes") {
        setNote("");
        setPending(null);
      }
      if (suffix.startsWith("/alerts/")) setAlert("");
      setAfter(0);
      setNotice("Incident updated.");
    }
    read.reload();
  }
  return (
    <>
      <button onClick={back}>Back to incidents</button>
      {notice && <p role="status">{notice}</p>}
      {save.error && <p role="alert">{save.error}</p>}
      <ReadState read={read}>
        {(i) => (
          <article className="investigation">
            <h3>{i.title ?? "Incident summary"}</h3>
            <p>
              <code>{i.id}</code>
            </p>
            <dl className="facts">
              <dt>Status</dt>
              <dd>{i.status}</dd>
              <dt>Priority</dt>
              <dd>{i.priority}</dd>
              <dt>Opened (UTC)</dt>
              <dd>{utc(i.opened_at)}</dd>
              {i.resolved_at && (
                <>
                  <dt>Resolved (UTC)</dt>
                  <dd>{utc(i.resolved_at)}</dd>
                </>
              )}
            </dl>
            {i.timeline && canInvestigate(access.role) && (
              <>
                <p>
                  Assigned to {i.assignee_id === access.user ? "you" : (i.assignee_id ?? "nobody")}
                </p>
                <div className="actions">
                  <button
                    disabled={save.busy}
                    onClick={() =>
                      void change("PATCH", "", { status: nextStatus[i.status] }, i.version)
                    }
                  >
                    Move to {nextStatus[i.status]}
                  </button>
                  {i.assignee_id !== access.user && (
                    <button
                      disabled={save.busy}
                      onClick={() =>
                        void change("PATCH", "", { assignee_id: access.user }, i.version)
                      }
                    >
                      Assign to me
                    </button>
                  )}
                  {i.assignee_id && (
                    <button
                      disabled={save.busy}
                      onClick={() => void change("PATCH", "", { assignee_id: null }, i.version)}
                    >
                      Unassign
                    </button>
                  )}
                </div>
                <details>
                  <summary>Assign another investigator or attach an alert</summary>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void change("PATCH", "", { assignee_id: target }, i.version);
                    }}
                  >
                    <label>
                      Investigator UUID
                      <input
                        required
                        pattern={uuidPattern}
                        value={target}
                        onChange={(e) => setTarget(e.target.value)}
                      />
                    </label>
                    <button disabled={save.busy}>Assign investigator</button>
                  </form>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void change("PUT", "/alerts/" + alert, {}, i.version);
                    }}
                  >
                    <label>
                      Alert UUID
                      <input
                        required
                        pattern={uuidPattern}
                        value={alert}
                        onChange={(e) => setAlert(e.target.value)}
                      />
                    </label>
                    <button disabled={save.busy}>Attach alert</button>
                  </form>
                </details>
                <h4>Investigation timeline</h4>
                <ol className="timeline">
                  {i.timeline.map((e) => (
                    <li key={e.version}>
                      <strong>{words(e.action)}</strong> · {utc(e.occurred_at)} UTC
                      <p>
                        Actor <code>{e.actor_id === access.user ? "you" : e.actor_id}</code>
                        {e.old_value && " · from " + e.old_value}
                        {e.new_value && " · " + e.new_value}
                      </p>
                      {e.note && <p className="note">{e.note}</p>}
                    </li>
                  ))}
                </ol>
                {after > 0 && <button onClick={() => setAfter(0)}>First timeline page</button>}
                {i.next_version != null && (
                  <button onClick={() => setAfter(i.next_version!)}>Next timeline page</button>
                )}
                {pending ? (
                  <ConfirmNote
                    access={access}
                    path={path}
                    pending={pending}
                    retry={() => {
                      if (!save.busy)
                        void change("POST", "/notes", { text: pending.text }, pending.version);
                    }}
                    finish={(saved) => {
                      if (saved) setNote("");
                      setPending(null);
                      read.reload();
                    }}
                  />
                ) : (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void change("POST", "/notes", { text: note }, i.version);
                    }}
                  >
                    <label>
                      Investigation note
                      <textarea
                        required
                        disabled={save.busy}
                        maxLength={2000}
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                      />
                    </label>
                    <button disabled={save.busy || !note.trim()}>Add note</button>
                  </form>
                )}
              </>
            )}
            <button onClick={read.reload}>Refresh incident</button>
          </article>
        )}
      </ReadState>
    </>
  );
}

function IncidentList({ access, open }: { access: Access; open: (id: string) => void }) {
  const [status, setStatus] = useState("");
  const [after, setAfter] = useState("");
  const params = new URLSearchParams({ limit: "20" });
  if (status) params.set("status", status);
  if (after) params.set("after", after);
  const read = useProjectRead<Summary[]>(
    "/projects/" + access.project + "/incidents?" + params,
    access.onExpiry,
  );
  return (
    <>
      <label>
        Incident status
        <select
          value={status}
          onChange={(e) => {
            setAfter("");
            setStatus(e.target.value);
          }}
        >
          <option value="">All statuses</option>
          {Object.keys(nextStatus).map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <ReadState read={read}>
        {(rows) => (
          <>
            {!rows.length && <p>No incidents on this page.</p>}
            <ul className="records">
              {rows.map((i) => (
                <li key={i.id}>
                  <strong>
                    {i.priority} priority · {i.status}
                  </strong>
                  <p>Opened {utc(i.opened_at)} UTC</p>
                  <button onClick={() => open(i.id)}>View incident {i.id}</button>
                </li>
              ))}
            </ul>
            {after && <button onClick={() => setAfter("")}>First incident page</button>}
            {rows.length === 20 && (
              <button onClick={() => setAfter(rows[19].id)}>Next incident page</button>
            )}
          </>
        )}
      </ReadState>
    </>
  );
}

export function Incidents({ access, fromAlert }: { access: Access; fromAlert: string }) {
  const [selected, setSelected] = useState("");
  const [creating, setCreating] = useState(Boolean(fromAlert));
  const [alert, setAlert] = useState(fromAlert);
  function back() {
    setCreating(false);
    setSelected("");
    setAlert("");
  }
  return (
    <section aria-label="Project incidents">
      <h2>Incidents</h2>
      {creating && canInvestigate(access.role) ? (
        <>
          <NewIncident
            access={access}
            alert={alert}
            open={(id) => {
              setCreating(false);
              setSelected(id);
            }}
          />
          <button onClick={back}>Cancel</button>
        </>
      ) : selected ? (
        <Investigation key={selected} access={access} id={selected} back={back} />
      ) : (
        <>
          {canInvestigate(access.role) && (
            <button
              onClick={() => {
                setCreating(true);
                setAlert("");
              }}
            >
              New incident
            </button>
          )}
          <IncidentList access={access} open={setSelected} />
        </>
      )}
    </section>
  );
}
