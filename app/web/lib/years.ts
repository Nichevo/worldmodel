"use client";

// What years each indicator has, for the year strips in the indicator drop-downs: countries
// with figures in each year, split into the source's estimates (history) and its own
// projections or forecasts. Fetched once per page load from /indicators/years.
import { useEffect, useState } from "react";
import { get, type Indicator } from "@/lib/api";

export type IndicatorYears = { from: number; e: number[]; p: number[]; countries: boolean; by?: string[] };

let cache: Record<string, IndicatorYears> | null = null;
let loading: Promise<Record<string, IndicatorYears>> | null = null;

export function useIndicatorYears(on: boolean): Record<string, IndicatorYears> | null {
  const [found, setFound] = useState(cache);
  useEffect(() => {
    if (!on || cache) return;
    loading ??= get<Record<string, IndicatorYears>>("/indicators/years").then((r) => (cache = r)).catch(() => { loading = null; return {}; });
    let live = true;
    loading.then((r) => { if (live) setFound(r); });
    return () => { live = false; };
  }, [on]);
  return on ? found : null;
}

export type YearSummary = {
  first: number | null; lastHist: number | null; // history: first and last year with an estimate
  projFrom: number | null; projTo: number | null; // the source's own forecasts, after the history
  peak: number; peakYear: number | null;          // most countries in any history year
  lastCount: number;                              // countries in the last history year
  gaps: number;                                   // years with no figures between first and last history year
  every: number;                                  // history comes every n years (censuses, five-yearly series); 1 = yearly or uneven
  by: string[]; countries: boolean;
};

// One indicator's years in words-ready numbers, from the strip data when there is some,
// else from the indicator's own first, last and last-estimate years (ratios of yours).
export function summarise(i: Indicator, y: IndicatorYears | undefined): YearSummary {
  if (!y) {
    const lastHist = i.last_estimate_year ?? null;
    const proj = i.last_year != null && lastHist != null && i.last_year > lastHist;
    return { first: i.first_year, lastHist, projFrom: proj ? lastHist! + 1 : null, projTo: proj ? i.last_year : null,
      peak: i.countries, peakYear: null, lastCount: 0, gaps: 0, every: 1, by: [], countries: true };
  }
  let first: number | null = null, lastHist: number | null = null, peak = 0, peakYear: number | null = null, gaps = 0;
  y.e.forEach((n, k) => {
    if (!n) return;
    const yr = y.from + k;
    first ??= yr;
    lastHist = yr;
    if (n > peak) { peak = n; peakYear = yr; }
  });
  const have = y.e.map((n, k) => (n ? y.from + k : 0)).filter(Boolean);
  const steps = new Set(have.slice(1).map((yr, k) => yr - have[k]));
  const every = steps.size === 1 ? [...steps][0] : 1;
  if (every === 1 && first != null && lastHist != null) for (let yr = first; yr <= lastHist; yr++) if (!y.e[yr - y.from]) gaps++;
  let projFrom: number | null = null, projTo: number | null = null;
  y.p.forEach((n, k) => {
    const yr = y.from + k;
    if (!n || (lastHist != null && yr <= lastHist)) return;
    projFrom ??= yr;
    projTo = yr;
  });
  return { first, lastHist, projFrom, projTo, peak, peakYear, lastCount: lastHist != null ? y.e[lastHist - y.from] : 0,
    gaps, every, by: y.by ?? [], countries: y.countries };
}

// The short text beside a strip: "1960–2023" and, in orange, "→ 2050".
export function yearsText(s: YearSummary): { hist: string; proj: string } {
  const hist = s.first == null ? "no history" : s.first === s.lastHist ? `${s.first}` : `${s.first}–${s.lastHist}`;
  return { hist, proj: s.projTo != null ? `→ ${s.projTo}` : "" };
}

// The longer line for the drop-down's foot and the strip's hover text.
export function yearsSentence(s: YearSummary): string {
  const what = s.countries ? "countries" : "places";
  const parts: string[] = [];
  if (s.first == null) parts.push("No history in this build.");
  else {
    let h = `History ${s.first === s.lastHist ? s.first : `${s.first} to ${s.lastHist}`}`;
    if (s.peak) h += `, up to ${s.peak} ${what}${s.peakYear ? ` (${s.peakYear})` : ""}`;
    if (s.lastCount && s.lastCount < s.peak) h += `, ${s.lastCount} in ${s.lastHist}`;
    if (s.every > 1) h += `; figures every ${s.every} years`;
    if (s.gaps) h += `; ${s.gaps} year${s.gaps === 1 ? "" : "s"} missing in between`;
    parts.push(h + ".");
  }
  if (s.projTo != null) parts.push(`Forecast ${s.projFrom === s.projTo ? s.projTo : `${s.projFrom} to ${s.projTo}`}${s.by.length ? ` by ${s.by.join(", ")}` : ""}.`);
  else parts.push("No forecasts from the source.");
  return parts.join(" ");
}

// The strip's time scale: 1700-1950 squeezed into the first eighth, 1950-2100 spread over the rest.
export const STRIP_FROM = 1700, STRIP_KNEE = 1950, STRIP_TO = 2100;
export function stripX(year: number, width: number): number {
  const knee = width * 0.125;
  if (year <= STRIP_KNEE) return Math.max(0, ((year - STRIP_FROM) / (STRIP_KNEE - STRIP_FROM)) * knee);
  return knee + (Math.min(year, STRIP_TO) - STRIP_KNEE) / (STRIP_TO - STRIP_KNEE) * (width - knee);
}
