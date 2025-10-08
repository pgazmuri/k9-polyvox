import { ComponentType, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Camera,
  Clock,
  Compass,
  Gauge,
  Headphones,
  MapPin,
  Power,
  User,
  Zap,
} from "lucide-react";
import { useRobotContext } from "@/context/RobotContext";
import { updateCameraStream } from "@/lib/actions";
import { resolveCameraStreamUrl } from "@/lib/camera";

function formatRelative(timestamp: unknown): string {
  if (!timestamp) {
    return "never";
  }
  const value = Number(timestamp);
  if (!Number.isFinite(value)) {
    return "unknown";
  }
  const diff = Date.now() - value * 1000;
  if (Number.isNaN(diff)) {
    return "unknown";
  }
  const seconds = Math.max(0, Math.round(diff / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function resolvePath(snapshot: Record<string, unknown> | null, path: string): unknown {
  if (!snapshot) {
    return null;
  }
  return path.split(".").reduce<unknown>((acc: unknown, key) => {
    if (acc && typeof acc === "object" && key in acc) {
      return (acc as Record<string, unknown>)[key];
    }
    return null;
  }, snapshot);
}

function prettifyActionName(name: string): string {
  return name
    .replace(/[_\-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

interface MetricConfig {
  id: string;
  label: string;
  value: string;
  icon: ComponentType<{ className?: string }>;
  iconClass?: string;
  colSpanClass?: string;
}

const FALLBACK_IMAGE =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(`<?xml version="1.0" encoding="UTF-8"?>
<svg width="640" height="360" viewBox="0 0 640 360" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#5C5CFF" stop-opacity="0.6" />
      <stop offset="100%" stop-color="#2ED7C9" stop-opacity="0.4" />
    </linearGradient>
  </defs>
  <rect width="640" height="360" fill="#070A1B" />
  <rect width="640" height="360" fill="url(#grad)" opacity="0.65" />
  <g fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="1">
    <path d="M40 180h560M320 40v280" />
    <rect x="140" y="80" width="360" height="200" rx="32" ry="32" />
  </g>
  <g fill="rgba(255,255,255,0.7)" font-family="Inter, sans-serif" text-anchor="middle">
    <text x="320" y="180" font-size="24">Awaiting live frame</text>
  </g>
</svg>`);

export function CameraPanel() {
  const { state, camera, setCamera, currentAction } = useRobotContext();
  const [toggling, setToggling] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [streamError, setStreamError] = useState(false);
  const perception = (state?.perception ?? {}) as Record<string, unknown>;

  const streamUrl = useMemo(() => resolveCameraStreamUrl(camera), [camera]);

  useEffect(() => {
    setStreamError(false);
  }, [streamUrl]);

  const snapshotUrl = useMemo(() => {
    const candidates = [
      perception["latest_frame_url"],
      perception["latest_capture_url"],
      perception["last_snapshot_url"],
      perception["last_frame"],
    ];
    const match = candidates.find((val) => typeof val === "string" && val.length > 4);
    if (typeof match === "string") {
      return match;
    }
    return FALLBACK_IMAGE;
  }, [perception]);

  const hasSnapshot = snapshotUrl !== FALLBACK_IMAGE;
  const streaming = Boolean(streamUrl) && !streamError;

  const facePresent = Boolean(perception["face_present"]);
  const lastFaceSeen = formatRelative(perception["face_last_seen_at"]);
  const pendingStimulus = (state?.interaction as Record<string, unknown> | undefined)?.pending_stimulus as string | undefined;

  const metrics = useMemo<MetricConfig[]>(() => {
    const snapshot = (state ?? null) as Record<string, unknown> | null;
    const goalRaw = resolvePath(snapshot, "interaction.goal");
    const headPoseDescription = resolvePath(snapshot, "motion.head_pose_description");
    const headPoseFallback = resolvePath(snapshot, "motion.head_pose");
    const postureRaw = resolvePath(snapshot, "motion.posture");
    const volumeRaw = resolvePath(snapshot, "audio.volume");
    const historicalAction = resolvePath(snapshot, "meta.last_action");

    const goal = typeof goalRaw === "string" && goalRaw.trim().length > 0 ? goalRaw : "No goal set";
    const headPoseCandidate =
      typeof headPoseDescription === "string" && headPoseDescription.trim().length > 0
        ? headPoseDescription
        : typeof headPoseFallback === "string" && headPoseFallback.trim().length > 0
          ? headPoseFallback
          : "Neutral";
    const posture = typeof postureRaw === "string" && postureRaw.trim().length > 0 ? postureRaw : "Unknown";
    const volumeValue = Number(volumeRaw);
    const volume = Number.isFinite(volumeValue) && volumeValue >= 0 ? `${Math.round(Math.min(volumeValue, 1) * 100)}%` : "—";

    const actionLabel =
      typeof currentAction === "string" && currentAction.trim().length > 0
        ? prettifyActionName(currentAction)
        : typeof historicalAction === "string" && historicalAction.trim().length > 0
          ? prettifyActionName(historicalAction)
          : "None yet";

    return [
      { id: "last-face", label: "Last face seen", value: lastFaceSeen, icon: Clock, iconClass: "text-aurora" },
      { id: "stimulus", label: "Stimulus", value: pendingStimulus || "Idle", icon: User, iconClass: "text-pulse" },
      { id: "last-action", label: "Last action", value: actionLabel, icon: Zap, iconClass: "text-aurora" },
      {
        id: "tracking",
        label: "Tracking face",
        value: facePresent ? "Yes" : "No",
        icon: Activity,
        iconClass: facePresent ? "text-aurora" : "text-white/50",
      },
      { id: "posture", label: "Posture", value: posture, icon: Compass, iconClass: "text-white/70" },
      { id: "volume", label: "Volume", value: volume, icon: Headphones, iconClass: "text-white/70" },
      {
        id: "goal",
        label: "Goal",
        value: goal,
        icon: MapPin,
        iconClass: "text-white/80",
        colSpanClass: "sm:col-span-2 xl:col-span-3",
      },
      {
        id: "head-pose",
        label: "Head pose",
        value: headPoseCandidate,
        icon: Gauge,
        iconClass: "text-white/80",
        colSpanClass: "sm:col-span-2 xl:col-span-3",
      },
    ];
  }, [state, currentAction, lastFaceSeen, pendingStimulus, facePresent]);

  const handleToggle = async () => {
    if (toggling) {
      return;
    }
    setToggling(true);
    setFeedback(null);
    const nextEnabled = !(camera?.enabled ?? false);
    try {
      const status = await updateCameraStream({ enabled: nextEnabled });
      const updated = {
        enabled: Boolean(status.enabled),
        frameRate: status.frameRate ?? null,
        port: status.port ?? null,
        path: status.path ?? null,
        streamUrl: null,
      } as const;
      setCamera({
        ...updated,
        streamUrl: resolveCameraStreamUrl({ ...updated, streamUrl: null }),
      });
      setFeedback(status.enabled ? "Live stream enabled" : "Live stream disabled");
    } catch (error) {
      console.error(error);
      setFeedback("Failed to toggle camera stream");
    } finally {
      setToggling(false);
    }
  };

  return (
    <div className="group relative overflow-hidden rounded-3xl border border-white/5 bg-gradient-to-br from-white/10 via-white/5 to-white/0 p-6 shadow-glow">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(94,80,255,0.35),transparent_55%)] opacity-70" />
      <div className="relative flex flex-col gap-5">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold tracking-tight text-white">Status</h2>
            <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs font-medium uppercase tracking-wide text-white/80">
              <Camera size={14} />
              Live feed
            </span>
          </div>
          <div className="flex flex-col items-end gap-2 text-right text-xs">
            <button
              type="button"
              onClick={handleToggle}
              disabled={toggling}
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 font-semibold transition ${
                camera?.enabled
                  ? "border-aurora/50 bg-aurora/10 text-aurora"
                  : "border-white/15 bg-white/5 text-white/60"
              } ${toggling ? "opacity-70" : "hover:border-aurora/60 hover:text-aurora"}`}
            >
              <Power className="h-3.5 w-3.5" />
              {camera?.enabled ? "Disable stream" : "Enable stream"}
            </button>
            <span className={`font-medium ${facePresent ? "text-aurora" : "text-white/50"}`}>
              {facePresent ? "Face detected" : "No face detected"}
            </span>
          </div>
        </header>
        <div className="flex justify-center">
          <div
            className="relative w-full max-w-[28rem] overflow-hidden rounded-2xl border border-white/10"
          >
            {streaming ? (
              <img
                key={streamUrl ?? "stream"}
                src={streamUrl ?? undefined}
                alt="Live camera feed"
                className="h-full w-full select-none object-cover transition duration-500 group-hover:scale-[1.02]"
                onError={() => setStreamError(true)}
              />
            ) : (
              <img
                src={snapshotUrl}
                alt="Latest camera frame"
                className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.02]"
              />
            )}
            {!streaming && !hasSnapshot && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/60 text-sm text-white/70">
                Live video stream not available
              </div>
            )}
          </div>
        </div>
        {feedback && <div className="text-xs text-white/60">{feedback}</div>}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {metrics.map((metric) => (
            <MetricCard key={metric.id} {...metric} />
          ))}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, iconClass, colSpanClass }: MetricConfig) {
  return (
    <div
      className={`flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm ${
        colSpanClass ?? ""
      }`}
    >
      <span className={`rounded-full border border-white/5 bg-white/10 p-2 ${iconClass ?? "text-white/70"}`}>
        <Icon className="h-4 w-4" />
      </span>
      <div className="flex flex-col leading-tight">
        <span className="text-xs uppercase tracking-wide text-white/40">{label}</span>
        <span className="font-medium text-white/80 break-words">{value}</span>
      </div>
    </div>
  );
}
