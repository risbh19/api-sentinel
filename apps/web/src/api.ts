export async function api(path: string, options?: RequestInit) {
  return fetch("/api/v1" + path, { cache: "no-store", credentials: "same-origin", ...options });
}
