// The map's weather layers: forecast maps drawn by this app's server from NOAA GFS (one picture per field
// and forecast hour), RainViewer's rain radar (read straight from RainViewer), and satellite clouds.
// The forecast hour is shared by every map panel, like the map's time window.

import { useEffect, useState, useSyncExternalStore } from "react";
import type { RasterTiles } from "@/components/WorldMap";
import { get } from "@/lib/api";

export type WeatherField = "temp" | "rain" | "cloud" | "wind" | "pressure" | "waves" | "swell";
type Fetching = { run: string; step: number; done: number; of: number } | null;
export type WaveStatus = {
  on: boolean; run: string | null; run_time: string | null; steps: number[]; all_steps: number[];
  fetching: Fetching; note: string; error: string; mb_per_run: number;
};
export type WeatherStatus = {
  on: boolean; model: "gfs" | "ecmwf"; model_name: string; detail: string; days: number; run: string | null; run_time: string | null;
  steps: number[]; step_hours: number; all_steps: number[];
  fetching: Fetching; note: string; error: string;
  fields: Record<WeatherField, { label: string; unit: string }>;
  legends: Record<Exclude<WeatherField, "pressure">, [number, string][]>;
  isobar_hpa: number; mb_per_run: number; waves: WaveStatus;
};
export type WeatherAt = {
  step: number; valid?: string | null; note?: string;
  values: Partial<Record<WeatherField | "u" | "v" | "from_deg" | "wave_period" | "wave_from" | "wind_waves" | "swell_period" | "swell_from", number | null>>;
};
export type RainSoon = { now: boolean; starts: string | null; ends: string | null; mm?: number; hours: number };
export type AirNow = {
  error?: string; source_name?: string; link?: string; timezone?: string;
  now?: { time: string | null; us_aqi: number | null; european_aqi: number | null; pm2_5: number | null; pm10: number | null; dust: number | null;
    ozone: number | null; nitrogen_dioxide: number | null; uv_index: number | null; words: string | null };
  days?: { date: string; us_aqi: number; hour: string; words: string }[];
};
export type ModelsAgree = {
  error?: string; source_name?: string;
  days?: { date: string; models: { model: string; name: string; high: number | null; rain: number | null }[];
    high_lo: number; high_hi: number; rain_lo: number | null; rain_hi: number | null; n: number; agree: boolean; why: string }[];
};
export type PlaceForecast = {
  lat: number; lon: number; source: string; source_name?: string; link?: string; error?: string;
  timezone?: string; utc_offset_s?: number; elevation?: number | null;
  rain_soon?: RainSoon | null;
  now?: { time: string | null; temp: number | null; feels: number | null; humidity: number | null; rain: number | null; cloud: number | null;
    wind: number | null; gust: number | null; from_deg: number | null; pressure: number | null; words: string | null };
  hourly?: { time: string[]; temp: (number | null)[]; rain: (number | null)[]; rain_chance: (number | null)[]; cloud: (number | null)[];
    wind: (number | null)[]; from_deg: (number | null)[] };
  daily?: { date: string; high: number | null; low: number | null; rain: number | null; rain_chance: number | null; wind: number | null;
    from_deg: number | null; words: string | null; sunrise: string | null; sunset: string | null }[];
};

// Map layer letters (see MAP_LAYERS in workspace.ts). Forecast layers follow the forecast hour.
export const WX_LETTERS: Record<string, WeatherField | "radar" | "satellite" | "windlines"> = {
  "!": "temp", "$": "rain", "(": "cloud", ")": "wind", ";": "pressure", "@": "radar", ":": "satellite",
  "=": "waves", "[": "swell", "^": "windlines",
};
const FORECAST_ORDER: WeatherField[] = ["temp", "waves", "swell", "cloud", "rain", "wind", "pressure"];
export const WAVE_FIELDS: WeatherField[] = ["waves", "swell"];
export const hasWeather = (letters: string) => [...letters].some((l) => l in WX_LETTERS);
export const hasWaves = (letters: string) => letters.includes("=") || letters.includes("[");
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
let wavesWanted = 0; // map panels with a wave layer on: the server then fetches the wave model too
function loadStatus(): Promise<WeatherStatus> {
  if (!loading) {
    loading = get<WeatherStatus>("/weather/status", wavesWanted > 0 ? { waves: "true" } : {})
      .then((s) => { status = s; statusAt = Date.now(); statusSubs.forEach((f) => f()); return s; })
      .finally(() => { loading = null; });
  }
  return loading;
}
// The forecast run while a weather layer is on: asked again every 20 seconds while a run downloads, else every 10 minutes.
export function useWeatherStatus(on: boolean, waves = false): { status: WeatherStatus | null; error: string | null } {
  const [, tick] = useState(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!on || !waves) return;
    wavesWanted += 1;
    statusAt = 0; // ask again now, with the waves
    return () => { wavesWanted -= 1; };
  }, [on, waves]);
  useEffect(() => {
    if (!on) return;
    const f = () => tick((n) => n + 1);
    statusSubs.add(f);
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const go = () => {
      const fresh = status && Date.now() - statusAt < 15_000;
      (fresh ? Promise.resolve(status!) : loadStatus())
        .then((s) => {
          if (!live) return;
          setError(null);
          const busy = s.fetching || !s.run || (wavesWanted > 0 && s.waves.on && (s.waves.fetching || !s.waves.run));
          timer = setTimeout(go, busy ? 20_000 : 600_000);
        })
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
const OPACITY: Record<WeatherField, number> = { temp: 0.75, rain: 0.95, cloud: 0.9, wind: 0.85, pressure: 1, waves: 0.85, swell: 0.85 };

// The wave model's step nearest the forecast hour picked on the weather bar (its runs and steps are its own).
export function waveStep(st: WeatherStatus | null, s: number | null): number | null {
  const w = st?.waves;
  if (!st || !w?.run_time || !w.steps.length) return null;
  const at = st.run_time && s !== null ? Date.parse(st.run_time) + s * 3_600_000 : Date.now();
  const h = (at - Date.parse(w.run_time)) / 3_600_000;
  return w.steps.reduce((best, x) => (Math.abs(x - h) < Math.abs(best - h) ? x : best), w.steps[0]);
}
export const shownStep = (st: WeatherStatus | null, s: number | null) => (st && s !== null && st.steps.includes(s) ? s : st ? nowStep(st) : null);

export function weatherRasters(letters: string, st: WeatherStatus | null, s: number | null, rad: RadarFrames | null): RasterTiles[] {
  const out: RasterTiles[] = [];
  const fields = forecastFields(letters);
  const at = shownStep(st, s);
  const ws = waveStep(st, at);
  for (const f of fields) {
    if (WAVE_FIELDS.includes(f)) {
      if (st?.on && st.waves.on && st.waves.run && ws !== null) {
        out.push({ tiles: `${origin()}/api/v1/weather/tiles/${f}/${st.waves.run}/${ws}/{z}/{x}/{y}.png`, over: true, opacity: OPACITY[f],
          maxzoom: 8, attribution: "Waves: NOAA GFS-Wave" });
      }
    } else if (st?.on && st.run && at !== null) {
      out.push({ tiles: `${origin()}/api/v1/weather/tiles/${f}/${st.run}/${at}/{z}/{x}/{y}.png`, over: true, opacity: OPACITY[f],
        maxzoom: st.detail === "0p25" ? 8 : 7, attribution: `Forecast: ${st.model_name}${st.model === "ecmwf" ? " (CC BY 4.0)" : ""}` });
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
  if (v.waves != null) parts.push(`waves ${r1(v.waves)} m${v.wave_period != null ? ` every ${r0(v.wave_period)} s` : ""}${v.wave_from != null ? ` from the ${compass(v.wave_from)}` : ""}`);
  if (v.swell != null) parts.push(`swell ${r1(v.swell)} m${v.swell_period != null ? ` every ${r0(v.swell_period)} s` : ""}${v.swell_from != null ? ` from the ${compass(v.swell_from)}` : ""}`);
  return parts.join(" · ");
}

// US air quality index bands (EPA).
export function aqiWords(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "";
  return v <= 50 ? "good" : v <= 100 ? "moderate" : v <= 150 ? "unhealthy for sensitive groups" : v <= 200 ? "unhealthy" : v <= 300 ? "very unhealthy" : "hazardous";
}
export const aqiColour = (v: number) => (v <= 50 ? "#40c057" : v <= 100 ? "#fcc419" : v <= 150 ? "#fd7e14" : v <= 200 ? "#e03131" : v <= 300 ? "#862e9c" : "#5c0f2e");

// windy.com at a place (Leaflet zoom is one more than MapLibre's for the same view).
export const windyLink = (lat: number, lon: number, zoom = 8) => `https://www.windy.com/?${lat.toFixed(3)},${lon.toFixed(3)},${Math.max(3, Math.min(17, Math.round(zoom)))}`;

// A place's air now and the models side by side, kept a while per place.
function kept<T>(cache: Map<string, Promise<T>>, path: string, lat: number, lon: number): Promise<T> {
  const k = `${lat.toFixed(2)},${lon.toFixed(2)}`;
  if (!cache.has(k)) {
    if (cache.size > 100) cache.clear();
    const p = get<T>(path, { lat: lat.toFixed(3), lon: lon.toFixed(3) });
    p.catch(() => cache.delete(k));
    cache.set(k, p);
    setTimeout(() => cache.delete(k), 30 * 60_000);
  }
  return cache.get(k)!;
}
const airs = new Map<string, Promise<AirNow>>();
const modelSets = new Map<string, Promise<ModelsAgree>>();
export const placeAir = (lat: number, lon: number) => kept(airs, "/weather/air", lat, lon);
export const placeModels = (lat: number, lon: number) => kept(modelSets, "/weather/models", lat, lon);

// Forecast accuracy: which model has been most right in each scored city (last 60 days).
export type SkillModel = { model: string; name: string; temp: number | null; wind: number | null; rain: number | null; n: number;
  airport_share: number; wet_hours: number; mean_rank: number | null };
export type SkillCity = { id: string; name: string; country: string; region: string; icao: string | null; lat: number; lon: number;
  best: string | null; best_name: string | null; models: SkillModel[] };
export type SkillTable = { lead: "day1" | "day2"; cities: SkillCity[]; models?: Record<string, string>;
  regions: { region: string; cities: number; wins: { model: string; name: string; cities: number }[] }[];
  last_round: string | null; days: number; rounds: number; running: boolean; note: string; error: string };
export type SkillNear = { city: string | null; city_id?: string; km?: number; best?: string; best_name?: string; temp?: number | null;
  wind?: number | null; rain?: number | null; n?: number; airport_share?: number; order?: string[]; days: number };
// One colour per model, the same on the map, the leaderboard and the forecast card.
export const MODEL_COLOURS: Record<string, string> = {
  best_match: "#868e96", ecmwf_ifs025: "#1c7ed6", gfs_seamless: "#e03131", icon_seamless: "#2f9e44", ukmo_seamless: "#7048e8",
  gem_seamless: "#f08c00", jma_seamless: "#c2255c", meteofrance_seamless: "#0c8599",
};
export const SKILL_ENOUGH_DAYS = 21; // until about three weeks are in, the ranking is shown as early
const skillNear = new Map<string, Promise<SkillNear>>();
export const placeSkill = (lat: number, lon: number) => kept(skillNear, "/weather/skill/near", lat, lon);

// The wind on a 1° grid for the moving wind lines (u and v in m/s).
export type WindGrid = { lat0: number; lon0: number; d: number; nj: number; ni: number; u: Float32Array; v: Float32Array };
const grids = new Map<string, Promise<WindGrid>>();
export function windGrid(run: string, step: number): Promise<WindGrid> {
  const k = `${run}/${step}`;
  if (!grids.has(k)) {
    if (grids.size > 12) grids.clear();
    const p = get<{ lat0: number; lon0: number; d: number; nj: number; ni: number; scale: number; u: string; v: string }>(`/weather/wind/${run}/${step}`)
      .then((g) => {
        const unpack = (b64: string) => {
          const bin = atob(b64);
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          const ints = new Int16Array(bytes.buffer);
          const out = new Float32Array(ints.length);
          for (let i = 0; i < ints.length; i++) out[i] = ints[i] * g.scale;
          return out;
        };
        return { lat0: g.lat0, lon0: g.lon0, d: g.d, nj: g.nj, ni: g.ni, u: unpack(g.u), v: unpack(g.v) };
      });
    p.catch(() => grids.delete(k));
    grids.set(k, p);
  }
  return grids.get(k)!;
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
