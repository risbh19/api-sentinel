import { Alerts } from "./Alerts";
import { Overview } from "./Overview";
import { Incidents } from "./Incidents";
import { Integrations } from "./Integrations";
import { Inventory } from "./Inventory";
import { Events } from "./Events";
import { AuditActivity } from "./AuditActivity";
import { api } from "./api";
import { useCallback, useEffect, useState, type FormEvent } from "react";

type Org = { id: string; name: string; role: string };
type Account = { id: string; email: string; organizations: Org[]; csrf_token: string };
type Project = { id: string; name: string; slug: string };

function Projects({ org, token, user, onExpiry }: { org: Org; token: string; user: string; onExpiry: () => void }) {
  const [selected, setSelected] = useState("");
  const [tab, setTab] = useState("Overview");
  const [fromAlert, setFromAlert] = useState("");
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

  const project = items.find(p => p.id === selected) ?? items[0];
  function navigate(view: string) { setFromAlert(""); setTab(view); }
  const access = project && { project:project.id, role:org.role, token, user, onExpiry };
  return <section aria-labelledby="project-list" className="project-panel">
    <div className="heading"><h2 id="project-list">Projects</h2><span>{org.role}</span></div>
    {project && access && <>
      <label>Project<select value={project.id} onChange={e=>{setSelected(e.target.value);navigate("Overview");}}>
        {items.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      <nav aria-label="Project views">{["Overview","Inventory","Events","Alerts","Incidents",...(org.role === "viewer" ? [] : ["Integrations"])].map(view=>
        <button key={view} aria-label={view+" for "+project.name} aria-current={view===tab ? "page" : undefined} onClick={()=>navigate(view)}>{view}</button>)}</nav>
      <div key={project.id} className="project-view">
        {tab === "Overview" && <Overview access={access}/>}
        {tab === "Alerts" && <Alerts access={access} promote={id=>{setFromAlert(id);setTab("Incidents");}}/>}
        {tab === "Incidents" && <Incidents access={access} fromAlert={fromAlert}/>}
        {tab === "Events" && <Events project={project.id} detailed={org.role !== "viewer"} onExpiry={onExpiry}/>}
        {tab === "Integrations" && <Integrations project={project.id} writable={org.role === "owner" || org.role === "developer"} csrf={token} onExpiry={onExpiry}/>}
        {tab === "Inventory" && <Inventory project={project.id} writable={org.role !== "viewer"} token={token} onExpiry={onExpiry}/>}
      </div>
    </>}
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
          <Projects key={org.id} org={org} token={account.csrf_token} user={account.id} onExpiry={expire} />
          {(org.role === "owner" || org.role === "analyst") && <AuditActivity key={"audit-" + org.id} orgId={org.id} onExpiry={expire} />}</> : <p>Ask an organization owner to add your account.</p>}</>}
      {error && <p role="alert">{error}</p>}
    </main></>;
}
