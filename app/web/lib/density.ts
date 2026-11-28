// How much room the map page's toolbars take, kept in this browser:
// "full" is the original look, "compact" puts the page bar in the top menu and slims the
// panel toolbars and the Layers panel, "focus" hides every toolbar (F or the Focus button).
// The body carries map-compact or map-focus while the map page is open, so CSS can follow.

import { useSyncExternalStore } from "react";

export type Density = "full" | "compact" | "focus";
export const DENSITIES: { id: Density; label: string; hint: string }[] = [
  { id: "full", label: "Full", hint: "Every toolbar as it was: the page bar on its own row, all view tabs and buttons in each panel" },
  { id: "compact", label: "Compact", hint: "The page bar in the top menu, one-row panel toolbars (a View list and a ⋯ menu in narrow panels) and a slimmer Layers panel" },
  { id: "focus", label: "Focus", hint: "Panels only: every menu and toolbar hidden (F or Esc brings them back)" },
];

const KEY = "wm.mapDensity";
const BACK = "wm.mapDensityBack"; // what Esc goes back to from Focus
const OLD_FOCUS = "wm.mapFocus"; // the older hide-controls switch
const DEFAULT: Density = "compact";
const listeners = new Set<() => void>();
let cached: Density | null = null;

function read(): Density {
  if (cached) return cached;
  let v: string | null = null;
  try {
    v = window.localStorage.getItem(KEY);
    if (!v && window.localStorage.getItem(OLD_FOCUS) === "1") v = "focus";
  } catch { /* storage blocked: the default */ }
  cached = v === "full" || v === "compact" || v === "focus" ? v : DEFAULT;
  return cached;
}

export function setDensity(d: Density) {
  const was = read();
  if (d === "focus" && was !== "focus") try { window.localStorage.setItem(BACK, was); } catch { /* kept for this visit */ }
  cached = d;
  try { window.localStorage.setItem(KEY, d); window.localStorage.removeItem(OLD_FOCUS); } catch { /* kept for this visit only */ }
  listeners.forEach((f) => f());
}

// Leaving Focus goes back to the size used before it.
export function leaveFocus() {
  let back: string | null = null;
  try { back = window.localStorage.getItem(BACK); } catch { /* storage blocked */ }
  setDensity(back === "full" ? "full" : "compact");
}

// F steps through the three: Full, Compact, Focus, then Full again.
export function nextDensity(d: Density): Density {
  return d === "full" ? "compact" : d === "compact" ? "focus" : "full";
}

export function useDensity(): Density {
  return useSyncExternalStore(
    (f) => { listeners.add(f); return () => listeners.delete(f); },
    read,
    () => DEFAULT,
  );
}

// The Layers panel stays open beside the map (pinned) or opens over it and closes on a click on the map.
const PIN_KEY = "wm.layersPinned";
const pinListeners = new Set<() => void>();
let pinned: boolean | null = null;
function readPin(): boolean {
  if (pinned === null) { try { pinned = window.localStorage.getItem(PIN_KEY) === "1"; } catch { pinned = false; } }
  return pinned;
}
export function setLayersPinned(on: boolean) {
  pinned = on;
  try { window.localStorage.setItem(PIN_KEY, on ? "1" : "0"); } catch { /* kept for this visit only */ }
  pinListeners.forEach((f) => f());
}
export function useLayersPinned(): boolean {
  return useSyncExternalStore((f) => { pinListeners.add(f); return () => pinListeners.delete(f); }, readPin, () => false);
}
