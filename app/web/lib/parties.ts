// Charts coloured by the party in government: each head of government's (or
// state's) term from the leaders Wikidata lists, in the party's colour, with the
// leader's name where the term starts.

import { useEffect, useState } from "react";
import type { EChartsOption } from "echarts";
import { api, type EventRow } from "@/lib/api";
import { cssVar, seriesColor } from "@/lib/colors";
import { yearOf } from "@/lib/events";

export type Term = { from: string; to: string | null; x0: number; x1: number; leader: string; party: string; color: string };

// A colour for a party Wikidata gives none for, the same one every time.
function partyColor(party: string): string {
  let h = 0;
  for (const c of party) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return seriesColor(3 + (h % 6));
}

// Terms of one office, oldest first; each lasts until the next one starts (acting
// leaders and overlaps cut short), and the last one until today.
export function termsOf(events: EventRow[], office: "government" | "state"): Term[] {
  const rows = events.filter((e) => e.kind === "leader" && (e.subkind ?? "").endsWith(office))
    .sort((a, b) => a.start_date.localeCompare(b.start_date));
  const today = new Date().toISOString().slice(0, 10);
  return rows.map((e, i) => {
    const next = rows[i + 1]?.start_date;
    const to = next && (!e.end_date || next < e.end_date) ? next : e.end_date;
    const party = e.detail ?? "No party";
    return {
      from: e.start_date, to, x0: yearOf(e.start_date) - 0.5, x1: yearOf(to ?? today) - 0.5,
      leader: e.title.replace(/\s*\(head of (government|state)\)$/, ""), party,
      color: e.color ?? (e.detail ? partyColor(e.detail) : cssVar("--muted")),
    };
  }).filter((t) => t.x1 > t.x0);
}

// The terms for one country, when asked for (Settings or the panel's switch).
export function useGovernments(entity: string | null, on: boolean, office: "government" | "state"): Term[] {
  const [rows, setRows] = useState<EventRow[]>([]);
  useEffect(() => {
    if (!entity || !on) { setRows([]); return; }
    let live = true;
    api.events({ entities: [entity], kinds: ["leader"] }).then((r) => live && setRows(r)).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [entity, on]);
  return termsOf(rows, office);
}

export function termAt(terms: Term[], x: number): Term | undefined {
  return terms.find((t) => x >= t.x0 && x < t.x1);
}

// Colour a one-country chart by governing party: the line and the area under it
// (or each bar) in the colour of the party in office, the leader's name at the
// start of each term, the parties in the legend and the government in the tooltip.
// Only the terms that overlap the years with data are drawn.
export function withParties<T extends EChartsOption>(option: T, terms: Term[], years: [number, number] | null): T {
  if (!terms.length || !years) return option;
  const shown = terms.filter((t) => t.x1 > years[0] - 0.5 && t.x0 < years[1] + 0.5);
  if (!shown.length) return option;
  const series = (option.series as Record<string, unknown>[]) ?? [];
  const main = series.map((s, i) => [s, i] as const).filter(([s]) => /:[EP]$/.test(String(s.id ?? "")));
  const colorAt = (x: number) => termAt(shown, x)?.color ?? cssVar("--muted");
  const out = series.map((s) => {
    if (!/:[EP]$/.test(String(s.id ?? ""))) return s;
    if (s.type === "bar") {
      return { ...s, data: (s.data as { value: [number, number]; itemStyle?: object }[]).map((d) =>
        ({ ...d, itemStyle: { ...(d.itemStyle ?? {}), color: colorAt(d.value[0]) } })) };
    }
    return { ...s, areaStyle: { opacity: String(s.id).endsWith(":P") ? 0.25 : 0.55 }, lineStyle: { ...(s.lineStyle as object), width: 1.5 } };
  });
  const parties = [...new Map(shown.map((t) => [t.party, t.color])).entries()];
  // A name at the start of each term; terms too short to hold one get just the line.
  const minLen = (years[1] - years[0]) / 40;
  const lines = shown.filter((t) => t.x0 >= years[0] - 0.5).map((t) => ({
    xAxis: t.x0, name: t.x1 - t.x0 >= minLen ? t.leader : "",
    lineStyle: { color: cssVar("--muted"), type: "solid" as const, width: 1, opacity: 0.5 },
  }));
  out.push({
    type: "line", id: "governments", data: [], silent: true, tooltip: { show: false },
    markLine: { symbol: "none", silent: true, animation: false, data: lines,
      label: { show: true, position: "insideEndTop", formatter: (p: { name: string }) => p.name, color: cssVar("--ink-2"), fontSize: 10 } },
  });
  for (const [party, color] of parties) out.push({ type: "line", id: `party:${party}`, name: party, data: [], color });
  const hasLines = main.some(([s]) => s.type !== "bar");
  const tip = option.tooltip as { formatter?: (p: unknown) => string } | undefined;
  const inner = tip?.formatter;
  return {
    ...option,
    series: out,
    visualMap: hasLines ? {
      type: "piecewise", show: false, dimension: 0, seriesIndex: main.filter(([s]) => s.type !== "bar").map(([, i]) => i),
      pieces: shown.map((t) => ({ gte: t.x0, lt: t.x1, color: t.color })), outOfRange: { color: cssVar("--muted") },
    } : undefined,
    legend: {
      show: true, top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, type: "scroll",
      data: parties.map(([p]) => p), textStyle: { color: cssVar("--ink-2") }, selectedMode: false,
    },
    grid: { ...(option.grid as object), top: 60 },
    tooltip: inner ? { ...(option.tooltip as object), formatter: (params: unknown) => {
      const html = inner(params);
      const first = (Array.isArray(params) ? params[0] : params) as { value?: [number, number] } | undefined;
      const t = first?.value ? termAt(shown, first.value[0]) : undefined;
      return t ? `${html}<br/><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${t.color};margin-right:6px"></span>${t.leader} (${t.party})` : html;
    } } : option.tooltip,
  } as T;
}
