"use client";

import { useState } from "react";
import { openAsk, type AskPart } from "@/lib/ai";
import { useSettings } from "@/lib/settings";

// "Ask AI" on a page or card: builds the parts it would send (some fetch figures
// first) and opens the Ask AI box. Hidden when Local AI is switched off.
export default function AskButton({ title, parts, entity, indicator, className = "link small" }: {
  title: string; parts: () => AskPart[] | Promise<AskPart[]>; entity?: string; indicator?: string; className?: string;
}) {
  const s = useSettings();
  const [busy, setBusy] = useState(false);
  if (!s.ai_enabled) return null;
  return (
    <button className={className} disabled={busy} title="Ask the local AI; what is on this page goes with the question"
      onClick={async () => {
        setBusy(true);
        try { openAsk({ title, parts: await parts(), entity, indicator }); } finally { setBusy(false); }
      }}>{busy ? "Gathering…" : "Ask AI"}</button>
  );
}
