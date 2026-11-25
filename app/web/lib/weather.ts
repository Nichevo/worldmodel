// The map's weather layers: forecast maps drawn by this app's server from NOAA GFS (one picture per field
// and forecast hour), RainViewer's rain radar (read straight from RainViewer), and satellite clouds.
// The forecast hour is shared by every map panel, like the map's time window.

import { useEffect, useState, useSyncExternalStore } from "react";
import type { RasterTiles } from "@/components/WorldMap";
import { get } from "@/lib/api";

export type WeatherField = "temp" | "rain" | "cloud" | "wind" | "pressure";
export type WeatherStatus = {
  on: boolean; detail: string; days: number; run: string | null; run_time: string | null;
  steps: number[]; step_hours: number; all_steps: number[];
  fetching: { run: string; step: number; done: number; of: number } | null; note: string; error: string;
  fields: Record<WeatherField, { label: string; unit: string }>;
  legends: Record<Exclude<WeatherField, "pressure">, [number, string][]>;
  isobar_hpa: number; mb_per_run: number;
};
export type WeatherAt = {
  step: number; valid?: string; note?: string;
  values: Partial<Record<WeatherField | "u" | "v" | "from_deg", number | null>>;
};
export type PlaceForecast = {
  lat: number; lon: number; source: string; source_name?: string; link?: string; error?: string;
  timezone?: string; utc_offset_s?: number; elevation?: number | null;
  now?: { time: string | null; temp: number | null; feels: number | null; humidity: number | null; rain: number | null; cloud: number | null;
    wind: number | null; gust: number | null; from_deg: number | null; pressure: number | null; words: string | null };
  hourly?: { time: string[]; temp: (number | null)[]; rain: (number | null)[]; rain_chance: (number | null)[]; cloud: (number | null)[];
    wind: (number | null)[]; from_deg: (number | null)[] };
  daily?: { date: string; high: number | null; low: number | null; rain: number | null; rain_chance: number | null; wind: number | null;
    from_deg: number | null; words: string | null; sunrise: string | null; sunset: string | null }[];
};

// Map layer letters (see MAP_LAYERS in workspace.ts). Forecast layers follow the forecast hour.
export const WX_LETTERS: Record<string, WeatherField | "radar" | "satellite"> = {
  "!": "temp", "$": "rain", "(": "cloud", ")": "wind", ";": "pressure", "@": "radar", ":": "satellite",
};
const FORECAST_ORDER: WeatherField[] = ["temp", "cloud", "rain", "wind", "pressure"];
export const hasWeather = (letters: string) => [...letters].some((l) => l in WX_LETTERS);
export const forecastFields = (letters: string): WeatherField[] =>
  FORECAST_ORDER.filter((f) => [...letters].some((l) => WX_LETTERS[l] === f));

// ----------------------------------------------------------------------------- shared forecast hour
let step: number | null = null; // hours after the run; null = the step nearest now
const subs = new Set<() => void>();
export function setWeatherStep(s: number | null) { step = s; subs.forEach((f) => f()); }
export function useWeatherStep(): number | null {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => step, () => null);
}

// The step nearest now among those on this PC.
export function nowStep(st: WeatherStatus): number | null {
  if (!st.run_time || !st.steps.length) return null;
  const h = (Date.now() - Date.parse(st.run_time)) / 3_600_000;
  return st.steps.reduce((best, s) => (Math.abs(s - h) < Math.abs(best - h) ? s : best), st.steps[0]);
}
export const validTime = (st: WeatherStatus, s: number) => new Date(Date.parse(st.run_time ?? "") + s * 3_600_000);

// ----------------------------------------------------------------------------- status (shared, refreshed while on)
let status: WeatherStatus | null = null;
let statusAt = 0;
let loading: Promise<WeatherStatus> | null = null;
const statusSubs = new Set<() => void>();
function loadStatus(): Promise<WeatherStatus> {
  if (!loading) {
    loading = get<WeatherStatus>("/weather/status")
      .then((s) => { status = s; statusAt = Date.now(); statusSubs.forEach((f) => f()); return s; })
      .finally(() => { loading = null; });
  }
  return loading;
}
// The forecast run while a weather layer is on: asked again every 20 seconds while a run downloads, else every 10 minutes.
export function useWeatherStatus(on: boolean): { status: WeatherStatus | null; error: string | null } {
  const [, tick] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!on) return;
    const f = () => tick((n) => n + 1);
    statusSubs.add(f);
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const go = () => {
      const fresh = status && Date.now() - statusAt < 15_000;
      (fresh ? Promise.resolve(status!) : loadStatus())
        .then((s) => { if (!live) return; setError(null); timer = setTimeout(go, s.fetching || !s.run ? 20_000 : 600_000); })
        .catch((e) => { if (!live) return; setError(String(e.message || e)); timer = setTimeout(go, 60_000); });
    };
    go();
    return () => { live = false; clearTimeout(timer); statusSubs.delete(f); };
  }, [on]);
  return { status: on ? status : null, error };
}

// ----------------------------------------------------------------------------- RainViewer radar
type RadarFrames = { host: string; frames: { time: number; path: string }[] };
let radar: RadarFrames | null = null;
let radarAt = 0;
export function useRadar(on: boolean): { radar: RadarFrames | null; error: string | null } {
  const [got, setGot] = useState<RadarFrames | null>(radar);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!on) return;
    let live = true;
    const go = () => {
      if (radar && Date.now() - radarAt < 4 * 60_000) { setGot(radar); return; }
      fetch("https://api.rainviewer.com/public/weather-maps.json")
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`RainViewer answered ${r.status}`))))
        .then((d: { host: string; radar?: { past?: { time: number; path: string }[] } }) => {
          radar = { host: d.host, frames: d.radar?.past ?? [] };
          radarAt = Date.now();
          if (live) { setGot(radar); setError(null); }
        })
        .catch((e) => live && setError(`Rain radar did not load (${String(e.message || e)}).`));
    };
    go();
    const t = setInterval(go, 5 * 60_000);
    return () => { live = false; clearInterval(t); };
  }, [on]);
  return { radar: on ? got : null, error };
}

// ----------------------------------------------------------------------------- picture layers
const origin = () => (typeof location !== "undefined" ? location.origin : "");
const OPACITY: Record<WeatherField, number> = { temp: 0.75, rain: 0.95, cloud: 0.9, wind: 0.85, pressure: 1 };

export function weatherRasters(letters: string, st: WeatherStatus | null, s: number | null, rad: RadarFrames | null): RasterTiles[] {
  const out: RasterTiles[] = [];
  const fields = forecastFields(letters);
  const at = st && s !== null && st.steps.includes(s) ? s : st ? nowStep(st) : null;
  if (st?.on && st.run && at !== null) {
    for (const f of fields) {
      out.push({ tiles: `${origin()}/api/v1/weather/tiles/${f}/${st.run}/${at}/{z}/{x}/{y}.png`, over: true, opacity: OPACITY[f],
        maxzoom: st.detail === "0p25" ? 8 : 7, attribution: "Forecast: NOAA GFS" });
    }
  }
  if (letters.includes(":") && st?.on !== false) {
    out.push({ tiles: `${origin()}/api/v1/weather/clouds/{z}/{x}/{y}.png`, over: true, opacity: 0.9, maxzoom: 7,
      attribution: "Clouds: NASA GIBS (Himawari, GOES)" });
  }
  const last = rad?.frames.at(-1);
  if (letters.includes("@") && rad && last) {
    out.push({ tiles: `${rad.host}${last.path}/256/{z}/{x}/{y}/2/1_1.png`, over: true, opacity: 0.85, maxzoom: 7, attribution: "Radar: RainViewer" });
  }
  return out;
}

// ----------------------------------------------------------------------------- words and numbers
const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
export const compass = (deg: number | null | undefined) => (deg === null || deg === undefined ? "" : COMPASS[Math.round(deg / 22.5) % 16]);
export const fmtHour = (d: Date) =>
  d.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: d.getMinutes() ? "2-digit" : undefined });
export function fromNow(d: Date): string {
  const h = Math.round((d.getTime() - Date.now()) / 3_600_000);
  if (Math.abs(h) < 1) return "now";
  const a = Math.abs(h);
  const span = a < 48 ? `${a} h` : `${Math.round(a / 24)} days`;
  return h > 0 ? `in ${span}` : `${span} ago`;
}
export const r1 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : (Math.round(v * 10) / 10).toLocaleString());
export const r0 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : Math.round(v).toLocaleString());

export function atLine(a: WeatherAt | null): string {
  const v = a?.values;
  if (!v || !Object.keys(v).length) return "";
  const parts = [];
  if (v.temp != null) parts.push(`${r1(v.temp)} °C`);
  if (v.rain != null) parts.push(v.rain < 0.05 ? "dry" : `rain ${r1(v.rain)} mm/h`);
  if (v.cloud != null) parts.push(`cloud ${r0(v.cloud)}%`);
  if (v.wind != null) parts.push(`wind ${r0(v.wind)} km/h${v.from_deg != null ? ` from the ${compass(v.from_deg)}` : ""}`);
  if (v.pressure != null) parts.push(`${r0(v.pressure)} hPa`);
  return parts.join(" · ");
}

// A place's forecast, kept a while per place.
const points = new Map<string, Promise<PlaceForecast>>();
export function placeForecast(lat: number, lon: number): Promise<PlaceForecast> {
  const k = `${lat.toFixed(2)},${lon.toFixed(2)}`;
  if (!points.has(k)) {
    if (points.size > 100) points.clear();
    const p = get<PlaceForecast>("/weather/point", { lat: lat.toFixed(3), lon: lon.toFixed(3) });
    p.catch(() => points.delete(k));
    points.set(k, p);
    setTimeout(() => points.delete(k), 20 * 60_000);
  }
  return points.get(k)!;
}

// An hourly time from the forecast as a Date: Open-Meteo gives the place's own clock (no zone),
// MET Norway gives UTC.
export function hourDate(f: PlaceForecast, t: string): Date {
  return new Date(Date.parse(`${t}:00Z`) - (f.source === "open_meteo" ? (f.utc_offset_s ?? 0) * 1000 : 0));
}
