import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";

export type Access = {
  project: string;
  role: string;
  token: string;
  user: string;
  onExpiry: () => void;
};
export const canInvestigate = (role: string) => role === "owner" || role === "analyst";
export const words = (value: string) => value.replaceAll("_", " ");
export const utc = (value: string) => new Date(value).toISOString().replace("T", " ").slice(0, 16);

type Result<T> = { key: string; data?: T; error?: string };
export function useProjectRead<T>(path: string, onExpiry: () => void) {
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<Result<T> | null>(null);
  const key = path + "#" + revision;
  useEffect(() => {
    const controller = new AbortController();
    async function read() {
      try {
        const res = await api(path, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (res.status === 401) {
          onExpiry();
          return;
        }
        if (!res.ok)
          throw new Error(
            res.status === 403 || res.status === 404
              ? "This record is unavailable or your access has changed."
              : "Could not load project data.",
          );
        const data: T = await res.json();
        if (!controller.signal.aborted) setResult({ key, data });
      } catch (err) {
        if (!controller.signal.aborted)
          setResult({
            key,
            error: err instanceof Error ? err.message : "Could not reach the API.",
          });
      }
    }
    void read();
    return () => controller.abort();
  }, [path, key, onExpiry]);
  return {
    data: result?.key === key ? result.data : undefined,
    error: result?.key === key ? result.error : undefined,
    reload: () => setRevision((n) => n + 1),
  };
}

export function ReadState<T>({
  read,
  children,
}: {
  read: ReturnType<typeof useProjectRead<T>>;
  children: (data: T) => ReactNode;
}) {
  if (read.error)
    return (
      <>
        <p role="alert">{read.error}</p>
        <button onClick={read.reload}>Retry loading</button>
      </>
    );
  if (read.data === undefined) return <p role="status">Loading project data…</p>;
  return <>{children(read.data)}</>;
}

export function useIncidentWrite(access: Access) {
  const active = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => () => active.current?.abort(), []);
  async function write(path: string, method: string, body: object) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setError("");
    let rejected = false;
    try {
      const response = await api(path, {
        method,
        signal: controller.signal,
        body: JSON.stringify(body),
        headers: { "Content-Type": "application/json", "X-CSRF-Token": access.token },
      });
      if (controller.signal.aborted) return;
      if (response.status === 401) {
        access.onExpiry();
        return;
      }
      if (!response.ok) {
        rejected = response.status >= 400 && response.status < 500;
        const detail = (await response.json().catch(() => null))?.detail;
        throw new Error(typeof detail === "string" ? detail : "Unable to save the change.");
      }
      const data: { id: string; version: number } = await response.json();
      if (!controller.signal.aborted) return data;
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : "Unable to confirm the change.");
        if (!rejected) return "uncertain" as const;
      }
    } finally {
      if (!controller.signal.aborted) {
        active.current = null;
        setBusy(false);
      }
    }
  }
  return { write, busy, error };
}
