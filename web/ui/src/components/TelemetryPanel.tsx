import type { ComponentType } from "react";
import { Compass, Gauge, Headphones, MapPin, User, Zap } from "lucide-react";
import { useRobotContext } from "@/context/RobotContext";

type IconComponent = ComponentType<{ className?: string }>;

const ROWS: Array<{ label: string; accessor: string; icon: IconComponent; format?: (value: unknown) => string }> = [
  {
    label: "Last Action",
    accessor: "meta.last_action",
    icon: Zap,
    format: (value) => (typeof value === "string" && value.length > 0 ? value : "None yet"),
  },
  { label: "Goal", accessor: "interaction.goal", icon: MapPin },
  {
    label: "Tracking Face",
    accessor: "perception.face_present",
    icon: User,
    format: (value) => (value === true ? "Yes" : "No"),
  },
  { label: "Head Pose", accessor: "motion.head_pose_description", icon: Gauge },
  { label: "Posture", accessor: "motion.posture", icon: Compass },
  {
    label: "Volume",
    accessor: "audio.volume",
    icon: Headphones,
    format: (value) => `${Math.round(Number(value ?? 0) * 100)}%`,
  },
];

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

export function TelemetryPanel() {
  const { state, currentAction } = useRobotContext();

  return (
  <div className="space-y-4 rounded-3xl border border-white/5 bg-white/10 p-5 shadow-glow">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight text-white">Vitals</h2>
        <span className="text-xs uppercase tracking-[0.2em] text-white/40">Live snapshot</span>
      </header>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {ROWS.map((row) => {
          const Icon = row.icon;
          let value = resolvePath(state as Record<string, unknown> | null, row.accessor);
          if (row.accessor === "meta.current_action") {
            value = currentAction ?? value;
          }
          const display = row.format ? row.format(value) : String(value ?? "—");
          return (
            <div
              key={row.accessor}
              className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm"
            >
              <span className="rounded-full border border-white/5 bg-white/10 p-2 text-pulse">
                <Icon className="h-4 w-4" />
              </span>
              <div className="flex flex-col">
                <span className="text-xs uppercase tracking-wide text-white/40">{row.label}</span>
                <span className="font-medium text-white/80">{display}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
