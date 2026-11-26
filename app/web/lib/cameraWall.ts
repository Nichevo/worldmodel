// The camera wall: cameras picked from the map's Cameras layer, watched side by side. Kept in
// this browser only (a per-viewer convenience); every map on the page shares the one wall.

import { useSyncExternalStore } from "react";
import type { CameraProps } from "@/components/CameraView";

export type WallCamera = CameraProps & { lng?: number; lat?: number };
export const WALL_MAX = 12;
const KEY = "wm-camera-wall";
const OPEN = "wm-camera-wall-open";

let wall: WallCamera[] | null = null;
let open = true;
const listeners = new Set<() => void>();
const EMPTY: WallCamera[] = [];

function load(): WallCamera[] {
  if (wall) return wall;
  wall = [];
  if (typeof window === "undefined") return wall;
  try {
    const got = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    if (Array.isArray(got)) wall = got.filter((c) => c && typeof c.id === "string").slice(0, WALL_MAX);
    open = window.localStorage.getItem(OPEN) !== "0";
  } catch { /* storage blocked: the wall lasts this visit only */ }
  return wall;
}

function save(next: WallCamera[]) {
  wall = next;
  try { window.localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* storage blocked */ }
  listeners.forEach((f) => f());
}

function subscribe(f: () => void) {
  listeners.add(f);
  return () => { listeners.delete(f); };
}

export function useCameraWall(): WallCamera[] {
  return useSyncExternalStore(subscribe, load, () => EMPTY);
}

export function useCameraWallOpen(): boolean {
  return useSyncExternalStore(subscribe, () => { load(); return open; }, () => false);
}

export function showCameraWall(v: boolean) {
  open = v;
  try { window.localStorage.setItem(OPEN, v ? "1" : "0"); } catch { /* storage blocked */ }
  listeners.forEach((f) => f());
}

export function onWall(id: string): boolean {
  return load().some((c) => c.id === id);
}

// Add a camera (the oldest drops off past WALL_MAX), or take it off if it is already there.
export function toggleWall(cam: WallCamera): "added" | "removed" {
  const cur = load();
  if (cur.some((c) => c.id === cam.id)) {
    save(cur.filter((c) => c.id !== cam.id));
    return "removed";
  }
  // Windy picture links expire after ten minutes: the wall asks Windy for a fresh one instead.
  const keep: WallCamera = { ...cam, image: cam.source === "windy" ? undefined : cam.image };
  save([...cur, keep].slice(-WALL_MAX));
  showCameraWall(true);
  return "added";
}

export function moveOnWall(id: string, by: number) {
  const cur = [...load()];
  const i = cur.findIndex((c) => c.id === id);
  const j = i + by;
  if (i < 0 || j < 0 || j >= cur.length) return;
  [cur[i], cur[j]] = [cur[j], cur[i]];
  save(cur);
}

export function clearWall() {
  save([]);
}
