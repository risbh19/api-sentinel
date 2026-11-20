import { useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { Workspace } from "./Workspace";
import "./style.css";

function subscribe(listener: () => void) {
  window.addEventListener("hashchange", listener);
  return () => window.removeEventListener("hashchange", listener);
}

function Shell() {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash);
  return hash === "#workspace" ? <Workspace /> : <App />;
}

createRoot(document.getElementById("root")!).render(<Shell />);
