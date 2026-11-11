// The Map's "World in year" layer: its own year (kept in Settings, so it is there next time)
// and the states alive that year, with each state's shape fetched once and kept.

import { useEffect, useState, useSyncExternalStore } from "react";
import { api, type GeoFeature } from "@/lib/api";
import { saveSettings, useSettings } from "@/lib/settings";
import { hueColor, yl } from "@/lib/long";

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
