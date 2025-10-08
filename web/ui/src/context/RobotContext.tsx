import { createContext, useCallback, useContext, useMemo, useReducer, ReactNode } from "react";
import {
  CameraStreamStatus,
  DEFAULT_LOOP_STATUS,
  PersonaState,
  RobotContextValue,
  RobotStateSnapshot,
  TimelineEvent,
} from "@/lib/store";

interface RobotStoreState {
  state: RobotStateSnapshot;
  events: TimelineEvent[];
  loops: typeof DEFAULT_LOOP_STATUS;
  camera: CameraStreamStatus | null;
  currentAction: string | null;
  persona: PersonaState;
  actions: string[];
}

const initialState: RobotStoreState = {
  state: null,
  events: [],
  loops: { ...DEFAULT_LOOP_STATUS },
  camera: null,
  currentAction: null,
  persona: { list: [], current: null, selected: null },
  actions: [],
};

type Action =
  | { type: "SET_STATE"; snapshot: RobotStateSnapshot }
  | { type: "PUSH_EVENT"; event: TimelineEvent }
  | { type: "RESET_EVENTS"; events: TimelineEvent[] }
  | { type: "SET_LOOPS"; loops: Partial<typeof DEFAULT_LOOP_STATUS> }
  | { type: "SET_CAMERA"; camera: CameraStreamStatus | null }
  | { type: "SET_CURRENT_ACTION"; action: string | null }
  | { type: "SET_PERSONA"; persona: PersonaState }
  | { type: "SET_ACTIONS"; actions: string[] };

function reducer(state: RobotStoreState, action: Action): RobotStoreState {
  switch (action.type) {
    case "SET_STATE":
      return { ...state, state: action.snapshot };
    case "PUSH_EVENT": {
      const incoming = action.event;
      const id = typeof incoming.id === "string" ? incoming.id : null;
      let events = state.events;

      if (id) {
        const existingIndex = events.findIndex((event) => event.id === id);
        if (existingIndex >= 0) {
          events = events.map((event, index) => (index === existingIndex ? incoming : event));
        } else {
          events = [...events, incoming];
        }
      } else {
        events = [...events, incoming];
      }

      if (events.length > 200) {
        events = events.slice(-200);
      }

      return { ...state, events };
    }
    case "RESET_EVENTS": {
      const trimmed = action.events.slice(-200);
      return { ...state, events: trimmed };
    }
    case "SET_LOOPS":
      return { ...state, loops: { ...state.loops, ...action.loops } };
    case "SET_CAMERA":
      return { ...state, camera: action.camera };
    case "SET_CURRENT_ACTION":
      return { ...state, currentAction: action.action };
    case "SET_PERSONA":
      return { ...state, persona: action.persona };
    case "SET_ACTIONS":
      return { ...state, actions: action.actions };
    default:
      return state;
  }
}

const RobotContext = createContext<RobotContextValue | undefined>(undefined);

export function RobotProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const setState = useCallback((snapshot: RobotStateSnapshot) => {
    dispatch({ type: "SET_STATE", snapshot });
  }, []);

  const pushEvent = useCallback((event: TimelineEvent) => {
    dispatch({ type: "PUSH_EVENT", event });
  }, []);

  const setLoops = useCallback((loops: Partial<typeof DEFAULT_LOOP_STATUS>) => {
    dispatch({ type: "SET_LOOPS", loops });
  }, []);

  const resetEvents = useCallback((events: TimelineEvent[]) => {
    dispatch({ type: "RESET_EVENTS", events });
  }, []);

  const setCamera = useCallback((camera: CameraStreamStatus | null) => {
    dispatch({ type: "SET_CAMERA", camera });
  }, []);

  const setCurrentAction = useCallback((action: string | null) => {
    dispatch({ type: "SET_CURRENT_ACTION", action });
  }, []);

  const setPersona = useCallback((persona: PersonaState) => {
    dispatch({ type: "SET_PERSONA", persona });
  }, []);

  const setActions = useCallback((actions: string[]) => {
    dispatch({ type: "SET_ACTIONS", actions });
  }, []);

  const value = useMemo<RobotContextValue>(() => ({
    state: state.state,
    events: state.events,
    loops: state.loops,
    camera: state.camera,
    currentAction: state.currentAction,
    persona: state.persona,
    actions: state.actions,
    setState,
    pushEvent,
    setLoops,
    resetEvents,
    setCamera,
    setCurrentAction,
    setPersona,
    setActions,
  }), [state.state, state.events, state.loops, state.camera, state.currentAction, state.persona, state.actions, setState, pushEvent, setLoops, resetEvents, setCamera, setCurrentAction, setPersona, setActions]);

  return <RobotContext.Provider value={value}>{children}</RobotContext.Provider>;
}

export function useRobotContext(): RobotContextValue {
  const context = useContext(RobotContext);
  if (!context) {
    throw new Error("useRobotContext must be used within a RobotProvider");
  }
  return context;
}
