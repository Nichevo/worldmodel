// The user's settings, shared by every component: loaded once from the API,
// defaults until then (or if the API is down), and updated in place on save.

import { useSyncExternalStore } from "react";
import { api, type Settings } from "@/lib/api";

export const DEFAULT_SETTINGS: Settings = {
  click_mode: "popup",
  hover_sparkline: true,
  popup_tabs: true,
  side_panel: true,
  disk_limit_gb: 100,
  pictures_limit_gb: 2,
  numbeo_daily: 20,
  wikipedia_countries_daily: 20,
  wikipedia_cities_daily: 10,
  wikipedia_background: true,
  history_paused: false,
  history_retention_days: 0,
  problem_banner: true,
  events_on_charts: true,
  party_colours: false,
  party_office: "government",
  event_kinds: "recession,crisis,coup,conflict,disaster,sport,notable,user",
  disaster_min_deaths: 100,
};

let current: Settings = DEFAULT_SETTINGS;
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

function set(next: Settings) {
  current = next;
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  loading ??= api.settings().then((r) => set(r.settings)).catch(() => { loading = null; });
  return () => { listeners.delete(l); };
}

export function useSettings(): Settings {
  return useSyncExternalStore(subscribe, () => current, () => DEFAULT_SETTINGS);
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  set({ ...current, ...patch }); // show the change at once; the API's answer is the final word
  const r = await api.saveSettings(patch);
  set(r.settings);
  return r.settings;
}
