import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, History } from "lucide-react";
import { TimelineEvent } from "@/lib/store";
import { useRobotContext } from "@/context/RobotContext";

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatType(type: string): string {
  return type.replace(/\./g, " › ");
}

function renderPayload(payload: Record<string, unknown>): string {
  const entries = Object.entries(payload ?? {});
  if (!entries.length) {
    return "No metadata";
  }
  return entries
    .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`)
    .join(" · ");
}

export function EventFeed() {
  const { events } = useRobotContext();
  const latestEvents = useMemo(() => [...events].reverse(), [events]) as TimelineEvent[];
  const [open, setOpen] = useState(false);
  const mobileEvents = latestEvents.slice(0, 8);
  const desktopEvents = latestEvents.slice(0, 25);

  return (
    <>
      <div className="space-y-3 rounded-3xl border border-white/5 bg-white/10 p-5 shadow-glow lg:hidden">
        <header className="flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight text-white">Event stream</h2>
          <span className="text-xs uppercase tracking-[0.2em] text-white/40">{events.length} total</span>
        </header>
        <div className="space-y-3">
          {mobileEvents.map((event) => (
            <div key={event.id} className="rounded-2xl border border-white/10 bg-white/5 p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium text-white/80">{formatType(event.type)}</span>
                <span className="text-xs text-white/40">{formatTimestamp(event.timestamp)}</span>
              </div>
              <p className="mt-2 text-xs text-white/60">{renderPayload(event.payload)}</p>
            </div>
          ))}
          {!mobileEvents.length && (
            <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-6 text-center text-sm text-white/50">
              Waiting for events to roll in.
            </div>
          )}
        </div>
      </div>

      <div className="pointer-events-none fixed bottom-10 right-6 z-40 hidden lg:flex flex-col items-end justify-end sm:right-10">
        <div className="pointer-events-auto flex flex-col items-end gap-4">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/40 px-4 py-2 text-xs font-semibold uppercase tracking-[0.25em] text-white/60 transition hover:border-white/30 hover:text-white"
          >
            <History className="h-4 w-4 text-aurora" />
            Stream
            {open ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>

          <AnimatePresence>
            {open && (
              <motion.aside
                key="event-feed"
                initial={{ x: 380, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: 380, opacity: 0 }}
                transition={{ type: "spring", stiffness: 320, damping: 32 }}
                className="w-[360px] max-h-[75vh] overflow-hidden rounded-3xl border border-white/10 bg-[#0B0F1F]/95 p-5 shadow-2xl ring-1 ring-white/10 backdrop-blur pointer-events-auto"
                aria-hidden={!open}
              >
                <div className="flex items-center justify-between border-b border-white/5 pb-3">
                  <div className="flex items-center gap-2 text-sm font-semibold text-white">
                    <History className="h-4 w-4 text-aurora" />
                    Event stream
                  </div>
                  <span className="text-xs uppercase tracking-[0.25em] text-white/40">Latest {desktopEvents.length}</span>
                </div>
                <div className="mt-4 space-y-3 overflow-y-auto pr-1 text-sm">
                  {desktopEvents.map((event) => (
                    <div
                      key={event.id}
                      className="rounded-2xl border border-white/10 bg-white/5 p-3 shadow-sm transition hover:border-white/20"
                    >
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-white/80">{formatType(event.type)}</span>
                        <span className="text-white/40">{formatTimestamp(event.timestamp)}</span>
                      </div>
                      <p className="mt-2 text-xs leading-relaxed text-white/60">{renderPayload(event.payload)}</p>
                    </div>
                  ))}
                  {!desktopEvents.length && (
                    <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-6 text-center text-xs text-white/50">
                      Waiting for events to roll in.
                    </div>
                  )}
                </div>
              </motion.aside>
            )}
          </AnimatePresence>
        </div>
      </div>
    </>
  );
}
