// Stories: short visual stories, each a list of steps. A step is one big chart or map and one
// sentence; the sentence is worked out from the step's own figures when the page opens, so a
// story updates itself after every refresh. The stories themselves are in app/web/stories/.

import type { ReactNode } from "react";
import type { Indicator, Ranking, RankingRow, SeriesRow } from "@/lib/api";
import { formatValue } from "@/lib/format";

export type Named = { id: string; name: string };

// What a step's sentence gets to work with.
export type RankData = { ind: Indicator; ranking: Ranking; row: (id: string) => RankingRow | undefined;
  count: (test: (v: number) => boolean) => number; fmt: (v: number | null | undefined) => string };
export type CountData = { ind: Indicator; years: number[]; counts: number[]; totals: number[]; lastEstimate: number | null;
  at: (year: number) => { count: number; total: number } | null; fmt: (v: number | null | undefined) => string };
export type SeriesData = { inds: Indicator[]; rows: SeriesRow[][];
  // the latest estimate, or the value in a year, for an entity (in the first indicator unless told)
  last: (entity: string, layer?: number) => { year: number; value: number } | null;
  at: (entity: string, year: number, layer?: number) => number | null;
  end: (entity: string, layer?: number) => { year: number; value: number } | null; // the last year of all, projections included
  fmt: (v: number | null | undefined, layer?: number) => string };
export type TilesData = { rows: { ind: Indicator; row: RankingRow; of: number }[]; fmt: (ind: Indicator, v: number | null | undefined) => string };
export type CityData = { cities: { name: string; country: string; pts: [number, number, boolean][] }[]; first: number; last: number };

export type Step =
  // A world map of one indicator in one year (the indicator's main year if none).
  | { kind: "map"; indicator: string; year?: number; diverging?: boolean; say: (d: RankData) => string }
  // Lines for a few entities, one indicator (or several indicators for one entity: `indicators`).
  | { kind: "lines"; indicator: string; indicators?: string[]; labels?: string[]; colors?: string[]; entities: Named[]; from?: number; to?: number;
      about?: string; // what the figures are, for the "not loaded yet" note before the indicator is in the catalogue
      say: (d: SeriesData) => string }
  // How many countries pass a test, year by year.
  | { kind: "count"; indicator: string; label: string; test: (v: number) => boolean; to?: number; say: (d: CountData) => string }
  // Ranked bars: the top (or bottom) countries, or the biggest changes over ten years; some highlighted.
  | { kind: "bars"; indicator: string; year?: number; top?: number; by?: "value" | "change"; order?: "desc" | "asc";
      highlight?: string[]; also?: string[]; say: (d: RankData) => string }
  // A grid of one country's figures with its rank and ten-year change.
  | { kind: "tiles"; entity: string; indicators: string[]; max?: number; say: (d: TilesData) => string }
  // Cities' people over time, by name (GHSL urban centres or UN figures).
  | { kind: "cities"; names: string[]; say: (d: CityData) => string }
  // One of the app's own views (sea ice circle, electricity map, largest cities), with a fixed sentence.
  | { kind: "view"; view: "seaice" | "electricity" | "cities"; say: string };

export type Story = {
  id: string; title: string; blurb: string; colour: string; // a strong colour for the gallery card and headings
  steps: (Step & { kicker?: string })[];
  sources: string; // a line naming where the figures come from
};

// Helpers for sentences.
export const n = (v: number) => v.toLocaleString("en");
export const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "–");
export const times = (a: number, b: number) => (b ? `${(a / b).toFixed(a / b >= 10 ? 0 : 1)} times` : "–");
export function fmtOf(ind: Indicator) {
  return (v: number | null | undefined) => (v === null || v === undefined ? "–"
    : ind.unit.startsWith("%") ? `${v.toFixed(ind.decimals)}%` : formatValue(v, ind.unit, ind.decimals));
}
// "New Zealand ranks 143rd of 236"
export function ordinal(k: number): string {
  const s = ["th", "st", "nd", "rd"], v = k % 100;
  return `${k}${s[(v - 20) % 10] ?? s[v] ?? s[0]}`;
}

export type StoryNode = ReactNode;
