"use client";

import { useSyncExternalStore } from "react";
import { api, type Grade, type Indicator, type QualityShow } from "@/lib/api";

// Stars set in this browser session, shared by every drop-down at once (the server keeps them;
// this only saves waiting for a reload of the indicator list).
let stars: Record<string, boolean> = {};
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => { listeners.add(fn); return () => listeners.delete(fn); };

export function useStars(): Record<string, boolean> {
  return useSyncExternalStore(subscribe, () => stars, () => stars);
}

export function isStarred(i: Indicator, local: Record<string, boolean>): boolean {
  return local[i.indicator_id] ?? Boolean(i.starred);
}

export async function setStar(id: string, on: boolean): Promise<void> {
  stars = { ...stars, [id]: on };
  listeners.forEach((f) => f());
  try {
    await api.setQuality(id, { starred: on });
  } catch {
    stars = { ...stars, [id]: !on };
    listeners.forEach((f) => f());
  }
}

const ORDER: Grade[] = ["A", "B", "C", "D"];

// Whether an indicator passes the Show filter: starred ones always do.
export function passes(i: Indicator, show: QualityShow, starred: boolean): boolean {
  if (starred) return true;
  if (show === "starred") return false;
  if (show === "all" || !i.grade) return true;
  return ORDER.indexOf(i.grade) <= ORDER.indexOf(show as Grade);
}

export const SHOW_TEXT: Record<QualityShow, string> = {
  starred: "Starred only", A: "A only", B: "A and B", C: "Up to C", all: "Everything",
};
