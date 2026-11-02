"use client";

import { useSettings } from "@/lib/settings";

// "Ask AI" beside a card's "Save picture"; hidden when Local AI is off.
export default function CardAsk({ onAsk }: { onAsk: () => void }) {
  const s = useSettings();
  if (!s.ai_enabled) return null;
  return <button className="link small" title="Ask the local AI about this chart; its figures (and a picture) go with the question" onClick={onAsk}>Ask AI</button>;
}
