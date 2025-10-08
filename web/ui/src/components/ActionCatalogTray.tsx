import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowDown,
  ArrowDownLeft,
  ArrowDownRight,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowUpLeft,
  ArrowUpRight,
  ChevronDown,
  Loader2,
  Move,
  PlayCircle,
  Search,
} from "lucide-react";
import { useRobotContext } from "@/context/RobotContext";
import { triggerAction } from "@/lib/actions";

type IconComponent = (props: { className?: string }) => JSX.Element;

const DIRECTIONAL_ACTIONS = new Set(["walk_forward", "walk_backward", "walk_left", "walk_right"]);

const HEAD_ORIENTATION_ACTIONS = new Set([
  "turn_head_up_left",
  "turn_head_up",
  "turn_head_up_right",
  "turn_head_left",
  "turn_head_forward",
  "turn_head_right",
  "turn_head_down_left",
  "turn_head_down",
  "turn_head_down_right",
]);

const MOVEMENT_ACTIONS = new Set(["stand", "sit", "lie", "sit_2_stand", "stretch", "push_up", "body_twisting"]);
const VOCAL_ACTIONS = new Set(["bark", "bark_harder", "pant", "howling"]);
const TILT_HEAD_ACTIONS = new Set(["tilt_head_left", "tilt_head_right"]);
const POSTURE_VOICE_ACTIONS = new Set([...MOVEMENT_ACTIONS, ...VOCAL_ACTIONS, ...TILT_HEAD_ACTIONS]);

const GESTURE_ACTIONS = new Set([
  "wag_tail",
  "scratch",
  "handshake",
  "high_five",
  "lick_hand",
  "fluster",
  "surprise",
  "alert",
  "attack_posture",
  "feet_shake",
  "think",
  "recall",
  "bored",
  "doze_off",
  "nod",
  "relax_neck",
  "shake_head",
]);

const OTHER_GROUP_DEFINITIONS: Array<{ id: string; title: string; members: Set<string> }> = [
  { id: "gestures", title: "Gestures & Tricks", members: GESTURE_ACTIONS },
  { id: "postureVoice", title: "Posture & Voice", members: POSTURE_VOICE_ACTIONS },
];

const HEAD_LAYOUT: Array<Array<{ action: string; icon: IconComponent } | null>> = [
  [
    { action: "turn_head_up_left", icon: ArrowUpLeft },
    { action: "turn_head_up", icon: ArrowUp },
    { action: "turn_head_up_right", icon: ArrowUpRight },
  ],
  [
    { action: "turn_head_left", icon: ArrowLeft },
    { action: "turn_head_forward", icon: Move },
    { action: "turn_head_right", icon: ArrowRight },
  ],
  [
    { action: "turn_head_down_left", icon: ArrowDownLeft },
    { action: "turn_head_down", icon: ArrowDown },
    { action: "turn_head_down_right", icon: ArrowDownRight },
  ],
];

const DIRECTIONAL_LAYOUT: Array<Array<{ action: string; keyHint: string; icon: IconComponent } | null>> = [
  [null, { action: "walk_forward", keyHint: "W", icon: ArrowUp }, null],
  [
    { action: "walk_left", keyHint: "A", icon: ArrowLeft },
    null,
    { action: "walk_right", keyHint: "D", icon: ArrowRight },
  ],
  [null, { action: "walk_backward", keyHint: "S", icon: ArrowDown }, null],
];

function prettifyActionName(name: string): string {
  return name
    .replace(/[_\-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function ActionCatalogTray() {
  const { actions, currentAction } = useRobotContext();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(true);
  const [sendingAction, setSendingAction] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const sortedActions = useMemo(() => [...actions].sort((a, b) => a.localeCompare(b)), [actions]);
  const filteredActions = useMemo(() => {
    const value = query.trim().toLowerCase();
    if (!value) {
      return sortedActions;
    }
    return sortedActions.filter((action) => action.toLowerCase().includes(value));
  }, [sortedActions, query]);

  const filteredSet = useMemo(() => new Set(filteredActions), [filteredActions]);

  const groupedActions = useMemo(() => {
    if (!filteredActions.length) {
      return [] as Array<{ id: string; title: string; items: string[] }>;
    }

    const remaining = new Set(filteredActions);

    DIRECTIONAL_ACTIONS.forEach((action) => remaining.delete(action));
    HEAD_ORIENTATION_ACTIONS.forEach((action) => remaining.delete(action));

    const groups: Array<{ id: string; title: string; items: string[] }> = [];

    OTHER_GROUP_DEFINITIONS.forEach((definition) => {
      const items = filteredActions.filter((action) => definition.members.has(action));
      if (items.length) {
        items.forEach((item) => remaining.delete(item));
        groups.push({ id: definition.id, title: definition.title, items });
      }
    });

    if (remaining.size) {
      groups.push({
        id: "other",
        title: "Other Actions",
        items: Array.from(remaining).sort((a, b) => a.localeCompare(b)),
      });
    }

    return groups;
  }, [filteredActions]);

  const handleTriggerAction = async (actionId: string) => {
    if (sendingAction) {
      return;
    }
    setSendingAction(actionId);
    try {
      await triggerAction({ name: actionId });
      const label = prettifyActionName(actionId);
      setFeedback(`Action "${label}" queued`);
    } catch (error) {
      setFeedback(`Failed to run action ${actionId}`);
    } finally {
      setSendingAction(null);
    }
  };

  const hasDirectional = Array.from(DIRECTIONAL_ACTIONS).some((action) => filteredSet.has(action));
  const hasHeadOrientation = Array.from(HEAD_ORIENTATION_ACTIONS).some((action) => filteredSet.has(action));

  const displayGroups = useMemo(() => {
    const existingOther = groupedActions.find((group) => group.id === "other");
    const shouldIncludeOther = hasDirectional || hasHeadOrientation;

    if (!existingOther && shouldIncludeOther) {
      return [
        ...groupedActions,
        {
          id: "other",
          title: "Other Actions",
          items: [],
        },
      ];
    }

    if (existingOther && !shouldIncludeOther && existingOther.items.length === 0) {
      return groupedActions.filter((group) => group.id !== "other");
    }

    return groupedActions;
  }, [groupedActions, hasDirectional, hasHeadOrientation]);

  return (
    <div className="rounded-3xl border border-white/5 bg-white/10 p-5 shadow-glow">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold tracking-tight text-white">Action catalog</h2>
          <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/60">
            {filteredActions.length} actions
          </span>
        </div>
        <div className="flex items-center gap-2">
          {feedback && (
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/70">
              {feedback}
            </span>
          )}
          <button
            type="button"
            onClick={() => setOpen((prev) => !prev)}
            className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold uppercase tracking-[0.25em] text-white/60 transition hover:border-white/30 hover:text-white"
          >
            <span>{open ? "Collapse" : "Expand"}</span>
            <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
        </div>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="catalog-content"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="mt-5 space-y-5"
          >
            <label className="flex items-center gap-2 rounded-full border border-white/10 bg-black/20 px-4 py-2 text-sm text-white/70 focus-within:border-aurora/50">
              <Search className="h-4 w-4 text-white/40" />
              <input
                type="text"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter actions..."
                className="w-full bg-transparent text-sm text-white placeholder:text-white/30 focus:outline-none"
              />
            </label>

            {filteredActions.length === 0 ? (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-white/60">
                No actions match that filter.
              </div>
            ) : (
              <div className="space-y-5">
                {displayGroups.length > 0 && (
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {displayGroups.map((group) =>
                      group.id === "other" ? (
                        <OtherActionsSection
                          key={group.id}
                          title={group.title}
                          items={group.items}
                          currentAction={currentAction}
                          sendingAction={sendingAction}
                          onTrigger={handleTriggerAction}
                          filteredSet={filteredSet}
                          showDirectional={hasDirectional}
                          showHeadOrientation={hasHeadOrientation}
                        />
                      ) : (
                        <ActionSection
                          key={group.id}
                          title={group.title}
                          items={group.items}
                          currentAction={currentAction}
                          sendingAction={sendingAction}
                          onTrigger={handleTriggerAction}
                        />
                      )
                    )}
                  </div>
                )}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface InteractiveSectionProps {
  currentAction: string | null;
  sendingAction: string | null;
  onTrigger: (actionId: string) => void;
  filteredSet: Set<string>;
}

function DirectionalSection({ currentAction, sendingAction, onTrigger, filteredSet }: InteractiveSectionProps) {
  return (
    <section className="space-y-1.5 rounded-xl border border-white/10 bg-white/5 p-2">
      <header className="flex items-center justify-between">
        <h3 className="text-[10px] font-semibold uppercase tracking-[0.3em] text-white/40">Directional</h3>
        <span className="text-[9px] uppercase tracking-[0.35em] text-white/30">W A S D</span>
      </header>
      <div className="grid grid-cols-3 gap-1">
        {DIRECTIONAL_LAYOUT.flatMap((row, rowIndex) =>
          row.map((cell, columnIndex) => {
            if (!cell || !filteredSet.has(cell.action)) {
              return (
                <div
                  key={`${rowIndex}-${columnIndex}`}
                  className="aspect-square min-h-[2.35rem] rounded-lg border border-white/5 bg-black/10"
                />
              );
            }
            return (
              <DirectionalButton
                key={cell.action}
                {...cell}
                isCurrent={currentAction === cell.action}
                isSending={sendingAction === cell.action}
                disabled={Boolean(sendingAction)}
                onClick={() => onTrigger(cell.action)}
              />
            );
          })
        )}
      </div>
    </section>
  );
}

function HeadOrientationSection({ currentAction, sendingAction, onTrigger, filteredSet }: InteractiveSectionProps) {
  return (
    <section className="space-y-1.5 rounded-xl border border-white/10 bg-white/5 p-2">
      <header className="text-[10px] font-semibold uppercase tracking-[0.3em] text-white/40">Head orientation</header>
      <div className="grid grid-cols-3 gap-1">
        {HEAD_LAYOUT.flatMap((row, rowIndex) =>
          row.map((cell, columnIndex) => {
            if (!cell || !filteredSet.has(cell.action)) {
              return (
                <div
                  key={`${rowIndex}-${columnIndex}`}
                  className="aspect-square min-h-[2.35rem] rounded-lg border border-white/5 bg-black/10"
                />
              );
            }
            return (
              <HeadOrientationButton
                key={cell.action}
                {...cell}
                isCurrent={currentAction === cell.action}
                isSending={sendingAction === cell.action}
                disabled={Boolean(sendingAction)}
                onClick={() => onTrigger(cell.action)}
              />
            );
          })
        )}
      </div>
    </section>
  );
}

interface ActionSectionProps {
  title: string;
  items: string[];
  currentAction: string | null;
  sendingAction: string | null;
  onTrigger: (actionId: string) => void;
}

function ActionSection({ title, items, currentAction, sendingAction, onTrigger }: ActionSectionProps) {
  return (
    <section className="flex h-full flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4">
      <header className="text-xs font-semibold uppercase tracking-[0.25em] text-white/40">{title}</header>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((action) => (
          <StandardActionButton
            key={action}
            action={action}
            isCurrent={currentAction === action}
            isSending={sendingAction === action}
            disabled={Boolean(sendingAction)}
            onClick={() => onTrigger(action)}
          />
        ))}
      </div>
    </section>
  );
}

interface OtherActionsSectionProps extends ActionSectionProps {
  filteredSet: Set<string>;
  showDirectional: boolean;
  showHeadOrientation: boolean;
}

function OtherActionsSection({
  title,
  items,
  currentAction,
  sendingAction,
  onTrigger,
  filteredSet,
  showDirectional,
  showHeadOrientation,
}: OtherActionsSectionProps) {
  const showOtherList = items.length > 0;

  return (
    <section className="flex h-full flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4">
      <header className="text-xs font-semibold uppercase tracking-[0.25em] text-white/40">{title}</header>
      {(showDirectional || showHeadOrientation) && (
        <div className="grid gap-2 sm:grid-cols-2">
          {showDirectional && (
            <DirectionalSection
              currentAction={currentAction}
              sendingAction={sendingAction}
              onTrigger={onTrigger}
              filteredSet={filteredSet}
            />
          )}
          {showHeadOrientation && (
            <HeadOrientationSection
              currentAction={currentAction}
              sendingAction={sendingAction}
              onTrigger={onTrigger}
              filteredSet={filteredSet}
            />
          )}
        </div>
      )}
      {showOtherList && (
        <div className="grid gap-2 sm:grid-cols-2">
          {items.map((action) => (
            <StandardActionButton
              key={action}
              action={action}
              isCurrent={currentAction === action}
              isSending={sendingAction === action}
              disabled={Boolean(sendingAction)}
              onClick={() => onTrigger(action)}
            />
          ))}
        </div>
      )}
      {!showOtherList && !(showDirectional || showHeadOrientation) && (
        <p className="rounded-xl border border-white/10 bg-black/10 px-3 py-2 text-center text-[11px] text-white/40">
          No actions match that filter.
        </p>
      )}
    </section>
  );
}

interface DirectionalButtonProps {
  action: string;
  keyHint: string;
  icon: IconComponent;
  isSending: boolean;
  isCurrent: boolean;
  onClick: () => void;
  disabled: boolean;
}

function DirectionalButton({ action, keyHint, icon: Icon, isSending, isCurrent, onClick, disabled }: DirectionalButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex aspect-square min-h-[2.35rem] flex-col items-center justify-center gap-1 rounded-lg border border-white/10 bg-black/20 text-[10px] font-medium transition hover:border-aurora/60 hover:text-white ${
        isSending ? "opacity-70" : ""
      }`}
    >
      <span className="text-[9px] font-semibold uppercase tracking-[0.35em] text-white/30">{keyHint}</span>
      {isSending ? <Loader2 className="h-3 w-3 animate-spin text-aurora" /> : <Icon className="h-3 w-3 text-aurora" />}
      <span className="text-[9px] uppercase tracking-[0.2em] text-white/50">{prettifyActionName(action)}</span>
      {isCurrent && (
        <span className="rounded-full border border-aurora/40 bg-aurora/10 px-1.5 py-[2px] text-[8px] uppercase tracking-[0.2em] text-aurora">
          Running
        </span>
      )}
    </button>
  );
}

interface HeadOrientationButtonProps {
  action: string;
  icon: IconComponent;
  isSending: boolean;
  isCurrent: boolean;
  onClick: () => void;
  disabled: boolean;
}

function HeadOrientationButton({ action, icon: Icon, isSending, isCurrent, onClick, disabled }: HeadOrientationButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex aspect-square min-h-[2.35rem] flex-col items-center justify-center gap-1 rounded-lg border border-white/10 bg-black/20 text-[10px] font-medium transition hover:border-aurora/60 hover:text-white ${
        isSending ? "opacity-70" : ""
      }`}
    >
      {isSending ? <Loader2 className="h-3 w-3 animate-spin text-aurora" /> : <Icon className="h-3 w-3 text-aurora" />}
      <span className="text-[9px] uppercase tracking-[0.25em] text-white/40">{prettifyActionName(action)}</span>
      {isCurrent && (
        <span className="rounded-full border border-aurora/40 bg-aurora/10 px-1.5 py-[2px] text-[8px] uppercase tracking-[0.2em] text-aurora">
          Running
        </span>
      )}
    </button>
  );
}

interface StandardActionButtonProps {
  action: string;
  isSending: boolean;
  isCurrent: boolean;
  onClick: () => void;
  disabled: boolean;
}

function StandardActionButton({ action, isSending, isCurrent, onClick, disabled }: StandardActionButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-left text-sm transition hover:border-aurora/60 hover:text-white ${
        isSending ? "opacity-70" : ""
      }`}
    >
      <span className="flex items-center gap-2">
        {isSending ? (
          <Loader2 className="h-4 w-4 animate-spin text-aurora" />
        ) : (
          <PlayCircle className="h-4 w-4 text-aurora" />
        )}
        <span className="font-medium text-white">{prettifyActionName(action)}</span>
      </span>
      {isCurrent && (
        <span className="rounded-full border border-aurora/40 bg-aurora/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] text-aurora">
          Running
        </span>
      )}
    </button>
  );
}
