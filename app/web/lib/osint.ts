// Detail from the OSINT communities: located fighting and unrest (UCDP, ACLED), war trackers
// (Oryx, claimed losses, DeepState, Kiel), internet outages, sanctions in force (OpenSanctions),
// military strength (Global Firepower) and arms deals (SIPRI). Types, API calls, chart options
// and the "Look closer" links that open other OSINT tools at a place and date.

import type { EChartsOption } from "echarts";
import { get } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar } from "@/lib/colors";
import { compact } from "@/lib/format";

export type OsintMonth = {
  month: string; ucdp_deaths: number | null; acled_deaths: number | null; civilians: number | null; violence: number; protests: number;
  riots: number; outages: number; outage_causes: string[]; sanctions_added: number; crisiswatch: string | null;
  crisiswatch_text: string | null; mismatch: string | null;
};
export type OsintCountry = { entity_id: string; since: string; months: OsintMonth[];
  has: { ucdp: boolean; acled: boolean; outages: boolean; sanctions: boolean; crisiswatch: boolean } };
export type OsintCwMonth = { month: string; countries: Record<string, { ucdp_deaths: number | null; acled_deaths: number | null;
  events: number; protests: number; outages: number; sanctions_added: number; mismatch: string | null }> };
export type LossLatest = { category: string; label: string } & Record<string, number | string | null>;
export type WarSummary = { id: string; name: string; short: string; sides: string[]; note: string; began: string | null;
  map: { west: number; south: number; east: number; north: number } | null;
  latest: { side: string; basis: string; count: number; day: string }[]; area: { day: string; km2: number } | null };
export type WarDetail = Omit<WarSummary, "latest" | "area"> & {
  oryx: Record<string, string> | null;
  series: { side: string; basis: "seen" | "claimed"; category: string; status: string; source: string; points: [string, number][] }[];
  latest: LossLatest[]; statuses: Record<string, Record<string, number>>; areas: [string, number][];
  front: { holder: string; land_of: string } | null;
  aid: { entity_id: string; name: string; year: number; military?: number; financial?: number; humanitarian?: number; total?: number }[];
  fighting: { month: string; source: string; deaths: number | null; events: number }[];
};
export type FrontLine = GeoJSON.FeatureCollection & { days?: string[] };
export type SanctionCell = { listed: number; added: number };
export type SanctionsNow = { loaded: boolean; authorities: { id: string; name: string; key: boolean }[]; authority_names: Record<string, string>;
  rows: { target: string; name: string; cells: Record<string, SanctionCell>; total: number; added: number }[];
  recent: SanctionListing[]; schemas: { schema: string; n: number }[] };
export type SanctionListing = { os_id: string; name: string; schema: string; targets: string[] | string; authorities: string[] | string;
  first_seen: string | null; url?: string };
export type MilitaryMeasure = { id: string; name: string; unit: string; group: string; group_name: string; also: string | null };
export type MilitaryValue = { value: number; edition: number; before: number | null; rank: number | null; of: number | null;
  also: { value: number; year: number } | null };
export type Military = { loaded: boolean; edition?: number; measures: MilitaryMeasure[];
  countries: { entity_id: string; name: string; values: Record<string, MilitaryValue> }[] };
export type ArmsPartner = { partner: string; tiv: number; deals: number; last: number | null };
export type Arms = { entity_id: string; since: number; suppliers: ArmsPartner[]; buyers: ArmsPartner[];
  deals: { supplier: string; recipient: string; ordered: number | null; delivered_from: number | null; delivered_to: number | null;
    weapon: string; description: string | null; number: number | null; tiv: number | null; status: string | null }[] };

export const osintApi = {
  country: (id: string, months = 24) => get<OsintCountry>(`/osint/country/${encodeURIComponent(id)}`, { months }),
  cwMonth: (month: string) => get<OsintCwMonth>("/osint/crisiswatch-month", { month }),
  wars: () => get<{ wars: WarSummary[] }>("/osint/wars"),
  war: (id: string) => get<WarDetail>(`/osint/wars/${encodeURIComponent(id)}`),
  front: (id: string, day?: string) => get<FrontLine>(`/osint/front/${encodeURIComponent(id)}`, { day }),
  events: (q: { west?: number; south?: number; east?: number; north?: number; days?: number; end?: string; kinds?: string; limit?: number }) =>
    get<GeoJSON.FeatureCollection & { count: number; loaded: boolean; newest?: string; from?: string; to?: string; capped?: boolean }>("/osint/events", q),
  sanctions: (schema?: string) => get<SanctionsNow>("/osint/sanctions", { schema }),
  sanctionsSearch: (q: string) => get<{ items: SanctionListing[] }>("/osint/sanctions/search", { q }),
  military: (entities: string[]) => get<Military>("/osint/military", { entities: entities.join(",") }),
  militaryMap: (measure: string) => get<{ measure: string; values: Record<string, number>; edition: number | null }>("/osint/military/map", { measure }),
  arms: (id: string, since = 2000) => get<Arms>(`/osint/arms/${encodeURIComponent(id)}`, { since }),
};

// Kinds of located event, their label and colour: deadly ones in reds, unrest in purples.
export const EVENT_KIND: Record<string, { label: string; color: string; group: "violence" | "unrest" | "other" }> = {
  state: { label: "Fighting between states or a state and rebels", color: "#c92a2a", group: "violence" },
  nonstate: { label: "Fighting between armed groups", color: "#e8590c", group: "violence" },
  onesided: { label: "Killing of civilians", color: "#862e9c", group: "violence" },
  battle: { label: "Battle", color: "#c92a2a", group: "violence" },
  explosion: { label: "Explosion or remote violence", color: "#f08c00", group: "violence" },
  civilians: { label: "Violence against civilians", color: "#862e9c", group: "violence" },
  protest: { label: "Protest", color: "#4263eb", group: "unrest" },
  riot: { label: "Riot", color: "#1098ad", group: "unrest" },
  strategic: { label: "Strategic development", color: "#868e96", group: "other" },
};
export const SOURCE_NAME: Record<string, string> = { ucdp_ged: "UCDP GED", ucdp_candidate: "UCDP Candidate", acled: "ACLED" };
export const STATUS_LABEL: Record<string, string> = { destroyed: "Destroyed", damaged: "Damaged", abandoned: "Abandoned", captured: "Captured", total: "Total" };

// ---------------------------------------------------------------- the map's time window for the fighting layer
// The map's timed layers follow the Layers panel's window; the fighting layer is read from the
// server for the area in view, so it is told the window here and asked again when it changes.
let layerWin: [string, string] | null = null;
export function setFightingWindow(start: string, end: string) {
  if (layerWin && layerWin[0] === start && layerWin[1] === end) return;
  layerWin = [start, end];
  if (typeof window !== "undefined") window.dispatchEvent(new Event("wm-layer-window"));
}
export function fightingQuery(): string {
  if (!layerWin) return "days=30";
  const days = Math.max(1, Math.round((Date.parse(layerWin[1]) - Date.parse(layerWin[0])) / 86_400_000));
  return `days=${Math.min(3650, days)}&end=${layerWin[1]}`;
}

// ---------------------------------------------------------------- "Look closer" links
// Other OSINT tools opened at a place and date (each opens in a new tab). Only public pages; none needs a key.
export function lookCloser(lat: number, lon: number, day?: string | null): { label: string; href: string; hint: string }[] {
  const d = day ? day.slice(0, 10) : new Date().toISOString().slice(0, 10);
  const back = new Date(Date.parse(d) - 10 * 86_400_000).toISOString().slice(0, 10);
  const ll = `${lat.toFixed(4)},${lon.toFixed(4)}`;
  return [
    { label: "Satellite before and after (Copernicus Browser)", hint: "Sentinel-2 pictures around that day; slide the date back for before",
      href: `https://browser.dataspace.copernicus.eu/?zoom=13&lat=${lat.toFixed(4)}&lng=${lon.toFixed(4)}&fromTime=${back}T00:00:00.000Z&toTime=${d}T23:59:59.999Z&datasetId=S2_L2A_CDAS` },
    { label: "Fires that night (NASA FIRMS)", hint: "Fires seen from space near the place, that day",
      href: `https://firms.modaps.eosdis.nasa.gov/map/#d:${d};@${lon.toFixed(3)},${lat.toFixed(3)},11.0z` },
    { label: "GeoConfirmed at this spot", hint: "Volunteer-geolocated videos and photos", href: `https://geoconfirmed.org/search?lat=${lat.toFixed(4)}&lng=${lon.toFixed(4)}` },
    { label: "Liveuamap that day", hint: "News pins on a map (opens at the place; pick the date there)", href: `https://liveuamap.com/?ll=${ll}&zoom=11` },
    { label: "Google Earth", hint: "3D view; the history slider shows older pictures", href: `https://earth.google.com/web/@${lat.toFixed(5)},${lon.toFixed(5)},500a,3000d,35y,0h,0t,0r` },
  ];
}

// ---------------------------------------------------------------- charts
const fmtDay = (d: string) => d;

// Monthly deaths in fighting, UCDP and ACLED side by side (never added together).
export function monthsOption(months: OsintMonth[], what: "deaths" | "unrest"): EChartsOption {
  const base = chrome();
  const x = months.map((m) => m.month);
  const series: EChartsOption["series"] = what === "deaths"
    ? [
        { name: "UCDP best estimate", type: "bar", data: months.map((m) => m.ucdp_deaths), itemStyle: { color: "#c92a2a" }, barGap: "5%" },
        { name: "ACLED reported deaths", type: "bar", data: months.map((m) => m.acled_deaths), itemStyle: { color: "#f08c00" } },
      ]
    : [
        { name: "Protests (ACLED)", type: "bar", stack: "u", data: months.map((m) => m.protests || null), itemStyle: { color: "#4263eb" } },
        { name: "Riots (ACLED)", type: "bar", stack: "u", data: months.map((m) => m.riots || null), itemStyle: { color: "#1098ad" } },
        { name: "Internet outages", type: "bar", data: months.map((m) => m.outages || null), itemStyle: { color: "#7048e8" } },
      ];
  return {
    ...base, grid: { left: 8, right: 12, top: 34, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } },
    xAxis: { type: "category", data: x, axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), trigger: "axis", axisPointer: { type: "shadow" } },
    series,
  };
}

// Running totals of losses: seen (Oryx, solid) against claimed (dashed), one colour per side.
export const SIDE_COLOR: Record<string, string> = { RUS: "#c92a2a", UKR: "#1c7ed6" };
export function lossesOption(w: WarDetail, category: string, names: Record<string, string>): EChartsOption {
  const base = chrome();
  const lines = w.series.filter((s) => s.category === category && s.status === "total");
  return {
    ...base, grid: { left: 8, right: 70, top: 34, bottom: 8, containLabel: true },
    legend: { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } },
    xAxis: { type: "time", axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), trigger: "axis" },
    series: lines.map((s) => ({
      name: `${names[s.side] ?? s.side}, ${s.basis === "seen" ? "seen (Oryx)" : `claimed by ${names[s.side === "RUS" ? "UKR" : "RUS"] ?? "the other side"}`}`,
      type: "line", showSymbol: false, data: s.points.map(([d, v]) => [fmtDay(d), v]),
      lineStyle: { color: SIDE_COLOR[s.side] ?? cssVar("--series-1"), width: 2, type: s.basis === "claimed" ? "dashed" : "solid" },
      itemStyle: { color: SIDE_COLOR[s.side] ?? cssVar("--series-1") },
      endLabel: { show: true, formatter: (p: { value?: unknown }) => compact((p.value as [string, number])[1]), color: cssVar("--ink-2") },
    })),
  };
}

export function areaOption(areas: [string, number][], label: string): EChartsOption {
  const base = chrome();
  return {
    ...base, grid: { left: 8, right: 70, top: 20, bottom: 8, containLabel: true },
    xAxis: { type: "time", axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", scale: true, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    tooltip: { ...(base.tooltip as object), trigger: "axis", valueFormatter: (v) => `${Math.round(Number(v)).toLocaleString()} km²` },
    series: [{ name: label, type: "line", showSymbol: areas.length < 30, data: areas, areaStyle: { opacity: 0.12 },
      lineStyle: { color: "#c92a2a", width: 2 }, itemStyle: { color: "#c92a2a" },
      endLabel: { show: true, formatter: (p: { value?: unknown }) => `${compact((p.value as [string, number])[1])} km²`, color: cssVar("--ink-2") } }],
  };
}
