export type Availability = "ready" | "unavailable" | "unreachable";

export async function readReadiness(signal: AbortSignal): Promise<Availability> {
  try {
    const response = await fetch("/health/ready", {
      signal, cache: "no-store", credentials: "omit", redirect: "error",
    });
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "status" in body) {
      if (response.status === 200 && body.status === "ready") return "ready";
      if (response.status === 503 && body.status === "unavailable") return "unavailable";
    }
  } catch {
    // An absent proxy, invalid JSON and a timed-out probe are all inconclusive.
  }
  return "unreachable";
}
