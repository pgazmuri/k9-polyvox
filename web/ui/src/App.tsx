import { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { CameraPanel } from "@/components/CameraPanel";
import { PersonaPanel } from "@/components/PersonaPanel";
import { EventFeed } from "@/components/EventFeed";
import { CommandConsole } from "@/components/CommandConsole";
import { ActionCatalogTray } from "@/components/ActionCatalogTray";
import { RobotProvider, useRobotContext } from "@/context/RobotContext";
import { useEventStream } from "@/hooks/useEventStream";
import {
  fetchActionCatalog,
  fetchCameraStreamStatus,
  fetchLoopStatus,
  fetchPersonas,
  fetchState,
  fetchTimeline,
} from "@/lib/actions";
import { resolveCameraStreamUrl } from "@/lib/camera";
import type { TimelineEvent } from "@/lib/store";

function Dashboard() {
  const { setState, resetEvents, setCamera, setPersona, setCurrentAction, setLoops, setActions } = useRobotContext();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEventStream();

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      try {
        const [snapshot, timeline, cameraStatus, personaResult, loopStatus, actionCatalog] = await Promise.all([
          fetchState(),
          fetchTimeline(),
          fetchCameraStreamStatus().catch(() => null),
          fetchPersonas().catch(() => null),
          fetchLoopStatus().catch(() => null),
          fetchActionCatalog().catch(() => null),
        ]);
        if (cancelled) {
          return;
        }
        setState(snapshot ?? null);
        const currentAction = (snapshot?.meta as Record<string, unknown> | undefined)?.current_action;
        if (typeof currentAction === "string" && currentAction.length > 0) {
          setCurrentAction(currentAction);
        }
        resetEvents((timeline?.events ?? []) as TimelineEvent[]);
        if (cameraStatus) {
          const baseStatus = {
            enabled: Boolean(cameraStatus.enabled),
            frameRate: cameraStatus.frameRate ?? null,
            port: cameraStatus.port ?? null,
            path: cameraStatus.path ?? null,
            streamUrl: cameraStatus.streamUrl ?? null,
          };
          setCamera({
            ...baseStatus,
            streamUrl: resolveCameraStreamUrl(baseStatus),
          });
        }
        if (personaResult?.persona) {
          setPersona(personaResult.persona);
        }
        if (loopStatus && typeof loopStatus === "object") {
          const nextLoops: Partial<Record<"awareness" | "sensors", boolean>> = {};
          (["awareness", "sensors"] as const).forEach((key) => {
            const raw = (loopStatus as Record<string, unknown>)[key];
            if (typeof raw === "boolean") {
              nextLoops[key] = raw;
            }
          });
          if (Object.keys(nextLoops).length > 0) {
            setLoops(nextLoops);
          }
        }
        setActions(Array.isArray(actionCatalog?.actions) ? [...actionCatalog.actions] : []);
        setError(null);
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message ?? "Failed to load robot state");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [resetEvents, setState, setCamera, setPersona, setCurrentAction, setLoops, setActions]);

  return (
    <div className="relative mx-auto flex w-full max-w-[135rem] flex-col gap-6 px-6 pb-10 pt-6 lg:px-10 xl:px-12">
      <Header />
      <ActionCatalogTray />
      {error && (
        <div className="rounded-2xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      )}
      <div className="grid gap-6 xl:grid-cols-3">
        <div className="flex flex-col gap-6">
          <CameraPanel />
        </div>
        <div className="flex flex-col gap-6">
          <CommandConsole />
        </div>
        <div className="flex flex-col gap-6">
          <PersonaPanel />
        </div>
      </div>
      {loading && (
        <div className="text-center text-sm uppercase tracking-[0.3em] text-white/40">Synchronizing...</div>
      )}
      <EventFeed />
    </div>
  );
}

export default function App() {
  return (
    <RobotProvider>
      <main className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(94,80,255,0.2),_transparent_55%)] text-white">
        <Dashboard />
      </main>
    </RobotProvider>
  );
}
