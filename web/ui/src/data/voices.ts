export interface VoiceOption {
  id: string;
  label: string;
  description: string;
}

export const VOICE_OPTIONS: VoiceOption[] = [
  {
    id: "alloy",
    label: "Alloy — Balanced neutral",
    description: "Balanced, gender-neutral voice that works well for general personas.",
  },
  {
    id: "ash",
    label: "Ash — Warm radio male",
    description: "Warm, calming male voice with a friendly radio host quality.",
  },
  {
    id: "ballad",
    label: "Ballad — Melodious British male",
    description: "Melodic male voice with a British lilt, ideal for storytelling personas.",
  },
  {
    id: "coral",
    label: "Coral — Clear instructional female",
    description: "High-pitched, articulate female voice suited for informative or instructional tones.",
  },
  {
    id: "echo",
    label: "Echo — Resonant authoritative male",
    description: "Resonant male voice that carries authority and impact.",
  },
  {
    id: "sage",
    label: "Sage — Gentle peacemaker female",
    description: "Calming female presence with optimistic, soothing energy.",
  },
  {
    id: "shimmer",
    label: "Shimmer — Soft playful female",
    description: "Soft, steady female voice with a spark of playfulness—great for empathetic personas.",
  },
  {
    id: "verse",
    label: "Verse — Sing-song male",
    description: "Friendly, musical male voice that stays light-hearted and non-threatening.",
  },
  {
    id: "marin",
    label: "Marin — Expressive next-gen female",
    description: "Expressive, modern female voice with rich emotional range and warmth.",
  },
  {
    id: "cedar",
    label: "Cedar — Expressive next-gen male",
    description: "Expressive, reliable male voice with warmth and subtle authority.",
  },
];

export const VOICE_OPTION_MAP = VOICE_OPTIONS.reduce<Record<string, VoiceOption>>((acc, option) => {
  acc[option.id] = option;
  return acc;
}, {});
