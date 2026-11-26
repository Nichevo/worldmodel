// The map page remembers what it showed last (panels, layers, years, pins: the whole address)
// and where each map was looking, so leaving for another page and coming back via the Map link
// opens it as it was. Kept in this browser only: localStorage ("always", the default) or
// sessionStorage ("visit": until the browser closes); "off" keeps nothing (Settings > Map).
import type { Camera } from "@/lib/camera";

export type RememberMode = "always" | "visit" | "off";

const MODE = "wm.mapRemember"; // a copy of the setting, readable before the settings have loaded
const QUERY = "wm.mapLast";
const CAMS = "wm.mapCameras";

function readMode(): RememberMode {
  try {
    const m = window.localStorage.getItem(MODE);
    return m === "visit" || m === "off" ? m : "always";
  } catch { return "off"; }
}

function store(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    const m = readMode();
    return m === "always" ? window.localStorage : m === "visit" ? window.sessionStorage : null;
  } catch { return null; }
}

/** Called with the saved setting once it is known: a change of mode drops what the old one kept. */
export function setRememberMode(mode: RememberMode | undefined) {
  if (typeof window === "undefined") return;
  const m: RememberMode = mode === "visit" || mode === "off" ? mode : "always";
  try {
    const was = window.localStorage.getItem(MODE);
    if (was === m) return;
    if (was !== null) forgetMap(); // first time: nothing kept under another mode yet
    window.localStorage.setItem(MODE, m);
  } catch { /* storage blocked: nothing is remembered */ }
}

/** The address of the map as last seen, or null. */
export function rememberedQuery(): string | null {
  try { return store()?.getItem(QUERY) || null; } catch { return null; }
}

export function rememberQuery(q: string) {
  try { store()?.setItem(QUERY, q); } catch { /* full or blocked: kept for this page only */ }
}

/** Where each map panel (by panel id) was looking. */
export function rememberedCameras(): Map<string, Camera> {
  const out = new Map<string, Camera>();
  try {
    const raw = JSON.parse(store()?.getItem(CAMS) || "{}") as Record<string, unknown>;
    for (const [id, c] of Object.entries(raw)) {
      const cam = c as Camera;
      if (Array.isArray(cam?.center) && cam.center.length === 2 && cam.center.every(Number.isFinite) && Number.isFinite(cam.zoom))
        out.set(id, { center: [cam.center[0], cam.center[1]], zoom: cam.zoom });
    }
  } catch { /* nothing usable kept */ }
  return out;
}

let pending: ReturnType<typeof setTimeout> | null = null;
/** Saves the cameras a little after the last move, not on every frame of a drag. */
export function rememberCameras(cams: Map<string, Camera>) {
  if (pending) clearTimeout(pending);
  pending = setTimeout(() => {
    pending = null;
    const round = (c: Camera): Camera => ({ center: [+c.center[0].toFixed(3), +c.center[1].toFixed(3)], zoom: +c.zoom.toFixed(2) });
    try { store()?.setItem(CAMS, JSON.stringify(Object.fromEntries([...cams].map(([k, c]) => [k, round(c)])))); } catch { /* blocked */ }
  }, 400);
}

export function forgetMap() {
  if (pending) { clearTimeout(pending); pending = null; }
  for (const s of [() => window.localStorage, () => window.sessionStorage]) {
    try { s().removeItem(QUERY); s().removeItem(CAMS); } catch { /* blocked */ }
  }
}
