// Dated events on charts and in lists: labels and colours per kind, the chart
// marks (a band for anything that lasts, a line for a single day), and a hook
// that loads the events Settings asks for.

import { useEffect, useState } from "react";
import { api, type EventRow, type Settings } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { compact } from "@/lib/format";
import { look } from "@/lib/look";
import { useSettings } from "@/lib/settings";

export const KINDS: { kind: string; label: string; color: string }[] = [
  { kind: "recession", label: "Recessions", color: "--div-neg-3" },
  { kind: "crisis", label: "Financial crises", color: "--div-neg-2" },
  { kind: "boom", label: "Booms", color: "--div-pos-2" },
  { kind: "inflation", label: "High inflation", color: "--series-6" },
  { kind: "debt", label: "Debt surges", color: "--series-8" },
  { kind: "coup", label: "Coups", color: "--series-4" },
  { kind: "conflict", label: "Armed conflicts", color: "--div-neg-1" },
  { kind: "election", label: "Elections", color: "--series-2" },
  { kind: "leader", label: "Leaders", color: "--series-5" },
  { kind: "independence", label: "Independence", color: "--series-7" },
  { kind: "sport", label: "Sporting events", color: "--series-3" },
  { kind: "disaster", label: "Disasters", color: "--series-1" },
  { kind: "epidemic", label: "Epidemics", color: "--series-1" },
  { kind: "notable", label: "Notable episodes", color: "--series-7" },
  { kind: "episode", label: "Big episodes", color: "--div-neg-2" },
  { kind: "crisiswatch", label: "CrisisWatch ratings", color: "--div-neg-2" },
  { kind: "un", label: "UN Security Council", color: "--series-2" },
  { kind: "sanction", label: "Sanctions", color: "--series-4" },
  { kind: "imf", label: "IMF programmes", color: "--series-8" },
  { kind: "trade_dispute", label: "WTO disputes", color: "--series-6" },
  { kind: "treaty", label: "Treaties", color: "--series-3" },
  { kind: "court", label: "International court cases", color: "--series-5" },
  { kind: "summit", label: "Summits hosted", color: "--series-7" },
  { kind: "law", label: "Law changes", color: "--series-3" },
  { kind: "holiday", label: "Public holidays", color: "--series-2" },
  { kind: "enso", label: "El Niño and La Niña", color: "--series-6" },
  { kind: "animal_disease", label: "Animal disease outbreaks", color: "--series-8" },
  { kind: "pest", label: "Pests and plant disease arriving", color: "--series-5" },
  { kind: "pollution", label: "Pollution disasters and smoke", color: "--series-4" },
  { kind: "transport", label: "Air, sea and rail accidents", color: "--div-neg-2" },
  { kind: "infrastructure", label: "Cables, pipelines and canals cut", color: "--series-6" },
  { kind: "user", label: "Your milestones", color: "--ink-2" },
];
const BY_KIND = new Map(KINDS.map((k) => [k.kind, k]));

export const kindLabel = (kind: string) => BY_KIND.get(kind)?.label ?? kind;
export const kindColor = (kind: string) => cssVar(BY_KIND.get(kind)?.color ?? "--muted");
export const kindVar = (kind: string) => `var(${BY_KIND.get(kind)?.color ?? "--muted"})`;

// A date as a fractional year, for charts whose x axis is the year.
export function yearOf(iso: string): number {
  const d = new Date(`${iso}T00:00:00Z`);
  const start = Date.UTC(d.getUTCFullYear(), 0, 1);
  return d.getUTCFullYear() + (d.getTime() - start) / (365.25 * 86_400_000);
}

export function when(e: EventRow): string {
  const fmt = (iso: string) => (e.precision === "year" ? iso.slice(0, 4) : e.precision === "month" ? iso.slice(0, 7) : iso);
  if (!e.end_date || e.end_date === e.start_date) return fmt(e.start_date);
  return e.precision === "year" && e.start_date.slice(0, 4) === e.end_date.slice(0, 4) ? fmt(e.start_date) : `${fmt(e.start_date)} to ${fmt(e.end_date)}`;
}

export function sizeText(e: EventRow): string {
  const bits: string[] = [];
  if (e.deaths) bits.push(`${compact(e.deaths)} deaths`);
  if (e.affected) bits.push(`${compact(e.affected)} affected`);
  if (e.damage_usd) bits.push(`$${compact(e.damage_usd)} damage`);
  if (!bits.length && e.size !== null && e.size_unit) bits.push(`${+e.size.toFixed(2)} ${e.size_unit}`);
  return bits.join(", ");
}

// Which events belong on a chart, by the Settings: the kinds ticked, and disasters
// and epidemics only from a number of deaths.
export function forCharts(events: EventRow[], s: Settings): EventRow[] {
  const kinds = new Set(s.event_kinds.split(",").filter(Boolean));
  return events.filter((e) => kinds.has(e.kind)
    && (!["disaster", "epidemic"].includes(e.kind) || (e.deaths ?? 0) >= s.disaster_min_deaths)
    && (e.kind !== "transport" || (e.deaths ?? 0) >= s.transport_min_deaths));
}

// An empty series carrying the marks: bands (markArea) and lines (markLine), labelled on hover.
// A yearly value sits on its year (2009 at x = 2009), so a year's span on the chart is
// 2008.5 to 2009.5 and a date is placed within it: a 2009 recession covers the 2009 bar.
export function eventMarks(events: EventRow[], names?: Map<string, string>) {
  const label = (e: EventRow) => `${e.title}${names && names.size > 1 ? ` (${names.get(e.entity_id) ?? e.entity_id})` : ""}`;
  const at = (iso: string) => yearOf(iso) - 0.5;
  const areas: object[] = [];
  const lines: object[] = [];
  for (const e of events) {
    const color = kindColor(e.kind);
    const x0 = e.precision === "year" && !e.end_date ? +e.start_date.slice(0, 4) : at(e.start_date);
    const x1 = e.end_date ? at(e.end_date) + 1 / 365 : null;
    if (x1 !== null && x1 - x0 > 0.05) {
      areas.push([{ xAxis: x0, name: label(e), url: e.url, itemStyle: { color, opacity: 0.12 } }, { xAxis: x1 }]);
    } else {
      lines.push({ xAxis: x0, name: label(e), url: e.url, lineStyle: { color, type: "dotted", width: 1.5 } });
    }
  }
  const hoverLabel = { show: true, color: cssVar("--ink"), backgroundColor: cssVar("--surface"), padding: [2, 4], borderRadius: 3,
    formatter: (p: { name: string }) => p.name };
  // Named on the chart (Settings > Look of charts): a short name standing up the band's left edge,
  // when there are few enough bands to read.
  const named = look.eventLabels && areas.length <= 10;
  const short = (t: string) => (t.length > 22 ? `${t.slice(0, 21)}…` : t);
  if (named) {
    for (const a of areas as { name: string; itemStyle: { color: string } }[][]) {
      Object.assign(a[0], { label: { show: true, position: "insideTopLeft", rotate: 90, align: "right", verticalAlign: "top",
        offset: [2, 4], fontSize: 10, color: a[0].itemStyle.color, formatter: () => short(a[0].name) } });
    }
  }
  return {
    type: "line" as const, id: "events", data: [] as number[], silent: false, tooltip: { show: false },
    markArea: { silent: false, label: { show: false }, emphasis: { label: { ...hoverLabel, position: "insideTop" } }, data: areas },
    markLine: { symbol: "none", silent: false, animation: false, label: { show: false },
      emphasis: { label: { ...hoverLabel, position: "insideEndTop" } }, data: lines },
  };
}

// Events for the countries on a chart, as Settings asks; none when switched off or
// for more than three countries (the chart would be all bands).
// `kinds` (comma-separated) overrides the kinds ticked in Settings, as the country
// page's event chips do.
export function useChartEvents(entityIds: string[], kinds?: string): EventRow[] {
  const s = useSettings();
  const [rows, setRows] = useState<EventRow[]>([]);
  const key = entityIds.join(",");
  const wanted = kinds ?? s.event_kinds;
  useEffect(() => {
    if (!s.events_on_charts || !key || entityIds.length > 3 || !wanted) { setRows([]); return; }
    let live = true;
    // El Niño and La Niña are stored on the World, so every country's charts can show them.
    const ks = wanted.split(",").filter(Boolean);
    const ents = key.split(",");
    api.events({ entities: ks.includes("enso") && !ents.includes("world") ? [...ents, "world"] : ents, kinds: ks })
      .then((r) => live && setRows(forCharts(r.filter((e) => e.entity_id !== "world" || e.kind === "enso" || ents.includes("world")), { ...s, event_kinds: wanted })))
      .catch(() => live && setRows([]));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, s.events_on_charts, wanted, s.disaster_min_deaths, s.transport_min_deaths]);
  return rows;
}

// The country page's own choice of event kinds, remembered in this browser; null
// until changed, which means "as in Settings".
const PROFILE_KINDS = "wm.profileEventKinds";
export function useProfileKinds(): [string | null, (k: string | null) => void] {
  const [kinds, setKinds] = useState<string | null>(null);
  useEffect(() => {
    try { setKinds(window.localStorage.getItem(PROFILE_KINDS)); } catch { /* storage blocked: use Settings */ }
  }, []);
  const set = (k: string | null) => {
    setKinds(k);
    try {
      if (k === null) window.localStorage.removeItem(PROFILE_KINDS); else window.localStorage.setItem(PROFILE_KINDS, k);
    } catch { /* kept for this visit only */ }
  };
  return [kinds, set];
}

// Add the events that cover the hovered year to a chart's axis tooltip.
export function withEventTooltip<T extends { tooltip?: unknown }>(option: T, events: EventRow[], names?: Map<string, string>): T {
  const tip = option.tooltip as { formatter?: (p: unknown) => string } | undefined;
  if (!events.length || !tip?.formatter) return option;
  const inner = tip.formatter;
  const formatter = (params: unknown) => {
    const html = inner(params);
    const first = (Array.isArray(params) ? params[0] : params) as { value?: [number, number] } | undefined;
    const year = first?.value?.[0];
    if (year === undefined) return html;
    const y = String(Math.round(year));
    const hits = events.filter((e) => e.start_date.slice(0, 4) <= y && (e.end_date ?? e.start_date).slice(0, 4) >= y).slice(0, 6);
    if (!hits.length) return html;
    const many = names && names.size > 1;
    return html + "<br/>" + hits.map((e) => `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${kindColor(e.kind)};margin-right:6px"></span>`
      + `${e.title}${many ? ` (${names!.get(e.entity_id) ?? e.entity_id})` : ""}`).join("<br/>");
  };
  return { ...option, tooltip: { ...(option.tooltip as object), formatter } };
}

// A click on a band or line that belongs to a page in the app (a big episode's page) opens it.
export function linkBands(chart: { on: (ev: string, fn: (p: unknown) => void) => void }, go: (url: string) => void) {
  chart.on("click", (p) => {
    const q = p as { componentType?: string; data?: { url?: string | null } | { url?: string | null }[] };
    if (q.componentType !== "markArea" && q.componentType !== "markLine") return;
    const d = Array.isArray(q.data) ? q.data[0] : q.data;
    if (d?.url && d.url.startsWith("/")) go(d.url);
  });
}
