"use client";

// Ask AI from anywhere: a component builds the context it can see (its figures as a
// table, descriptions, events, highlighted text) and opens the Ask AI box, which
// lives once in the page layout. Keep: send something to the Highlights page.
import { useEffect, useRef } from "react";
import { api, type EventRow, type Indicator, type NewHighlight, type SeriesRow } from "@/lib/api";
import { SOURCE_LABEL } from "@/lib/format";

export type PartKind = "data" | "description" | "events" | "highlight" | "page" | "notes";
export type AskPart = { key: string; kind: PartKind; label: string; text: string };
export type AskRequest = {
  title: string; // what the question is about, shown at the top of the box
  parts: AskPart[];
  entity?: string;
  indicator?: string;
  page?: string;
  question?: string;
  picture?: () => Promise<string | null>; // a PNG data URL of the chart, for models that can see pictures
  send?: boolean; // ask straight away (the question box in the top bar)
};

// The charts on the page now, so a question can bring one in by name ("Add a chart from
// this page" in the Ask AI box): its figures go as text, and a picture to models that see.
export type PageChart = { title: string; parts: () => AskPart[]; picture?: () => Promise<string | null> };
const pageChartGetters = new Map<number, () => PageChart>();
let chartSeq = 0;
export function registerChart(get: () => PageChart): () => void {
  const id = ++chartSeq;
  pageChartGetters.set(id, get);
  return () => { pageChartGetters.delete(id); };
}
export function pageCharts(): PageChart[] {
  const out: PageChart[] = [];
  for (const g of pageChartGetters.values()) {
    try { out.push(g()); } catch { /* a chart going away */ }
  }
  return out;
}
// For a component with a chart: stays listed while it is on the page, always with its latest figures.
export function useRegisterChart(get: () => PageChart) {
  const latest = useRef(get);
  latest.current = get;
  useEffect(() => registerChart(() => latest.current()), []);
}

const ASK = "worldmodel:ask";
const TOAST = "worldmodel:toast";

export function openAsk(req: AskRequest) {
  window.dispatchEvent(new CustomEvent<AskRequest>(ASK, { detail: { page: location.pathname + location.search, ...req } }));
}

export function onAsk(fn: (req: AskRequest) => void): () => void {
  const h = (e: Event) => fn((e as CustomEvent<AskRequest>).detail);
  window.addEventListener(ASK, h);
  return () => window.removeEventListener(ASK, h);
}

export function toast(text: string) {
  window.dispatchEvent(new CustomEvent<string>(TOAST, { detail: text }));
}

export function onToast(fn: (text: string) => void): () => void {
  const h = (e: Event) => fn((e as CustomEvent<string>).detail);
  window.addEventListener(TOAST, h);
  return () => window.removeEventListener(TOAST, h);
}

// Keep something on the Highlights page, with a short confirmation.
export async function keep(item: NewHighlight): Promise<boolean> {
  try {
    const heading = document.querySelector("main h1")?.textContent?.trim();
    await api.addHighlight({ page_url: location.pathname + location.search, page_title: heading || document.title, ...item });
    toast("Kept in Highlights.");
    return true;
  } catch (e) {
    toast(`Not kept: ${(e as Error).message || e}`);
    return false;
  }
}

// One indicator's rows as a table: a row per year, a column per entity; projections marked.
export function seriesTable(rows: SeriesRow[], names: Map<string, string>): { columns: string[]; rows: (string | number | null)[][] } {
  const ids = [...new Set(rows.map((r) => r.entity_id))];
  const years = [...new Set(rows.map((r) => +r.period))].sort((a, b) => a - b);
  const at = new Map(rows.map((r) => [`${r.entity_id}|${+r.period}`, r]));
  const anyP = rows.some((r) => r.status === "P");
  return {
    columns: ["Year", ...ids.map((id) => names.get(id) ?? id), ...(anyP ? ["Note"] : [])],
    rows: years.map((y) => {
      const cells = ids.map((id) => at.get(`${id}|${y}`)?.value ?? null);
      const proj = ids.some((id) => at.get(`${id}|${y}`)?.status === "P");
      return [y, ...cells.map((v) => (v === null ? null : +v.toPrecision(6))), ...(anyP ? [proj ? "projection" : ""] : [])];
    }),
  };
}

export function tableText(t: { columns: string[]; rows: (string | number | null)[][] }): string {
  return [t.columns.join(","), ...t.rows.map((r) => r.map((v) => (v === null ? "" : String(v))).join(","))].join("\n");
}

export function sourcesLine(rows: SeriesRow[]): string {
  return [...new Set(rows.map((r) => `${SOURCE_LABEL[r.source_id] ?? r.source_id} (${r.vintage})`))].join("; ");
}

// The usual parts for one indicator's chart: its figures, what it means, events in the years shown.
export function chartParts(indicator: Indicator, rows: SeriesRow[], names: Map<string, string>, events: EventRow[] = []): AskPart[] {
  const t = seriesTable(rows, names);
  const parts: AskPart[] = [
    { key: "data", kind: "data", label: `${indicator.name} (${indicator.unit})`,
      text: `Unit: ${indicator.unit}. Source: ${sourcesLine(rows)}.\n${tableText(t)}` },
    { key: "description", kind: "description", label: `What "${indicator.name}" measures`, text: indicator.description },
  ];
  if (events.length) parts.push({ key: "events", kind: "events", label: "Events in these years", text: eventsText(events) });
  return parts;
}

export function eventsText(events: EventRow[]): string {
  return events.slice(0, 80).map((e) => `${e.start_date}${e.end_date && e.end_date !== e.start_date ? ` to ${e.end_date}` : ""}: `
    + `${e.title}${e.entity_name ? ` (${e.entity_name})` : ""} [${e.kind}${e.subkind ? `, ${e.subkind}` : ""}]`).join("\n");
}

// A CSV (as the panels' downloads write it) back into a table, for keeping.
export function csvTable(text: string, max = 2000): { columns: string[]; rows: (string | number | null)[][] } {
  const lines: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      if (row.some((x) => x !== "")) lines.push(row);
      row = [];
      if (lines.length > max) break;
    } else cell += c;
  }
  if (cell || row.length) { row.push(cell); lines.push(row); }
  const [columns = [], ...rest] = lines;
  return { columns, rows: rest.map((r) => r.map((v) => (v === "" ? null : /^-?\d+(\.\d+)?(e-?\d+)?$/i.test(v) ? +v : v))) };
}

// The latest estimate of each indicator for some entities, as one table (fetched when asked).
export async function latestTable(indicators: Indicator[], ids: string[], names: Map<string, string>): Promise<string> {
  const lines = ["Indicator,Unit," + ids.map((id) => names.get(id) ?? id).join(",") + ",Year"];
  const all = await Promise.all(indicators.slice(0, 30).map((i) => api.series(i.indicator_id, ids).catch(() => [] as SeriesRow[])));
  indicators.slice(0, 30).forEach((ind, k) => {
    const est = all[k].filter((r) => r.status !== "P");
    if (!est.length) return;
    const year = Math.max(...est.map((r) => +r.period));
    const at = new Map(est.filter((r) => +r.period === year).map((r) => [r.entity_id, r.value]));
    const q = (s: string) => (/[",]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
    lines.push([q(ind.name), q(ind.unit), ...ids.map((id) => (at.has(id) ? String(+at.get(id)!.toPrecision(6)) : "")), String(year)].join(","));
  });
  return lines.join("\n");
}
