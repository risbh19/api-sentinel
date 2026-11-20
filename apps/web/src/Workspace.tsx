import { AuditActivity } from "./AuditActivity";
import { api } from "./api";
import { useCallback, useEffect, useState, type FormEvent } from "react";

type Org = { id: string; name: string; role: string };
type Account = { email: string; organizations: Org[]; csrf_token: string };
type Project = { id: string; name: string; slug: string };

function Projects({ org, onExpiry }: { org: Org; onExpiry: () => void }) {
  const [items, setItems] = useState<Project[]>([]);
  const [cursor, setCursor] = useState("");
  const [more, setMore] = useState(false);
  const [phase, setPhase] = useState<"loading" | "done" | "error">("loading");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const query = cursor ? "?after_slug=" + encodeURIComponent(cursor) : "";
    void api("/organizations/" + org.id + "/projects" + query, { signal: controller.signal })
      .then(async (res) => {
        if (controller.signal.aborted) return;
        if (res.status === 401) { onExpiry(); return; }
        if (!res.ok) throw new Error();
        const rows: Project[] = await res.json();
        if (controller.signal.aborted) return;
        setItems((previous) => cursor ? [...previous, ...rows] : rows);
        setMore(rows.length === 50);
        setPhase("done");
      }).catch(() => {
        if (!controller.signal.aborted) {
          setItems([]);
          setMore(false);
          setPhase("error");
        }
      });
    return () => controller.abort();
  }, [org.id, cursor, retry, onExpiry]);

  return <section aria-labelledby="project-list">
    <div className="heading"><h2 id="project-list">Projects</h2><span>{org.role}</span></div>
    {items.length > 0 && <ul>{items.map((p) => <li key={p.id}>{p.name} <code>{p.slug}</code></li>)}</ul>}
    {phase === "loading" && <p role="status">Loading projects…</p>}
    {phase === "done" && !items.length && <p>This organization has no projects yet.</p>}
    {phase === "error" && <><p role="alert">Unable to load these projects.</p>
      <button onClick={() => { setCursor(""); setPhase("loading"); setRetry((v) => v + 1); }}>Retry</button></>}
    {phase === "done" && more && <button onClick={() => { setPhase("loading"); setCursor(items[items.length - 1].slug); }}>Load more</button>}
  </section>;
}

export function Workspace() {
  const [account, setAccount] = useState<Account | null>(null);
  const [orgId, setOrgId] = useState("");
  const [phase, setPhase] = useState<"checking" | "offline" | "ready">("checking");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const expire = useCallback(() => {
    setAccount(null); setOrgId(""); setError("Your session expired. Sign in again.");
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void api("/auth/me", { signal: controller.signal }).then(async (res) => {
      if (res.status !== 401 && !res.ok) throw new Error();
      const data: Account | null = res.ok ? await res.json() : null;
      if (!controller.signal.aborted) { setAccount(data); setPhase("ready"); }
    }).catch(() => { if (!controller.signal.aborted) setPhase("offline"); });
    return () => controller.abort();
  }, [retry]);

  async function signIn(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const fields = new FormData(form);
    setBusy(true); setError("");
    try {
      const res = await api("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: fields.get("email"), password: fields.get("password") }) });
      if (!res.ok) {
        setError(res.status === 429 ? "Too many attempts. Try again in a minute." :
          res.status === 401 ? "Email or password is incorrect." : "Sign-in failed. Check the service and try again.");
        return;
      }
      const data: Account = await res.json();
      form.reset(); setAccount(data);
    } catch { setError("Could not reach the sign-in service."); }
    finally { setBusy(false); }
  }

  async function signOut() {
    if (!account) return;
    setBusy(true); setError("");
    try {
      const res = await api("/auth/logout", { method: "POST", headers: { "X-CSRF-Token": account.csrf_token } });
      if (res.status === 403) {
        setAccount(null);
        setOrgId("");
        setPhase("checking");
        setError("Your session changed. Check the account and sign out again.");
        setRetry((value) => value + 1);
        return;
      }
      if (!res.ok && res.status !== 401) throw new Error();
      setAccount(null); setOrgId("");
    } catch { setError("Sign-out could not be confirmed. Please retry."); }
    finally { setBusy(false); }
  }
  const org = account?.organizations.find((o) => o.id === orgId) ?? account?.organizations[0];
  return <><header><span className="brand-mark" aria-hidden="true">S</span>API Sentinel <a href="#status">Service status</a></header>
    <main><h1>{account ? "Project workspace" : "Sign in"}</h1>
      {phase === "checking" && <p role="status">Checking your session…</p>}
      {phase === "offline" && <><p role="alert">Account service unavailable.</p><button onClick={() => { setPhase("checking"); setRetry((n) => n + 1); }}>Retry</button></>}
      {phase === "ready" && !account && <section><form onSubmit={signIn}>
        <label>Email<input name="email" type="email" autoComplete="username" maxLength={254} required /></label>
        <label>Password<input name="password" type="password" autoComplete="current-password" maxLength={256} required /></label>
        <button disabled={busy}>Sign in</button></form></section>}
      {account && <><div className="account"><span>{account.email}</span><button disabled={busy} onClick={signOut}>Sign out</button></div>
        {org ? <><label>Organization<select value={org.id} onChange={(e) => setOrgId(e.target.value)}>
          {account.organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
          <Projects key={org.id} org={org} onExpiry={expire} />
          {(org.role === "owner" || org.role === "analyst") && <AuditActivity key={"audit-" + org.id} orgId={org.id} onExpiry={expire} />}</> : <p>Ask an organization owner to add your account.</p>}</>}
      {error && <p role="alert">{error}</p>}
    </main></>;
}
