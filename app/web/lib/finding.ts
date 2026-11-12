// A chart's headline: one short sentence saying what the chart shows, worked out from
// its own figures ("1.56 in 2023, the lowest since records began in 1960"), so a
// title says the finding and not just the measure. Estimates only; projections never count.

import type { SeriesRow } from "@/lib/api";
import { formatValue } from "@/lib/format";

type Named = { id: string; name: string };

export function finding(rows: SeriesRow[], entities: Named[], unit: string, decimals: number): string | null {
  const est = rows.filter((r) => r.status === "E");
  if (!est.length) return null;
  const fmt = (v: number) => formatValue(v, unit, decimals);
  if (entities.length === 1) return one(est, entities[0].name, fmt);
  // Several: who is highest and lowest in the latest year they all share, else each one's latest.
  const byE = new Map<string, SeriesRow[]>();
  for (const r of est) byE.set(r.entity_id, [...(byE.get(r.entity_id) ?? []), r]);
  const lasts = entities.map((e) => ({ e, r: (byE.get(e.id) ?? []).at(-1) })).filter((x): x is { e: Named; r: SeriesRow } => !!x.r);
  if (lasts.length < 2) return lasts.length ? one(byE.get(lasts[0].e.id)!, lasts[0].e.name, fmt) : null;
  const year = Math.min(...lasts.map((x) => +x.r.period));
  const at = lasts.map((x) => ({ e: x.e, r: (byE.get(x.e.id) ?? []).filter((r) => +r.period <= year).at(-1) }))
    .filter((x): x is { e: Named; r: SeriesRow } => !!x.r && +x.r.period === year);
  if (at.length < 2) return null;
  at.sort((a, b) => b.r.value - a.r.value);
  const top = at[0], low = at[at.length - 1];
  if (top.r.value === low.r.value) return `${top.e.name} and ${low.e.name} level at ${fmt(top.r.value)} in ${year}`;
  return `${top.e.name} highest at ${fmt(top.r.value)} in ${year}; ${low.e.name} lowest at ${fmt(low.r.value)}`;
}

function one(est: SeriesRow[], name: string, fmt: (v: number) => string): string | null {
  const pts = [...est].sort((a, b) => +a.period - +b.period);
  const last = pts[pts.length - 1];
  const y = +last.period, v = last.value;
  const first = +pts[0].period;
  const before = pts.slice(0, -1);
  const head = `${name}: ${fmt(v)} in ${y}`;
  if (before.length >= 10) {
    if (before.every((p) => p.value < v)) return `${head}, the highest since records began in ${first}`;
    if (before.every((p) => p.value > v)) return `${head}, the lowest since records began in ${first}`;
    // The highest (or lowest) for a long while: the last year it was at least this high (low).
    const hiSince = [...before].reverse().find((p) => p.value >= v);
    const loSince = [...before].reverse().find((p) => p.value <= v);
    if (hiSince && y - +hiSince.period >= 10) return `${head}, the highest since ${hiSince.period}`;
    if (loSince && y - +loSince.period >= 10) return `${head}, the lowest since ${loSince.period}`;
  }
  // Otherwise the change over ten years (or as far back as the figures go).
  const back = pts.filter((p) => +p.period <= y - 10).at(-1) ?? (pts.length > 1 ? pts[0] : null);
  if (!back || back === last) return head;
  const d = v - back.value;
  if (Math.abs(d) < Math.abs(back.value) * 0.005) return `${head}, about the same as in ${back.period}`;
  return `${head}, ${d > 0 ? "up" : "down"} from ${fmt(back.value)} in ${back.period}`;
}
