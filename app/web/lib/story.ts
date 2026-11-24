// Stories: short visual stories, each a list of steps. A step is one big chart or map and one
// sentence; the sentence is worked out from the step's own figures when the page opens, so a
// story updates itself after every refresh. The stories themselves are in app/web/stories/.

import type { ReactNode } from "react";
import type { Indicator, Ranking, RankingRow, SeriesRow, TrackRecord } from "@/lib/api";
import type { WarDetail } from "@/lib/osint";
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
// US states (or another country's regions): one figure in its latest year, highest first.
export type StatesData = { name: string; unit: string; year: number; rows: { id: string; name: string; value: number }[];
  row: (name: string) => { id: string; name: string; value: number; rank: number } | undefined;
  refs: { id: string; name: string; value: number }[]; fmt: (v: number | null | undefined) => string };
// Countries as dots (x against y), a year at a time.
export type BubbleData = { years: number[]; first: number; last: number;
  at: (entity: string, year: number) => { x: number; y: number } | null; fmtX: (v: number | null | undefined) => string;
  fmtY: (v: number | null | undefined) => string; names: Record<string, string> };
// A league table of forecasters: the crowd sites and you (Brier score) or named pundits (hit rate).
export type ScoresData = { rows: { name: string; kind: string; n: number; hit: number | null; brier: number | null }[] };
export type WarData = { w: WarDetail };
export type Band = { from: number; to: number; label: string };
export type CityData = { cities: { name: string; country: string; pts: [number, number, boolean][] }[]; first: number; last: number };

export type Step =
  // A world map of one indicator in one year (the indicator's main year if none).
  | { kind: "map"; indicator: string; year?: number; diverging?: boolean; say: (d: RankData) => string }
  // Lines for a few entities, one indicator (or several indicators for one entity: `indicators`).
  | { kind: "lines"; indicator: string; indicators?: string[]; labels?: string[]; colors?: string[]; entities: Named[]; from?: number; to?: number;
      about?: string; // what the figures are, for the "not loaded yet" note before the indicator is in the catalogue
      sameAxis?: boolean; // several indicators in the same unit under different names (two kinds of %): one axis
      bands?: Band[]; // periods shaded on the chart (wars, typed into the story)
      episodes?: boolean; // also shade the app's Big episodes (Episodes page) for these places
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
  // A country's regions (the US states): a map, or bars of the highest and lowest, for one figure in its latest year.
  // `minus` takes another figure away (Democrat share minus Republican share); `per` divides by people (per 1,000);
  // `refs` adds whole countries' figures from a world indicator as marked lines on the bars.
  // `over` divides by another figure (home value over income).
  | { kind: "states"; country?: string; indicator: string; minus?: string; over?: string; per?: "people"; show?: "map" | "bars"; label?: string;
      refs?: { indicator: string; entities: string[] }; say: (d: StatesData) => string }
  // Countries as dots: x against y, sized by people, with a year slider and Play; some countries named and coloured.
  | { kind: "bubbles"; x: string; y: string; from?: number; logX?: boolean; highlight: string[]; say: (d: BubbleData) => string }
  // Forecasts against outcomes (IMF by default): each release's path and what happened for one country,
  // or the typical next-year miss by country.
  | { kind: "track"; indicator: string; entity: string; show: "paths" | "countries"; source?: string; highlight?: string[]; say: (d: TrackRecord) => string }
  // Forecasters scored: the crowd sites and your own forecasts (Brier score), or named pundits (hit rate).
  | { kind: "scores"; who: "crowd" | "pundits"; say: (d: ScoresData) => string }
  // A war tracker: ground held over time and equipment lost (seen against claimed).
  | { kind: "war"; war?: string; say: (d: WarData) => string }
  // One of the app's own views (sea ice circle, electricity map, largest cities), with a fixed sentence.
  | { kind: "view"; view: "seaice" | "electricity" | "cities" | "energyflow"; entity?: string; say: string };

// Groups on the Stories page, in order.
export const STORY_GROUPS = [
  { id: "people", name: "People" },
  { id: "money", name: "Money and homes" },
  { id: "power", name: "War, power and politics" },
  { id: "energy", name: "Energy and climate" },
  { id: "places", name: "Places up close" },
  { id: "forecasts", name: "Forecasts" },
] as const;
export type StoryGroup = (typeof STORY_GROUPS)[number]["id"];

export type Story = {
  id: string; title: string; blurb: string; colour: string; // a strong colour for the gallery card and headings
  group: StoryGroup;
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
