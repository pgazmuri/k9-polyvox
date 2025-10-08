import { KeyboardEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Image as ImageIcon, Mic2, Power, Save, Sparkles, Target, UserCircle2 } from "lucide-react";
import { useRobotContext } from "@/context/RobotContext";
import { createPersona, fetchPersonas, requestShutdown, switchPersona, updatePersonaDetails } from "@/lib/actions";
import { VOICE_OPTIONS, VOICE_OPTION_MAP } from "@/data/voices";

const NEW_PERSONA_VALUE = "__persona_new__";

export function PersonaPanel() {
  const { persona, setPersona } = useRobotContext();

  const resolvePersona = useCallback(
    (name: string | null) => {
      const resolved = name ?? persona.selected ?? persona.current?.name ?? null;
      if (!resolved) {
        return null;
      }
      const fromList = persona.list.find((item) => item.name === resolved);
      if (fromList) {
        return fromList;
      }
      if (persona.current && persona.current.name === resolved) {
        return persona.current;
      }
      return null;
    },
    [persona.list, persona.current, persona.selected],
  );

  const initialName = persona.selected ?? persona.current?.name ?? null;
  const initialPersona = resolvePersona(initialName);

  const [selectedPersona, setSelectedPersona] = useState<string | null>(initialName);
  const [switching, setSwitching] = useState(false);
  const [creatingPersona, setCreatingPersona] = useState(false);
  const [newPersonaName, setNewPersonaName] = useState<string>("");
  const [promptDraft, setPromptDraft] = useState<string>(initialPersona?.prompt ?? "");
  const [voiceDraft, setVoiceDraft] = useState<string>(
    initialPersona?.voice ? initialPersona.voice.toLowerCase() : "",
  );
  const [motivationDraft, setMotivationDraft] = useState<string>(initialPersona?.default_motivation ?? "");
  const [imagePromptDraft, setImagePromptDraft] = useState<string>(initialPersona?.image_prompt ?? "");
  const [descriptionDraft, setDescriptionDraft] = useState<string>(initialPersona?.description ?? "");
  const [isDirty, setDirty] = useState(false);
  const [savingPersona, setSavingPersona] = useState(false);
  const [shutdownBusy, setShutdownBusy] = useState(false);
  const [shutdownConfirmed, setShutdownConfirmed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const personaOptions = persona.list;
  const currentPersona = useMemo(
    () => resolvePersona(selectedPersona),
    [resolvePersona, selectedPersona],
  );

  const isCreatingNew = selectedPersona === NEW_PERSONA_VALUE;

  const selectedVoiceOption = useMemo(
    () => (voiceDraft ? VOICE_OPTION_MAP[voiceDraft] : undefined),
    [voiceDraft],
  );

  const voiceChangePending = useMemo(() => {
    if (!currentPersona || isCreatingNew) {
      return false;
    }
    const currentVoice = currentPersona.voice ?? "";
    return (voiceDraft || "") !== currentVoice;
  }, [currentPersona, voiceDraft, isCreatingNew]);

  const newPersonaReady = newPersonaName.trim().length > 0 && promptDraft.trim().length > 0;
  const saveDisabled = isCreatingNew ? creatingPersona || !newPersonaReady : savingPersona || !isDirty;
  const saveLabel = isCreatingNew ? "Create persona" : "Save and load persona";
  const statusLabel = isCreatingNew ? "New persona draft" : isDirty ? "Unsaved persona changes" : "Persona synced";

  useEffect(() => {
    setSelectedPersona((previous) => {
      if (previous === NEW_PERSONA_VALUE) {
        return previous;
      }
      return persona.selected ?? persona.current?.name ?? null;
    });
  }, [persona.selected, persona.current?.name]);

  useEffect(() => {
    if (isCreatingNew) {
      return;
    }
    if (!isDirty) {
  setPromptDraft(currentPersona?.prompt ?? "");
  setVoiceDraft(currentPersona?.voice ? currentPersona.voice.toLowerCase() : "");
      setMotivationDraft(currentPersona?.default_motivation ?? "");
      setImagePromptDraft(currentPersona?.image_prompt ?? "");
      setDescriptionDraft(currentPersona?.description ?? "");
    }
  }, [currentPersona, isDirty, isCreatingNew]);

  const handlePersonaChange = async (name: string) => {
    setMessage(null);
    setError(null);

    if (name === NEW_PERSONA_VALUE) {
      setSelectedPersona(NEW_PERSONA_VALUE);
      setNewPersonaName("");
      setPromptDraft("");
      setVoiceDraft("");
      setMotivationDraft("");
      setImagePromptDraft("");
      setDescriptionDraft("");
      setDirty(false);
      return;
    }

    const nextName = name || null;
    setSelectedPersona(nextName);
    setDirty(false);
    const localPersona = resolvePersona(nextName);
  setPromptDraft(localPersona?.prompt ?? "");
  setVoiceDraft(localPersona?.voice ? localPersona.voice.toLowerCase() : "");
    setMotivationDraft(localPersona?.default_motivation ?? "");
    setImagePromptDraft(localPersona?.image_prompt ?? "");
    setDescriptionDraft(localPersona?.description ?? "");
    setNewPersonaName("");

    if (!name) {
      return;
    }
    if (name === persona.selected) {
      return;
    }
    setSwitching(true);
    setError(null);
    setMessage(`Switching to ${name}...`);
    try {
      await switchPersona(name);
      const refreshed = await fetchPersonas();
      setPersona(refreshed.persona);
      const resolvedName = refreshed.persona.selected ?? name ?? null;
      setSelectedPersona(resolvedName);
      const refreshedDetails =
        refreshed.persona.list.find((item) => item.name === resolvedName) ??
        (refreshed.persona.current && refreshed.persona.current.name === resolvedName ? refreshed.persona.current : null);
      setPromptDraft(refreshedDetails?.prompt ?? "");
      setVoiceDraft(refreshedDetails?.voice ?? "");
      setMotivationDraft(refreshedDetails?.default_motivation ?? "");
      setImagePromptDraft(refreshedDetails?.image_prompt ?? "");
      setDirty(false);
      setMessage(resolvedName ? `Switched to ${resolvedName}.` : "Persona updated.");
    } catch (err: any) {
      console.error(err);
      setError(err?.message ?? "Failed to switch persona");
    } finally {
      setSwitching(false);
    }
  };

  const handleSavePersona = async () => {
    const normalizedPrompt = promptDraft.trim();
    if (!normalizedPrompt) {
      setError("Prompt cannot be empty");
      return;
    }
    const normalizedVoiceRaw = voiceDraft.trim();
    const normalizedVoice = normalizedVoiceRaw ? normalizedVoiceRaw.toLowerCase() : "";
    const normalizedMotivation = motivationDraft.trim();
    const normalizedImagePrompt = imagePromptDraft.trim();
    const normalizedDescription = descriptionDraft.trim();

    if (isCreatingNew) {
      const normalizedName = newPersonaName.trim().replace(/\s+/g, " ");
      if (!normalizedName) {
        setError("Persona name cannot be empty");
        return;
      }
      if (personaOptions.some((option) => option.name.toLowerCase() === normalizedName.toLowerCase())) {
        setError(`Persona '${normalizedName}' already exists.`);
        return;
      }

      setCreatingPersona(true);
      setSwitching(true);
      setError(null);
      setMessage(null);
      try {
        await createPersona({
          name: normalizedName,
          voice: normalizedVoice ? normalizedVoice : null,
          prompt: normalizedPrompt,
          default_motivation: normalizedMotivation ? normalizedMotivation : null,
          image_prompt: normalizedImagePrompt ? normalizedImagePrompt : null,
          description: normalizedDescription ? normalizedDescription : null,
        });
        setMessage("Persona created. Loading it now...");
        await switchPersona(normalizedName);
        const refreshed = await fetchPersonas();
        setPersona(refreshed.persona);
        const resolvedName = refreshed.persona.selected ?? normalizedName;
        setSelectedPersona(resolvedName);
        const refreshedDetails =
          refreshed.persona.list.find((item) => item.name === resolvedName) ??
          (refreshed.persona.current && refreshed.persona.current.name === resolvedName
            ? refreshed.persona.current
            : null);
        setPromptDraft(refreshedDetails?.prompt ?? normalizedPrompt);
        setVoiceDraft(
          refreshedDetails?.voice ? refreshedDetails.voice.toLowerCase() : normalizedVoice,
        );
        setMotivationDraft(refreshedDetails?.default_motivation ?? normalizedMotivation);
        setImagePromptDraft(refreshedDetails?.image_prompt ?? normalizedImagePrompt);
        setDescriptionDraft(refreshedDetails?.description ?? normalizedDescription);
        setDirty(false);
        setNewPersonaName("");
        setMessage(`Persona '${resolvedName}' created and session restarted.`);
      } catch (err: any) {
        console.error(err);
        setError(err?.message ?? "Failed to create persona");
      } finally {
        setCreatingPersona(false);
        setSwitching(false);
      }
      return;
    }

    const previousVoice = currentPersona?.voice ?? null;

    setSavingPersona(true);
    setError(null);
    setMessage(null);
    try {
      await updatePersonaDetails({
        prompt: normalizedPrompt,
        voice: normalizedVoice ? normalizedVoice : null,
        default_motivation: normalizedMotivation ? normalizedMotivation : null,
        image_prompt: normalizedImagePrompt ? normalizedImagePrompt : null,
      });
      setDirty(false);
      const refreshed = await fetchPersonas();
      setPersona(refreshed.persona);
      const resolvedName = refreshed.persona.selected ?? selectedPersona ?? persona.current?.name ?? null;
      setSelectedPersona(resolvedName);
      const refreshedDetails =
        refreshed.persona.list.find((item) => item.name === resolvedName) ??
        (refreshed.persona.current && refreshed.persona.current.name === resolvedName ? refreshed.persona.current : null);
      setPromptDraft(refreshedDetails?.prompt ?? normalizedPrompt);
      setVoiceDraft(
        refreshedDetails?.voice ? refreshedDetails.voice.toLowerCase() : normalizedVoice,
      );
      setMotivationDraft(refreshedDetails?.default_motivation ?? normalizedMotivation);
      setImagePromptDraft(refreshedDetails?.image_prompt ?? normalizedImagePrompt);
      setDescriptionDraft(refreshedDetails?.description ?? normalizedDescription);
      const updatedVoice = refreshedDetails?.voice ?? (normalizedVoice ? normalizedVoice : null);
      if ((previousVoice ?? null) !== (updatedVoice ?? null)) {
        setMessage("Persona saved. Session restarted to apply the new voice.");
      } else {
        setMessage("Persona saved and session refreshed.");
      }
    } catch (err: any) {
      console.error(err);
      setError(err?.message ?? "Failed to update persona");
    } finally {
      setSavingPersona(false);
    }
  };

  const handlePromptKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!savingPersona && isDirty && promptDraft.trim()) {
        void handleSavePersona();
      }
    }
  };

  const handleShutdown = async () => {
    if (shutdownBusy) {
      return;
    }
    const confirmed = window.confirm("Send shutdown signal to PiDog?");
    if (!confirmed) {
      return;
    }
    setShutdownBusy(true);
    setError(null);
    setMessage(null);
    try {
      await requestShutdown();
      setMessage("Shutdown requested – robot will power down shortly.");
      setShutdownConfirmed(true);
    } catch (err: any) {
      console.error(err);
      setError(err?.message ?? "Failed to request shutdown");
    } finally {
      setShutdownBusy(false);
    }
  };

  return (
    <div className="space-y-4 rounded-3xl border border-white/5 bg-white/10 p-6 shadow-glow">
      <header className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 text-white">
          <Sparkles className="h-5 w-5 text-aurora" />
          <h2 className="text-lg font-semibold tracking-tight">Persona controls</h2>
        </div>
        <button
          type="button"
          onClick={handleShutdown}
          disabled={shutdownBusy || shutdownConfirmed}
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] transition ${
            shutdownBusy || shutdownConfirmed
              ? "border-red-400/40 bg-red-400/10 text-red-200/70"
              : "border-red-400/40 bg-red-400/10 text-red-200"
          } ${shutdownBusy || shutdownConfirmed ? "opacity-70" : "hover:border-red-300/60"}`}
          title="Send shutdown command"
        >
          <Power className="h-3.5 w-3.5" />
          Shutdown
        </button>
      </header>

      <section className="space-y-3">
        <label className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white/40">
          <UserCircle2 className="h-4 w-4 text-white/50" />
          Persona
        </label>
        <div className="relative">
          <select
            className="w-full appearance-none rounded-2xl border border-white/10 bg-black/30 px-4 py-3 text-sm text-white focus:border-aurora/60 focus:outline-none"
            value={selectedPersona ?? ""}
            onChange={(event) => {
              void handlePersonaChange(event.target.value);
            }}
            disabled={switching || creatingPersona}
          >
            <option
              value=""
              disabled={Boolean(selectedPersona)}
              hidden={Boolean(selectedPersona)}
              className="bg-[#070A1B] text-white/70"
            >
              {personaOptions.length === 0 ? "Loading personas..." : "Select a persona..."}
            </option>
            {personaOptions.map((option) => (
              <option key={option.name} value={option.name} className="bg-[#070A1B] text-white">
                {option.name}
              </option>
            ))}
            <option value={NEW_PERSONA_VALUE} className="bg-[#070A1B] text-aurora">
              ➕ Add new persona…
            </option>
          </select>
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-white/40">▾</span>
        </div>
        {isCreatingNew ? (
          <div className="space-y-3 rounded-2xl border border-white/10 bg-black/20 p-4">
            <input
              value={newPersonaName}
              onChange={(event) => {
                setNewPersonaName(event.target.value);
                setDirty(true);
                setMessage(null);
              }}
              className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2 text-sm text-white placeholder:text-white/40 focus:border-aurora/60 focus:outline-none"
              placeholder="Give your persona a name"
              autoFocus
            />
            <textarea
              value={descriptionDraft}
              onChange={(event) => {
                setDescriptionDraft(event.target.value);
                setDirty(true);
                setMessage(null);
              }}
              className="min-h-[72px] w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2 text-sm text-white placeholder:text-white/40 focus:border-aurora/60 focus:outline-none"
              placeholder="Short description to show in the list (optional)"
            />
            <p className="text-xs text-white/50">
              Pick a voice below and fill out the prompt to finalize this persona.
            </p>
          </div>
        ) : (
          currentPersona?.description && (
            <p className="text-sm text-white/60">{currentPersona.description}</p>
          )
        )}
      </section>

      <section className="space-y-3">
        <label className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white/40">
          <Mic2 className="h-4 w-4 text-white/50" />
          Voice
        </label>
        <select
          value={voiceDraft}
          onChange={(event) => {
            setVoiceDraft(event.target.value);
            setDirty(true);
            setMessage(null);
          }}
          disabled={switching || creatingPersona}
          className="w-full appearance-none rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-white focus:border-aurora/60 focus:outline-none"
        >
          <option value="" className="bg-[#070A1B] text-white/70">
            Let the model choose
          </option>
          {VOICE_OPTIONS.map((option) => (
            <option key={option.id} value={option.id} className="bg-[#070A1B] text-white">
              {option.label}
            </option>
          ))}
        </select>
        <div className="space-y-1 text-xs">
          {selectedVoiceOption && (
            <p className="text-white/60">{selectedVoiceOption.description}</p>
          )}
          <p className="text-white/40">
            Saving a different voice will restart the session so the change can take effect.
          </p>
          {voiceChangePending && (
            <p className="text-aurora">Voice change queued — save when ready to apply it.</p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <label className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white/40">
          <Target className="h-4 w-4 text-white/50" />
          Motivation
        </label>
        <textarea
          value={motivationDraft}
          onChange={(event) => {
            setMotivationDraft(event.target.value);
            setDirty(true);
            setMessage(null);
          }}
          className="min-h-[96px] w-full rounded-2xl border border-white/10 bg-black/20 p-3 text-sm text-white placeholder:text-white/30 focus:border-aurora/60 focus:outline-none"
          placeholder="What goal should this persona pursue by default?"
        />
      </section>

      <section className="space-y-3">
        <label className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white/40">
          <AlertTriangle className="h-4 w-4 text-pulse" />
          Persona prompt
        </label>
        <textarea
          value={promptDraft}
          onChange={(event) => {
            setPromptDraft(event.target.value);
            setDirty(true);
            setMessage(null);
          }}
          onKeyDown={handlePromptKeyDown}
          className="min-h-[120px] w-full rounded-2xl border border-white/10 bg-black/20 p-3 text-sm text-white placeholder:text-white/30 focus:border-aurora/60 focus:outline-none"
          placeholder="Describe what motivates this persona..."
        />
      </section>

      <section className="space-y-3">
        <label className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-white/40">
          <ImageIcon className="h-4 w-4 text-white/50" />
          Image prompt guidance
        </label>
        <textarea
          value={imagePromptDraft}
          onChange={(event) => {
            setImagePromptDraft(event.target.value);
            setDirty(true);
            setMessage(null);
          }}
          className="min-h-[96px] w-full rounded-2xl border border-white/10 bg-black/20 p-3 text-sm text-white placeholder:text-white/30 focus:border-aurora/60 focus:outline-none"
          placeholder="How should the persona describe images?"
        />
        <div className="flex justify-between text-xs text-white/50">
          <span>{statusLabel}</span>
          <button
            type="button"
            onClick={handleSavePersona}
            disabled={saveDisabled}
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold transition ${
              saveDisabled
                ? "border-white/20 bg-white/10 text-white/50"
                : "border-aurora/50 bg-aurora/10 text-aurora hover:border-aurora"
            }`}
          >
            <Save className="h-3.5 w-3.5" />
            {saveLabel}
          </button>
        </div>
      </section>

      {(message || error) && (
        <div
          className={`rounded-2xl border px-3 py-2 text-xs ${
            error
              ? "border-red-400/50 bg-red-500/10 text-red-200"
              : "border-aurora/40 bg-aurora/10 text-aurora"
          }`}
        >
          {error ?? message}
        </div>
      )}
    </div>
  );
}
