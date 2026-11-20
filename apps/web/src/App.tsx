import { useEffect, useState } from "react";
import { readReadiness, type Availability } from "./health";

const results = {
  checking: ["Checking readiness", "Waiting for a response from the local API."],
  ready: ["Ready", "The API reached PostgreSQL and completed its readiness query."],
  unavailable: ["Database unavailable", "The API responded. Check the database service and its connection settings."],
  unreachable: ["Readiness unknown", "The readiness check could not complete. Check the API and web services, then retry."],
} as const;

export function App() {
  const [status, setStatus] = useState<Availability | "checking">("checking");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 6000);
    void readReadiness(controller.signal).then((result) => {
      window.clearTimeout(timeout);
      if (active) setStatus(result);
    });
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  return (
    <>
      <header><span className="brand-mark" aria-hidden="true">S</span>API Sentinel</header>
      <main>
        <h1>Service status</h1>
        <section aria-labelledby="readiness">
          <div className="heading"><h2 id="readiness">API readiness</h2><code>GET /health/ready</code></div>
          <div role="status" className="result" data-status={status}>
            <strong><i aria-hidden="true" />{results[status][0]}</strong>
            <p>{results[status][1]}</p>
          </div>
          <button disabled={status === "checking"} onClick={() => {
            setStatus("checking");
            setAttempt((previous) => previous + 1);
          }}>Check again</button>
        </section>
        <aside><h2>Monitoring workspace</h2><p><a href="#workspace">Open your project workspace</a></p></aside>
      </main>
    </>
  );
}
