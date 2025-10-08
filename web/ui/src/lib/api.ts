const API_BASE = import.meta.env.VITE_API_BASE?.replace(/\/$/, "") || "";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (API_TOKEN) {
    headers.set("x-api-key", API_TOKEN);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function getWebSocketUrl(): string {
  const explicit = import.meta.env.VITE_WS_URL;
  const base = explicit || `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;
  const tokenParam = API_TOKEN ? `?token=${encodeURIComponent(API_TOKEN)}` : "";
  return `${base.replace(/\/$/, "")}/ws/events${tokenParam}`;
}
