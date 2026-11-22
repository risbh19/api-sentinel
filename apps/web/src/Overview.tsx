import { useState } from "react";
import { ReadState, useProjectRead, utc, type Access } from "./projectData";

type Totals = {
  since: string;
  until: string;
  events: number;
  open_alerts: number;
  active_incidents: number;
  buckets: { start: string; events: number }[];
};

export function Overview({ access }: { access: Access }) {
  const [window, setWindow] = useState("24h");
  const read = useProjectRead<Totals>(
    "/projects/" + access.project + "/metrics/overview?window=" + window,
    access.onExpiry,
  );
  return (
    <section className="dashboard" aria-label="Project overview">
      <div className="heading">
        <h2>Project overview</h2>
        <label>
          Event window
          <select value={window} onChange={(e) => setWindow(e.target.value)}>
            <option value="24h">Last 24 hours</option>
            <option value="7d">Last 7 days</option>
          </select>
        </label>
      </div>
      <ReadState read={read}>
        {(data) => (
          <>
            <dl className="metric-grid">
              <div><dt>Events in window</dt><dd>{data.events}</dd></div>
              <div><dt>Currently open alerts</dt><dd>{data.open_alerts}</dd></div>
              <div><dt>Currently active incidents</dt><dd>{data.active_incidents}</dd></div>
            </dl>
            <p>Resolving an incident leaves its linked alerts open.</p>
            <h3>Event volume</h3>
            <p>
              {utc(data.since)} – {utc(data.until)} UTC · by occurrence time
            </p>
            {data.events === 0 ? (
              <p>No events occurred in this window.</p>
            ) : (
              <table className="volume-chart">
                <caption className="sr-only">Security event count by UTC interval</caption>
                <thead>
                  <tr>
                    <th scope="col">Interval start (UTC)</th>
                    <th scope="col">Events</th>
                  </tr>
                </thead>
                <tbody>
                  {data.buckets.map((b) => (
                    <tr key={b.start}>
                      <th scope="row">{utc(b.start)}</th>
                      <td>
                        <meter
                          aria-label={"Events from " + utc(b.start) + " UTC"}
                          min={0}
                          max={Math.max(1, ...data.buckets.map((x) => x.events))}
                          value={b.events}
                          title={b.events + " events"}
                        />
                        {b.events}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <button onClick={read.reload}>Refresh overview</button>
          </>
        )}
      </ReadState>
    </section>
  );
}
