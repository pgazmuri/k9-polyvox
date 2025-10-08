export type RobotStateSnapshot = Record<string, unknown> | null;

export interface TimelineEvent {
  id: string;
  type: string;
  timestamp: string;
  payload: Record<string, unknown>;
  meta?: Record<string, unknown>;
}

export type LoopStatus = {
  awareness: boolean;
  sensors: boolean;
};

export interface RobotContextValue {
  state: RobotStateSnapshot;
  events: TimelineEvent[];
  loops: LoopStatus;
  camera: CameraStreamStatus | null;
  currentAction: string | null;
  persona: PersonaState;
  actions: string[];
  setState: (snapshot: RobotStateSnapshot) => void;
  pushEvent: (event: TimelineEvent) => void;
  setLoops: (loops: Partial<LoopStatus>) => void;
  resetEvents: (events: TimelineEvent[]) => void;
  setCamera: (camera: CameraStreamStatus | null) => void;
  setCurrentAction: (action: string | null) => void;
  setPersona: (persona: PersonaState) => void;
  setActions: (actions: string[]) => void;
}

export const DEFAULT_LOOP_STATUS: LoopStatus = {
  awareness: true,
  sensors: true,
};

export interface CameraStreamStatus {
  enabled: boolean;
  streamUrl: string | null;
  frameRate?: number | null;
  port?: number | null;
  path?: string | null;
}

export interface PersonaSummary {
  name: string;
  voice?: string;
  description?: string;
  prompt?: string;
  default_motivation?: string;
  image_prompt?: string;
}

export interface PersonaState {
  list: PersonaSummary[];
  current: PersonaSummary | null;
  selected: string | null;
}
