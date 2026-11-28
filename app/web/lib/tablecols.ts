"use client";

// Columns of a many-indicator table: what each column is (ColSpec), how it is written in a panel's
// `cols` (tokens), and loading the figures for a set of columns (useTableColumns). Kept apart from
// the workspace panel so any page can put figures side by side in MultiTable.
import { useEffect, useMemo, useState } from "react";
import { api, type Indicator } from "@/lib/api";
import { CHANGE_COL } from "@/lib/workspace";

// One cell: a figure, its status (E estimate, P projection) and, when it is not from the
// column's own year, the year it is from.
export type Cell = { value: number; status: string; year?: number };

// A column ready to draw: its figures by entity.
export type TableColumn = {
  key: string; label: string; unit: string; decimals: number; values: Map<string, Cell>;
  year?: number; // the column's year, shown under its name
  change?: boolean; // a change, written with a sign
  indicator?: string; // the indicator behind it, if any
};

// What a column shows: an indicator at the table's year (year null) or a fixed year, or the
// change in an indicator over `change` years up to the table's year.
export type ColSpec = { indicator: string; year: number | null; change?: number };

// Flags kept in the same list as the column tokens.
export const EXACT_FLAG = "exact"; // no filling of missing years
export const SHADE_FLAG = "shade"; // tint each cell by where it stands in its column
export const FLAGS = new Set([EXACT_FLAG, SHADE_FLAG, CHANGE_COL]);
// The table's sort: "sortby_2" (third column, highest first), "sortby_2_up" (lowest first), "sortby_name".
export const SORT_TOKEN = /^sortby_(name|\d{1,2})(_up)?$/;
export function parseSort(cols: string[]): { col: number | "name"; desc: boolean } {
  const m = cols.map((c) => SORT_TOKEN.exec(c)).find(Boolean);
  if (!m) return { col: 0, desc: true };
  return { col: m[1] === "name" ? "name" : +m[1], desc: !m[2] };
}
export const sortToken = (col: number | "name", desc: boolean) => `sortby_${col}${desc ? "" : "_up"}`;
// Years back a missing figure is filled from, unless the table is set to exact years.
export const FILL_BACK = 10;
export const MAX_COLS = 12;
export const COL_TOKEN = /^[a-z0-9_]+(-\d{4})?$/;

// "gdp_growth" (the table's year) or "gdp_growth-2015" (that year).
export function parseCol(token: string): ColSpec | null {
  if (FLAGS.has(token) || SORT_TOKEN.test(token) || !COL_TOKEN.test(token)) return null;
  const [indicator, y] = token.split("-");
  return { indicator, year: y ? +y : null };
}
export const colToken = (c: ColSpec) => (c.year === null ? c.indicator : `${c.indicator}-${c.year}`);

// The indicator columns of a panel's `cols` (flags left out), in order.
export const colSpecs = (cols: string[]) => cols.map(parseCol).filter((c): c is ColSpec => c !== null);
// The indicator ids a `cols` list uses (for knowing which indicators are in use).
export const colIndicators = (cols: string[]) => colSpecs(cols).map((c) => c.indicator);

type Raw = { entity_id: string; value: number; status: string; year?: number };
const cache = new Map<string, Promise<Raw[]>>();
// Every country's figure for a year; with `back`, a missing year is filled from the latest before it.
export function yearValues(indicator: string, year: number, back = 0): Promise<Raw[]> {
  const key = `${indicator}|${year}|${back}`;
  if (!cache.has(key)) {
    const p = api.map(indicator, year, back);
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return cache.get(key)!;
}

const toCells = (rows: Raw[] | undefined, year: number) =>
  new Map((rows ?? []).map((r) => [r.entity_id, { value: r.value, status: r.status, ...(r.year !== undefined && r.year !== year ? { year: r.year } : {}) }]));

// Load the figures for some columns at the table's `year`. `fill` fills a country's missing year
// with its latest figure from up to FILL_BACK years before (marked with that year). Changes always
// use exact years, so a change is never across a different span than its heading says.
export function useTableColumns(specs: ColSpec[], year: number, indicators: Indicator[], fill = true) {
  const key = specs.map((s) => `${colToken(s)}~${s.change ?? 0}`).join(",");
  const wanted = useMemo(() => {
    const w: { id: string; year: number; back: number }[] = [];
    for (const s of specs) {
      const y = s.year ?? year;
      if (s.change) w.push({ id: s.indicator, year: y, back: 0 }, { id: s.indicator, year: y - s.change, back: 0 });
      else w.push({ id: s.indicator, year: y, back: fill ? FILL_BACK : 0 });
    }
    return w;
  }, [key, year, fill]); // eslint-disable-line react-hooks/exhaustive-deps
  const [loaded, setLoaded] = useState<Map<string, Raw[]>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all(wanted.map((w) => yearValues(w.id, w.year, w.back)
      .catch((e) => { if (live) setError(String(e.message || e)); return [] as Raw[]; })
      .then((v) => [`${w.id}|${w.year}|${w.back}`, v] as const)))
      .then((pairs) => { if (live) { setLoaded(new Map(pairs)); setLoading(false); } });
    return () => { live = false; };
  }, [wanted]);

  const columns = useMemo<TableColumn[]>(() => specs.map((s, i) => {
    const ind = indicators.find((x) => x.indicator_id === s.indicator);
    const name = ind?.name ?? s.indicator;
    const unit = ind?.unit ?? "";
    const decimals = ind?.decimals ?? 1;
    const y = s.year ?? year;
    const k = `${colToken(s)}${s.change ? `~${s.change}` : ""}#${i}`;
    if (s.change) {
      const now = toCells(loaded.get(`${s.indicator}|${y}|0`), y);
      const before = toCells(loaded.get(`${s.indicator}|${y - s.change}|0`), y - s.change);
      const diff = new Map<string, Cell>();
      now.forEach((v, id) => {
        const b = before.get(id);
        if (b) diff.set(id, { value: v.value - b.value, status: v.status });
      });
      return { key: k, label: `${name}: change since ${y - s.change}`, unit: unit === "percent" ? "points" : unit, decimals,
        values: diff, change: true, indicator: s.indicator, year: y };
    }
    return { key: k, label: name, unit, decimals, values: toCells(loaded.get(`${s.indicator}|${y}|${fill ? FILL_BACK : 0}`), y),
      indicator: s.indicator, year: y };
  }), [specs, loaded, indicators, year, fill]); // eslint-disable-line react-hooks/exhaustive-deps
  return { columns, error, loading };
}
