// The Map's "World in year" layer: its own year (kept in Settings, so it is there next time)
// and the states alive that year, with each state's shape fetched once and kept.

import { useEffect, useState, useSyncExternalStore } from "react";
import type { MapMark } from "@/components/WorldMap";
import { api, type GeoFeature, type LongEvent } from "@/lib/api";
import { saveSettings, useSettings } from "@/lib/settings";
import { hueColor, KIND_WORD, kindColor, mapKinds, yl } from "@/lib/long";

let year: number | null = null;
const subs = new Set<() => void>();
let saveTimer: ReturnType<typeof setTimeout> | undefined;

export function setMapYear(y: number) {
  year = Math.max(-3400, Math.min(2024, Math.round(y))) || 1;
  subs.forEach((f) => f());
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveSettings({ map_history_year: year! }).catch(() => {}), 1000);
}

export function useMapYear(): number {
  const s = useSettings();
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; },
    () => year ?? s.map_history_year ?? 1700, () => s.map_history_year ?? 1700);
}

const geometries = new Map<string, GeoJSON.Geometry>();
const years = new Map<number, Promise<GeoFeature[]>>();

async function worldIn(y: number): Promise<GeoFeature[]> {
  const fc = await api.longWorld(y, false);
  const missing = fc.features.map((f) => f.properties.key as string).filter((k) => !geometries.has(k));
  for (let i = 0; i < missing.length; i += 400) {
    const got = await api.longShapes(missing.slice(i, i + 400));
    for (const [k, g] of Object.entries(got)) geometries.set(k, g);
  }
  return fc.features.filter((f) => geometries.has(f.properties.key as string))
    .map((f) => ({ ...f, geometry: geometries.get(f.properties.key as string)! }));
}

// The states alive in a year as map areas (coloured by the empire they belong to), or null when off.
export function useWorldIn(on: boolean, y: number) {
  const [areas, setAreas] = useState<{ key: string; data: GeoJSON.FeatureCollection; count: number } | null>(null);
  useEffect(() => {
    if (!on) { setAreas(null); return; }
    let live = true;
    if (!years.has(y)) {
      if (years.size > 40) years.clear();
      const p = worldIn(y);
      p.catch(() => years.delete(y));
      years.set(y, p);
    }
    years.get(y)!.then((feats) => {
      if (!live) return;
      setAreas({ key: `world:${y}`, count: feats.length, data: { type: "FeatureCollection", features: feats.map((f) => ({
        type: "Feature", geometry: f.geometry, properties: { ...f.properties, color: hueColor(f.properties.hue as number), opacity: 0.7,
          label: `${f.properties.label}<br/><span style="opacity:.7">World in ${yl(y)} (Cliopatria)</span>` } })) } });
    }).catch(() => live && setAreas(null));
    return () => { live = false; };
  }, [on, y]);
  return areas;
}

// Events and beginnings around the year on a World-in-year map: the kinds picked in
// Settings (history_map_groups), from history_map_window years either side, the best-known
// first. Fetched a moment after the year stops changing (Play moves it many times a second).
const eventCache = new Map<string, Promise<LongEvent[]>>();

export function useYearEvents(on: boolean, y: number) {
  const s = useSettings();
  const groups = s.history_map_groups ?? "war,built,belief,city";
  const win = s.history_map_window ?? 25;
  const [events, setEvents] = useState<LongEvent[]>([]);
  useEffect(() => {
    const kinds = mapKinds(groups);
    if (!on || !kinds.length) { setEvents([]); return; }
    let live = true;
    const t = setTimeout(() => {
      const key = `${y}|${win}|${groups}|${s.history_event_min_links ?? 5}`;
      if (!eventCache.has(key)) {
        if (eventCache.size > 80) eventCache.clear();
        const p = api.longEvents({ start: y - win, end: y + win, kind: kinds.join(","), limit: 300 });
        p.catch(() => eventCache.delete(key));
        eventCache.set(key, p);
      }
      eventCache.get(key)!.then((ev) => live && setEvents(ev)).catch(() => live && setEvents([]));
    }, 150);
    return () => { live = false; clearTimeout(t); };
  }, [on, y, win, groups, s.history_event_min_links]);
  return { events, window: win, groups };
}

const esc = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Marks for the map: faded the further from the year, bigger for the better known (or the
// deadlier), with names written beside the best-known few.
export function yearMarks(events: LongEvent[], y: number, win: number, labels: number): MapMark[] {
  const placed = events.filter((e) => e.lat !== null && e.lon !== null);
  const fame = (e: LongEvent) => (e.links ?? (e.source_id === "typed_in" ? 60 : 0)) + Math.log10(1 + (e.deaths ?? 0)) * 10;
  const named = new Set([...placed].sort((a, b) => fame(b) - fame(a)).slice(0, labels).map((e) => e.event_id));
  return placed.map((e) => {
    const off = e.year > y ? e.year - y : Math.max(0, y - (e.end_year ?? e.year));
    const opacity = Math.max(0.3, 1 - (0.7 * off) / Math.max(1, win));
    const r = 3.5 + Math.min(5, Math.log10(1 + (e.links ?? 20)) * 2.2) + (e.deaths ? Math.min(2, Math.log10(1 + e.deaths) / 3) : 0);
    return {
      key: e.event_id, lng: e.lon!, lat: e.lat!, color: kindColor(e.kind), r, opacity,
      label: `<b>${esc(e.title)}</b><br/>${esc(KIND_WORD[e.kind] ?? e.kind)} · ${esc(e.when)}${e.place ? ` · ${esc(e.place)}` : ""}`
        + (e.deaths ? `<br/>about ${Math.round(e.deaths).toLocaleString("en")} deaths` : "") + "<br/><i>Click for more</i>",
      href: e.url ?? undefined,
      text: named.has(e.event_id) ? `${e.title.length > 34 ? `${e.title.slice(0, 32)}…` : e.title} ${yl(e.year)}` : undefined,
    };
  });
}
