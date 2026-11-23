"use client";

import type { Tour } from "@/lib/api";

// The guided tour in progress: kept in this browser only (localStorage), so it carries on across
// pages and a reload. The tour bar (components/TourBar) reads it and follows each stop.
export type TourState = { tour: Tour; step: number };
const KEY = "worldmodel.tour";
const EVENT = "worldmodel-tour";

export function readTour(): TourState | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as TourState) : null;
  } catch {
    return null;
  }
}

export function setTour(state: TourState | null) {
  try {
    if (state) localStorage.setItem(KEY, JSON.stringify(state));
    else localStorage.removeItem(KEY);
  } catch {}
  window.dispatchEvent(new Event(EVENT));
}

export function onTour(fn: () => void): () => void {
  window.addEventListener(EVENT, fn);
  window.addEventListener("storage", fn);
  return () => { window.removeEventListener(EVENT, fn); window.removeEventListener("storage", fn); };
}
