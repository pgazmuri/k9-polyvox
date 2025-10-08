import { CameraStreamStatus } from "@/lib/store";

function normalizePath(path?: string | null): string {
  if (!path) {
    return "/mjpg";
  }
  return path.startsWith("/") ? path : `/${path}`;
}

function normalizePort(port?: number | null): number | null {
  if (typeof port === "number" && Number.isFinite(port) && port > 0) {
    return port;
  }
  return null;
}

export function resolveCameraStreamUrl(status: CameraStreamStatus | null): string | null {
  if (!status || !status.enabled) {
    return null;
  }
  if (status.streamUrl) {
    return status.streamUrl;
  }
  if (typeof window === "undefined") {
    return null;
  }

  const port = normalizePort(status.port) ?? null;
  const path = normalizePath(status.path ?? null);

  try {
    const url = new URL(window.location.href);
    const protocol = (() => {
      if (port === 443) {
        return "https:";
      }
      if (port === 80) {
        return "http:";
      }
      if (port) {
        return "http:";
      }
      return window.location.protocol === "https:" ? "https:" : "http:";
    })();

    url.protocol = protocol;
    url.pathname = path;
    url.search = "";

    if (port && !((protocol === "https:" && port === 443) || (protocol === "http:" && port === 80))) {
      url.port = String(port);
    } else {
      url.port = "";
    }

    return url.toString();
  } catch (error) {
    console.warn("Failed to resolve camera stream URL", error);
    return null;
  }
}
