import { apiFetch } from "@/lib/api";
import { CameraStreamStatus, PersonaState, PersonaSummary } from "@/lib/store";

export interface TriggerActionRequest {
  name: string;
  origin?: string;
}

export async function triggerAction(request: TriggerActionRequest) {
  return apiFetch<{ status: string; details?: unknown }>("/api/actions/trigger", {
    method: "POST",
    body: JSON.stringify({ ...request, origin: request.origin ?? "web-ui" }),
  });
}

export async function fetchActionCatalog() {
  return apiFetch<{ actions: string[] }>("/api/actions/catalog");
}

export async function sendAwarenessMessage(message: string, origin = "web-ui") {
  return apiFetch<{ status: string }>("/api/awareness/custom", {
    method: "POST",
    body: JSON.stringify({ message, origin }),
  });
}

export async function updateLoops(loops: { awareness?: boolean; sensors?: boolean }) {
  return apiFetch<{ loops: Record<string, boolean> }>("/api/loops", {
    method: "POST",
    body: JSON.stringify(loops),
  });
}

export async function fetchLoopStatus() {
  return apiFetch<Record<string, boolean>>("/api/loops");
}

export interface TimelineResponse {
  events: Array<{
    id: string;
    type: string;
    timestamp: string;
    payload: Record<string, unknown>;
    meta?: Record<string, unknown>;
  }>;
}

export async function fetchTimeline() {
  return apiFetch<TimelineResponse>("/api/actions/history");
}

export async function fetchState() {
  return apiFetch<Record<string, unknown> | null>("/api/state");
}

export async function fetchCameraStreamStatus() {
  return apiFetch<CameraStreamStatus>("/api/camera/web-stream");
}

export interface UpdateCameraStreamPayload {
  enabled: boolean;
  frameRate?: number;
  origin?: string;
}

export async function updateCameraStream(payload: UpdateCameraStreamPayload) {
  return apiFetch<CameraStreamStatus>(
    "/api/camera/web-stream",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

interface PersonaCatalogResponse {
  personas: PersonaSummary[];
  current: PersonaSummary | null;
  selected: string | null;
  goal?: string;
}

export async function fetchPersonas() {
  const response = await apiFetch<PersonaCatalogResponse>("/api/personas");
  const personaState: PersonaState = {
    list: response.personas ?? [],
    current: response.current ?? null,
    selected: response.selected ?? (response.current?.name ?? null),
  };
  return {
    persona: personaState,
    goal: response.goal,
  };
}

export interface CreatePersonaPayload {
  name: string;
  voice?: string | null;
  prompt?: string | null;
  default_motivation?: string | null;
  image_prompt?: string | null;
  description?: string | null;
  origin?: string;
}

export async function createPersona(payload: CreatePersonaPayload) {
  return apiFetch<{ persona: PersonaSummary }>("/api/personas", {
    method: "POST",
    body: JSON.stringify({ ...payload, origin: payload.origin ?? "web-ui" }),
  });
}

export async function switchPersona(name: string, origin = "web-ui") {
  return apiFetch<{ status: string; persona: string }>("/api/personas/switch", {
    method: "POST",
    body: JSON.stringify({ name, origin }),
  });
}

export async function updateGoal(goal: string, origin = "web-ui") {
  return apiFetch<{ goal: string }>("/api/interaction/goal", {
    method: "POST",
    body: JSON.stringify({ goal, origin }),
  });
}

export interface UpdatePersonaDetailsPayload {
  prompt: string;
  voice?: string | null;
  default_motivation?: string | null;
  image_prompt?: string | null;
  origin?: string;
}

export async function updatePersonaDetails(payload: UpdatePersonaDetailsPayload) {
  const { origin = "web-ui", ...details } = payload;
  return apiFetch<{
    persona: string;
    prompt: string;
    voice: string | null | undefined;
    default_motivation: string | null | undefined;
    image_prompt: string | null | undefined;
  }>("/api/interaction/prompt", {
    method: "POST",
    body: JSON.stringify({ ...details, origin }),
  });
}

export async function instructResponse(instructions: string, origin = "web-ui") {
  return apiFetch<{ status: string }>("/api/interaction/instruct", {
    method: "POST",
    body: JSON.stringify({ instructions, origin }),
  });
}

export async function requestShutdown(origin = "web-ui") {
  return apiFetch<{ status: string }>("/api/system/shutdown", {
    method: "POST",
    body: JSON.stringify({ origin }),
  });
}
