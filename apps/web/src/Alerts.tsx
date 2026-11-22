import { useState } from "react";
import { canInvestigate, ReadState, useProjectRead, utc, words, type Access } from "./projectData";

type Alert = {
  id: string;
  source_id: string;
  rule_key: string;
  severity: string;
  status: string;
  version: number;
  threshold: number;
  window_seconds: number;
  last_seen: string;
  occurrence_count: number;
};
type Detail = Alert & {
  explanation: string;
  caveat: string;
  evidence: string[];
  next_evidence_cursor: string | null;
};
type Page = { entries: Alert[]; next_cursor: string | null };
type Event = {
  method: string;
  route_template: string;
  status_code: number;
  occurred_at: string;
  event_type: string;
};

function Observation({ access, id }: { access: Access; id: string }) {
  const read = useProjectRead<Event>(
    "/projects/" + access.project + "/events/" + id,
    access.onExpiry,
  );
  return (
    <ReadState read={read}>
      {(e) => (
        <p>
          {e.method} <code>{e.route_template}</code> · HTTP {e.status_code} · {words(e.event_type)}{" "}
          · {utc(e.occurred_at)} UTC
        </p>
      )}
    </ReadState>
  );
}

function Evidence({
  access,
  id,
  promote,
}: {
  access: Access;
  id: string;
  promote: (id: string) => void;
}) {
  const [after, setAfter] = useState("");
  const [event, setEvent] = useState("");
  const read = useProjectRead<Detail>(
    "/projects/" + access.project + "/alerts/" + id + (after ? "?after=" + after : ""),
    access.onExpiry,
  );
  return (
    <ReadState read={read}>
      {(a) => (
        <article className="investigation" aria-label="Alert evidence">
          <h3>{words(a.rule_key)}</h3>
          <p>
            Rule version {a.version} · {a.severity} severity · {a.occurrence_count} matching
            findings
          </p>
          <p>{a.explanation}</p>
          <p>{a.caveat}</p>
          {canInvestigate(access.role) && (
            <button onClick={() => promote(id)}>Create incident from alert</button>
          )}
          <h4>Supporting events</h4>
          <ul>
            {a.evidence.map((key) => (
              <li key={key}>
                <button onClick={() => setEvent(key)}>{key}</button>
                {event === key && <Observation access={access} id={key} />}
              </li>
            ))}
          </ul>
          {!a.evidence.length && <p>No supporting events remain.</p>}
          {after && (
            <button
              onClick={() => {
                setEvent("");
                setAfter("");
              }}
            >
              First evidence page
            </button>
          )}
          {a.next_evidence_cursor && (
            <button
              onClick={() => {
                setEvent("");
                setAfter(a.next_evidence_cursor!);
              }}
            >
              Next evidence page
            </button>
          )}
        </article>
      )}
    </ReadState>
  );
}

export function Alerts({ access, promote }: { access: Access; promote: (id: string) => void }) {
  const [status, setStatus] = useState("");
  const [after, setAfter] = useState("");
  const [selected, setSelected] = useState("");
  const params = new URLSearchParams({ limit: "20" });
  if (status) params.set("status", status);
  if (after) params.set("after", after);
  const read = useProjectRead<Page>(
    "/projects/" + access.project + "/alerts?" + params,
    access.onExpiry,
  );
  function page(cursor: string) {
    setSelected("");
    setAfter(cursor);
  }
  return (
    <section aria-label="Project alerts">
      <div className="heading">
        <h2>Alerts</h2>
        <label>
          Alert status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              page("");
            }}
          >
            <option value="">All statuses</option>
            {["open", "acknowledged", "resolved"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      <ReadState read={read}>
        {(data) => (
          <>
            {!data.entries.length && <p>No alerts match this filter.</p>}
            <ul className="records">
              {data.entries.map((a) => (
                <li key={a.id}>
                  <strong>{words(a.rule_key)}</strong>
                  <p>
                    {a.source_id} · {a.severity} · {a.status} · {utc(a.last_seen)} UTC
                  </p>
                  {access.role !== "viewer" && (
                    <button
                      aria-expanded={selected === a.id}
                      onClick={() => setSelected(selected === a.id ? "" : a.id)}
                    >
                      Inspect alert {a.id}
                    </button>
                  )}
                  {selected === a.id && (
                    <Evidence key={a.id} access={access} id={a.id} promote={promote} />
                  )}
                </li>
              ))}
            </ul>
            {after && <button onClick={() => page("")}>First alert page</button>}
            {data.next_cursor && (
              <button onClick={() => page(data.next_cursor!)}>Next alert page</button>
            )}
            <button
              onClick={() => {
                setSelected("");
                read.reload();
              }}
            >
              Refresh alerts
            </button>
          </>
        )}
      </ReadState>
    </section>
  );
}
