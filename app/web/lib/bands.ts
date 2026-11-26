// Value bands for the "Bands" picture: every country as a tile, stacked in columns by
// which band its value falls in, so the columns' heights read as a bar chart. Bands are
// round numbers chosen from the spread of the values: even steps (0-1%, 1-2%...) for
// most figures, steps of 1-2-5 per power of ten for figures that run over many powers
// of ten (population, GDP). A lone tail below zero becomes one "Below 0" band.

import { compact } from "@/lib/format";
import { shortValue } from "@/lib/look";

export type Band = { lo: number | null; hi: number | null; label: string; neg: boolean };
export type BandDetail = "fewer" | "auto" | "more";

const COUNT: Record<BandDetail, number> = { fewer: 6, auto: 9, more: 13 };

function quantile(sorted: number[], q: number): number {
  if (!sorted.length) return 0;
  const i = (sorted.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo);
}

function niceStep(raw: number): number {
  if (!(raw > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(raw));
  const f = raw / p;
  // the nearest round step (on a log scale): 1, 2, 2.5, 5 or 10
  const steps = [1, 2, 2.5, 5, 10];
  return steps.reduce((b, s) => (Math.abs(Math.log(s / f)) < Math.abs(Math.log(b / f)) ? s : b), 1) * p;
}

// An edge as short text: 2%, 0.5, 1.2M, $40k.
export function edgeText(v: number, unit: string, step: number): string {
  const dec = step >= 1 || v === 0 ? 0 : Math.min(3, Math.ceil(-Math.log10(step) - 1e-9));
  if (Math.abs(v) >= 1e4) {
    const c = compact(v);
    return unit === "US dollars" || unit === "US dollars per person" ? `$${c}` : c;
  }
  return shortValue(v, unit, dec);
}

export function makeBands(values: number[], unit: string, detail: BandDetail = "auto"): Band[] {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return [];
  const target = COUNT[detail];
  const p5 = quantile(v, 0.05), p95 = quantile(v, 0.95);
  const lab = (x: number, step: number) => edgeText(x, unit, step);
  // Figures over many powers of ten: 1-2-5 steps (or 1-3, or one per power) on a log scale.
  if (p5 > 0 && p95 / p5 > 80) {
    const decades = Math.log10(p95 / p5);
    const seq = decades * 3 <= target + 1 ? [1, 2, 5] : decades * 2 <= target + 1 ? [1, 3] : [1];
    const edges: number[] = [];
    for (let k = Math.floor(Math.log10(p5)); k <= Math.ceil(Math.log10(p95)) + 1; k++) {
      for (const m of seq) { const e = m * 10 ** k; if (e > p5 * 0.999 && e <= p95 * 1.001) edges.push(e); }
    }
    if (edges.length < 2) return linear(v, p5, p95, target, unit);
    return fromEdges(edges, (x) => lab(x, x / 10), v);
  }
  return linear(v, p5, p95, target, unit);
}

function linear(v: number[], p5: number, p95: number, target: number, unit: string): Band[] {
  if (p95 === p5) return [{ lo: null, hi: null, label: "All", neg: false }];
  const step = niceStep((p95 - p5) / Math.max(2, target - 2));
  let first = Math.floor(p5 / step) * step, last = Math.ceil(p95 / step) * step;
  // a short tail below zero: one band for every value under 0
  const negShare = v.filter((x) => x < 0).length / v.length;
  if (first < 0 && last > 0 && negShare < 0.3) first = 0;
  if (last - first < step) last = first + step;
  const edges: number[] = [];
  for (let e = first; e <= last + step * 1e-6; e += step) edges.push(+e.toPrecision(12));
  return fromEdges(edges, (x) => edgeText(x, unit, step), v);
}

// Bands below the first edge, between each pair, and from the last up; empty ends dropped.
function fromEdges(edges: number[], text: (x: number) => string, v: number[]): Band[] {
  const bands: Band[] = [{ lo: null, hi: edges[0], label: edges[0] === 0 ? "Below zero" : `Under ${text(edges[0])}`, neg: edges[0] <= 0 }];
  for (let i = 0; i < edges.length - 1; i++) {
    bands.push({ lo: edges[i], hi: edges[i + 1], label: `${text(edges[i])} to ${text(edges[i + 1])}`, neg: edges[i + 1] <= 0 });
  }
  bands.push({ lo: edges[edges.length - 1], hi: null, label: `${text(edges[edges.length - 1])} or more`, neg: false });
  const used = bands.map((b) => v.some((x) => inBand(b, x)));
  const a = used.indexOf(true), z = used.lastIndexOf(true);
  return a < 0 ? bands : bands.slice(a, z + 1);
}

export function inBand(b: Band, x: number): boolean {
  return (b.lo === null || x >= b.lo) && (b.hi === null || x < b.hi);
}

export function bandOf(bands: Band[], x: number): number {
  const i = bands.findIndex((b) => inBand(b, x));
  if (i >= 0) return i;
  return x < (bands[0]?.hi ?? 0) ? 0 : bands.length - 1;
}
