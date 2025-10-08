import { useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Activity, Brain, Power, Radio, ToggleLeft, ToggleRight } from "lucide-react";
import { ReactNode } from "react";
import { useRobotContext } from "@/context/RobotContext";
import { requestShutdown, updateLoops } from "@/lib/actions";

type LoopKey = "awareness" | "sensors";

const LOOP_LABELS: Record<LoopKey, string> = {
  awareness: "Wake Randomly",
  sensors: "Wake on Sensor",
};

export function Header() {
  const { loops, persona, setLoops } = useRobotContext();
  const [busyLoop, setBusyLoop] = useState<LoopKey | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [shutdownPending, setShutdownPending] = useState(false);

  const loopStates = useMemo(() => ["awareness", "sensors"] as const, []);

  const handleToggle = async (loop: LoopKey) => {
    if (busyLoop) {
      return;
    }
    setBusyLoop(loop);
    try {
      const nextValue = !loops[loop];
      const response = await updateLoops({ [loop]: nextValue });
      const resolved = response.loops ?? {};
      const value = loop in resolved ? Boolean(resolved[loop]) : nextValue;
      setLoops({ [loop]: value });
      setFeedback(`${LOOP_LABELS[loop]} ${value ? "enabled" : "paused"}`);
    } catch (error) {
      console.error(error);
      setFeedback(`Failed to update ${LOOP_LABELS[loop]}`);
    } finally {
      setBusyLoop(null);
    }
  };

  const handleShutdown = async () => {
    if (shutdownPending) {
      return;
    }
    setShutdownPending(true);
    try {
      const response = await requestShutdown();
      setFeedback(response.status === "shutting_down" ? "Shutdown initiated" : "Shutdown requested");
    } catch (error) {
      console.error(error);
      setFeedback("Failed to request shutdown");
    } finally {
      setShutdownPending(false);
    }
  };

  return (
    <div className="flex flex-col gap-5 rounded-3xl border border-white/5 bg-white/10 p-6 shadow-glow backdrop-blur-xl lg:flex-row lg:items-start lg:justify-between">
      <div className="flex flex-col gap-2">
        <motion.h1
          className="text-3xl font-semibold tracking-tight"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
        >
          k9-polyvox Control Center
        </motion.h1>
        <motion.p
          className="text-sm text-white/60"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
        >
          Live awareness. Instant reactions. Manual override at your fingertips.
        </motion.p>
      </div>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap justify-end gap-2">
          {loopStates.map((loop) => {
            const active = loops[loop];
            return (
              <LoopToggle
                key={loop}
                label={LOOP_LABELS[loop]}
                active={active}
                busy={busyLoop === loop}
                onClick={() => handleToggle(loop)}
              />
            );
          })}
          <button
            type="button"
            onClick={handleShutdown}
            disabled={shutdownPending}
            className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition ${
              shutdownPending
                ? "border-red-500/60 bg-red-500/10 text-red-200 opacity-80"
                : "border-red-500/40 bg-red-500/10 text-red-200 hover:border-red-400 hover:text-red-100"
            }`}
            aria-label="Initiate shutdown"
          >
            <Power className="h-4 w-4" />
            Shutdown
          </button>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3">
          <StatusPill
            icon={<Activity className="h-4 w-4" />}
            label="Sensors"
            active={loops.sensors}
            activeText="Tracking"
            inactiveText="Paused"
          />
          <StatusPill
            icon={<Brain className="h-4 w-4" />}
            label="Awareness"
            active={loops.awareness}
            activeText="Engaged"
            inactiveText="Idle"
          />
          <StatusPill
            icon={<Radio className="h-4 w-4" />}
            label="Link"
            active
            activeText="Live"
            inactiveText="Offline"
          />
          <div className="hidden items-center gap-3 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/70 lg:flex">
            <span className="text-xs uppercase tracking-wide text-white/40">Persona</span>
            <span className="font-medium text-white/80">{persona.selected ?? "Loading"}</span>
          </div>
        </div>
        <AnimatePresence mode="wait">
          {feedback && (
            <motion.span
              key={feedback}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2 }}
              className="text-right text-xs text-white/60"
            >
              {feedback}
            </motion.span>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

interface StatusPillProps {
  icon: ReactNode;
  label: string;
  active: boolean;
  activeText: string;
  inactiveText: string;
}

interface LoopToggleProps {
  label: string;
  active: boolean;
  busy: boolean;
  onClick: () => void;
}

function LoopToggle({ label, active, busy, onClick }: LoopToggleProps) {
  const Icon = active ? ToggleRight : ToggleLeft;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold transition ${
        active ? "border-aurora/60 bg-aurora/10 text-aurora" : "border-white/10 bg-white/5 text-white/60"
      } ${busy ? "opacity-70" : "hover:border-aurora/60 hover:text-aurora"}`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}

function StatusPill({ icon, label, active, activeText, inactiveText }: StatusPillProps) {
  return (
    <div className={`flex items-center gap-3 rounded-full border px-4 py-2 text-sm shadow-sm transition-colors ${
      active ? "border-aurora/50 bg-aurora/10 text-aurora" : "border-white/10 bg-white/5 text-white/60"
    }`}>
      <span className="text-white/70">{icon}</span>
      <div className="flex flex-col leading-tight">
        <span className="text-xs uppercase tracking-wide text-white/40">{label}</span>
        <span className="font-medium">{active ? activeText : inactiveText}</span>
      </div>
    </div>
  );
}
