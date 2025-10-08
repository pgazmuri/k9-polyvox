import { useEffect, useRef } from "react";
import { getWebSocketUrl } from "@/lib/api";
import { PersonaState, TimelineEvent } from "@/lib/store";
import { resolveCameraStreamUrl } from "@/lib/camera";
import { useRobotContext } from "@/context/RobotContext";

const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 10000;

export function useEventStream() {
  const reconnectDelay = useRef(RECONNECT_BASE_DELAY);
  const wsRef = useRef<WebSocket | null>(null);
  const { pushEvent, setState, setLoops, setCamera, setCurrentAction, setPersona, camera, persona } = useRobotContext();

  const cameraRef = useRef(camera);
  const personaRef = useRef(persona);

  useEffect(() => {
    cameraRef.current = camera;
  }, [camera]);

  useEffect(() => {
    personaRef.current = persona;
  }, [persona]);

  useEffect(() => {
    let cancelled = false;

    const connect = () => {
      const url = getWebSocketUrl();
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.addEventListener("open", () => {
        reconnectDelay.current = RECONNECT_BASE_DELAY;
      });

      ws.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data) as TimelineEvent & { type: string };
          const cameraState = cameraRef.current;
          const personaState = personaRef.current;
          if (payload.type === "state.diff") {
            const stateData = (payload.payload?.state as Record<string, unknown>) || null;
            setState(stateData);
            const currentAction = (stateData?.meta as Record<string, unknown> | undefined)?.current_action;
            if (typeof currentAction === "string" && currentAction.length > 0) {
              setCurrentAction(currentAction);
            } else if (currentAction === null) {
              setCurrentAction(null);
            }
          } else if (payload.type === "loop.status") {
            const loops = payload.payload as Record<string, unknown>;
            const loopName = loops?.loop as string | undefined;
            const enabled = Boolean(loops?.enabled ?? true);
            if (loopName === "awareness" || loopName === "sensors") {
              setLoops({ [loopName]: enabled });
            }
          } else if (payload.type === "command.action.started") {
            const actionName = payload.payload?.name;
            if (typeof actionName === "string") {
              setCurrentAction(actionName);
            }
          } else if (payload.type === "command.action.completed" || payload.type === "command.action.failed") {
            setCurrentAction(null);
          } else if (payload.type === "camera.web_stream.updated") {
            const enabled = Boolean(payload.payload?.enabled);
            const rawFrameRate = payload.payload?.frame_rate as unknown;
            const rawPort = payload.payload?.port as unknown;
            const rawPath = payload.payload?.path as unknown;

            let frameRate: number | null = null;
            if (typeof rawFrameRate === "number" && Number.isFinite(rawFrameRate)) {
              frameRate = rawFrameRate;
            } else if (typeof cameraState?.frameRate === "number") {
              frameRate = cameraState.frameRate;
            }

            let resolvedPort: number | null = null;
            if (typeof rawPort === "number" && Number.isFinite(rawPort)) {
              resolvedPort = rawPort;
            } else if (typeof rawPort === "string") {
              const parsed = Number.parseInt(rawPort, 10);
              if (!Number.isNaN(parsed)) {
                resolvedPort = parsed;
              }
            } else if (typeof cameraState?.port === "number") {
              resolvedPort = cameraState.port;
            }

            const path = typeof rawPath === "string" ? rawPath : cameraState?.path ?? null;
            const baseStatus = {
              enabled,
              frameRate,
              port: resolvedPort,
              path,
              streamUrl: cameraState?.streamUrl ?? null,
            };
            const next = {
              ...baseStatus,
              streamUrl: enabled ? resolveCameraStreamUrl(baseStatus) : null,
            };
            setCamera(next);
          } else if (payload.type === "persona.switch.completed") {
            const rawName = payload.payload?.name;
            const nextName = typeof rawName === "string" ? rawName : personaState.selected ?? undefined;
            let nextCurrent = personaState.current ?? null;
            if (typeof nextName === "string") {
              const payloadDetails = (payload.payload ?? {}) as Record<string, unknown>;
              nextCurrent = {
                ...(personaState.current && personaState.current.name === nextName ? personaState.current : { name: nextName }),
                ...payloadDetails,
                name: nextName,
              } as PersonaState["current"];
            }

            const list = personaState.list.some((entry) => entry.name === nextCurrent?.name)
              ? personaState.list.map((entry) =>
                  entry.name === nextCurrent?.name ? { ...entry, ...payload.payload } : entry,
                )
              : nextCurrent
                ? [...personaState.list, nextCurrent]
                : personaState.list;
            setPersona({
              list,
              current: nextCurrent ?? personaState.current,
              selected: nextCurrent?.name ?? personaState.selected,
            });
          } else if (payload.type === "interaction.goal.updated") {
            const goal = payload.payload?.goal;
            if (personaState.current && typeof goal === "string") {
              setPersona({
                list: personaState.list,
                current: { ...personaState.current, default_motivation: goal },
                selected: personaState.selected,
              });
            }
          } else if (payload.type === "persona.prompt.updated") {
            const personaName = payload.payload?.persona;
            const promptText = payload.payload?.prompt;
            if (typeof personaName === "string" && typeof promptText === "string") {
              const voicePayload = payload.payload?.voice;
              const motivationPayload = payload.payload?.default_motivation;
              const imagePromptPayload = payload.payload?.image_prompt;

              const mergeUpdates = <T extends { name: string }>(entry: T): T => {
                const updates: Record<string, unknown> = { prompt: promptText };
                if (voicePayload === null) {
                  updates.voice = undefined;
                } else if (typeof voicePayload === "string") {
                  updates.voice = voicePayload;
                }
                if (motivationPayload === null) {
                  updates.default_motivation = undefined;
                } else if (typeof motivationPayload === "string") {
                  updates.default_motivation = motivationPayload;
                }
                if (imagePromptPayload === null) {
                  updates.image_prompt = undefined;
                } else if (typeof imagePromptPayload === "string") {
                  updates.image_prompt = imagePromptPayload;
                }
                return { ...entry, ...updates } as T;
              };

              const list = personaState.list.map((entry) =>
                entry.name === personaName ? mergeUpdates(entry) : entry,
              );
              const current =
                personaState.current && personaState.current.name === personaName
                  ? mergeUpdates(personaState.current)
                  : personaState.current;

              setPersona({
                list,
                current,
                selected: personaState.selected,
              });
            }
          } else {
            pushEvent(payload);
          }
        } catch (err) {
          console.warn("Failed to parse event", err);
        }
      });

      ws.addEventListener("close", () => {
        if (cancelled) {
          return;
        }
        const nextDelay = Math.min(RECONNECT_MAX_DELAY, reconnectDelay.current * 1.8);
        reconnectDelay.current = nextDelay;
        setTimeout(() => {
          if (!cancelled) {
            connect();
          }
        }, reconnectDelay.current);
      });

      ws.addEventListener("error", () => {
        ws.close();
      });
    };

    connect();

    return () => {
      cancelled = true;
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [pushEvent, setState, setLoops, setCamera, setCurrentAction, setPersona]);
}
