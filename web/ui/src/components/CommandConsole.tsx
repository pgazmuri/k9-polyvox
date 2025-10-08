import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Mic, MicOff, Send, Zap } from "lucide-react";
import { useRobotContext } from "@/context/RobotContext";
import { instructResponse } from "@/lib/actions";

function prettifyActionName(name: string): string {
  return name
    .replace(/[_\-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function CommandConsole() {
  const { state, currentAction } = useRobotContext();
  const [instruction, setInstruction] = useState("");
  const [sending, setSending] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [speakText, setSpeakText] = useState("");
  const [sendingSpeak, setSendingSpeak] = useState(false);
  const [speechSupported, setSpeechSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<any>(null);
  const listeningRef = useRef(false);
    
  const currentActionLabel = useMemo(() => {
    if (typeof currentAction === "string" && currentAction.trim().length > 0) {
      return prettifyActionName(currentAction);
    }
    return null;
  }, [currentAction]);

  const lastAction = useMemo(() => {
    const meta = (state?.meta ?? {}) as Record<string, unknown>;
    const value = meta.last_action;
    if (typeof value === "string" && value.trim().length > 0) {
      return prettifyActionName(value);
    }
    return null;
  }, [state]);

  const submitInstruction = async () => {
    if (!instruction.trim()) {
      setFeedback("Enter instructions first");
      return;
    }
    setSending(true);
    try {
      await instructResponse(instruction.trim());
      setFeedback("Instruction sent");
      setInstruction("");
    } catch (error) {
      setFeedback("Failed to send instruction");
    } finally {
      setSending(false);
    }
  };

  const handleMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await submitInstruction();
  };
    
  const sendSpeak = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) {
      setFeedback("Say something first");
      return;
    }
    if (sendingSpeak) {
      return;
    }
    setSendingSpeak(true);
    try {
      const sanitized = trimmed.replace(/"/g, '\\"');
      await instructResponse(`say: "${sanitized}"`);
      setFeedback("Speech queued");
      setSpeakText("");
    } catch (error) {
      setFeedback("Failed to queue speech");
    } finally {
      setSendingSpeak(false);
    }
  }, [sendingSpeak]);
    
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const SpeechRecognitionCtor = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) {
      setSpeechSupported(false);
      return;
    }
    const recognition: any = new SpeechRecognitionCtor();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognitionRef.current = recognition;
    setSpeechSupported(true);
    
    recognition.onresult = (event: any) => {
      const results: any[] = Array.from(event.results ?? []);
      const finalResult = results.find((result) => result?.isFinal);
      const transcript = finalResult?.[0]?.transcript?.trim?.() ?? "";
      if (transcript) {
        setSpeakText(transcript);
        void sendSpeak(transcript);
      }
    };
    
    recognition.onerror = (event: any) => {
      console.error("Speech recognition error", event?.error);
      setFeedback(event?.error === "not-allowed" ? "Microphone access denied" : "Speech capture error");
      listeningRef.current = false;
      setListening(false);
    };
    
    recognition.onend = () => {
      if (listeningRef.current) {
        try {
          recognition.start();
        } catch (error) {
          console.error("Failed to restart speech recognition", error);
          setFeedback("Speech capture interrupted");
          listeningRef.current = false;
          setListening(false);
        }
      }
    };
    
    return () => {
      listeningRef.current = false;
      setListening(false);
      try {
        recognition.stop();
      } catch (error) {
        // ignore cleanup errors
      }
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      recognitionRef.current = null;
    };
  }, [sendSpeak]);
    
  useEffect(() => {
    listeningRef.current = listening;
    const recognition = recognitionRef.current;
    if (!recognition) {
      return;
    }
    if (listening) {
      try {
        recognition.start();
      } catch (error: any) {
        if (error?.name !== "InvalidStateError") {
          console.error("Speech recognition start failed", error);
          setFeedback("Unable to start speech capture");
          listeningRef.current = false;
          setListening(false);
        }
      }
    } else {
      try {
        recognition.stop();
      } catch (error) {
        // stop may throw if already stopped; ignore
      }
    }
  }, [listening]);
    
  const handleSpeakSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await sendSpeak(speakText);
  };
    
  const handleSpeakKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!sendingSpeak) {
        void sendSpeak(speakText);
      }
    }
  };

  const toggleListening = () => {
    if (!speechSupported) {
      setFeedback("Speech capture not supported in this browser");
      return;
    }
    setListening((prev) => {
      const next = !prev;
      listeningRef.current = next;
      return next;
    });
  };

  const handlePromptKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!sending) {
        void submitInstruction();
      }
    }
  };
    
  return (
    <div className="flex h-full flex-col gap-5 rounded-3xl border border-white/5 bg-white/10 p-6 shadow-glow">
      <header className="flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight text-white">Command console</h2>
        {feedback && (
          <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs text-white/70">
            {feedback}
          </span>
        )}
      </header>
      <section className="space-y-3">
        <div className="text-xs uppercase tracking-[0.2em] text-white/40">Current action</div>
        <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm">
          <span className="rounded-full border border-white/5 bg-white/10 p-2 text-aurora">
            <Zap className="h-4 w-4" />
          </span>
          <div className="flex flex-col">
            <span className="text-xs uppercase tracking-wide text-white/40">Active routine</span>
            <span className="font-medium text-white/80">{currentActionLabel ?? "Standing by"}</span>
          </div>
        </div>
        {lastAction && (
          <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-xs text-white/60">
            <span className="uppercase tracking-[0.2em] text-white/30">Last completed</span>
            <span className="font-medium text-white/70">{lastAction}</span>
          </div>
        )}
      </section>
    
      <section className="space-y-3">
        <form className="flex flex-col gap-3" onSubmit={handleSpeakSubmit}>
          <div className="flex items-center justify-between">
            <div className="text-xs uppercase tracking-[0.2em] text-white/40">Speak</div>
            <button
              type="button"
              onClick={toggleListening}
              disabled={!speechSupported}
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold transition ${
                listening
                  ? "border-aurora/60 bg-aurora/20 text-aurora"
                  : "border-white/10 bg-white/5 text-white/60 hover:border-white/30 hover:text-white"
              } ${speechSupported ? "" : "opacity-50"}`}
              title={speechSupported ? (listening ? "Stop listening" : "Start listening") : "Speech capture unavailable"}
            >
              {listening ? <Mic className="h-4 w-4" /> : <MicOff className="h-4 w-4" />}
              {speechSupported ? (listening ? "Listening" : "Mic") : "No Mic"}
            </button>
          </div>
          <textarea
            value={speakText}
            onChange={(event) => setSpeakText(event.target.value)}
            placeholder="What should PiDog say aloud?"
            className="min-h-[72px] w-full rounded-2xl border border-white/10 bg-black/20 p-3 text-sm text-white placeholder:text-white/30 focus:border-aurora/60 focus:outline-none focus:ring-1 focus:ring-aurora/60"
            onKeyDown={handleSpeakKeyDown}
          />
          <button
            type="submit"
            className="inline-flex items-center justify-center gap-2 rounded-full border border-aurora/60 bg-aurora/20 px-4 py-2 text-sm font-semibold text-aurora transition hover:bg-aurora/30 disabled:opacity-70"
            disabled={sendingSpeak}
          >
            {sendingSpeak ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {sendingSpeak ? "Queueing" : "Send speech"}
          </button>
        </form>
      </section>
    
      <section className="space-y-3">
        <div className="text-xs uppercase tracking-[0.2em] text-white/40">Instruct response</div>
        <form className="flex flex-col gap-3" onSubmit={handleMessage}>
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="Explain exactly how PiDog should respond..."
            className="min-h-[96px] w-full rounded-2xl border border-white/10 bg-black/20 p-3 text-sm text-white placeholder:text-white/30 focus:border-aurora/60 focus:outline-none focus:ring-1 focus:ring-aurora/60"
            onKeyDown={handlePromptKeyDown}
          />
          <button
            type="submit"
            className="inline-flex items-center justify-center gap-2 rounded-full border border-aurora/60 bg-aurora/20 px-4 py-2 text-sm font-semibold text-aurora transition hover:bg-aurora/30 disabled:opacity-70"
            disabled={sending}
          >
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {sending ? "Sending" : "Send instruction"}
          </button>
        </form>
      </section>
    </div>
  );
}
