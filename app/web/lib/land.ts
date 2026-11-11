// Land, cities and trees: types and calls for the Land page, the city land card and the
// sector Land cards, and the chart options they share.

import type { EChartsOption, SeriesOption } from "echarts";
import { get, type IndicatorNames } from "@/lib/api";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";
import { compact, formatValue } from "@/lib/format";

export type Pt = [number, number];
export type LandOverview = { entity: string; series: Record<string, Pt[]>; names: IndicatorNames; modelled_before: number; hyde: string[] };
export type LandRanking = { indicator: string; start: number; end: number;
  rows: { entity_id: string; name: string; from: number; to: number; change: number; pct: number | null }[] };
export type LandWhere = { year: number | null; years: number[]; surface_ha: number; land_ha: number; habitable_ha: number;
  agri_ha: number | null; cropland_ha: number | null; pasture_ha: number | null; forest_ha: number | null;
  livestock_calories_share: number; livestock_protein_share: number; about: string };
export type LandClimate = { entity: string; series: Record<string, Pt[]>; names: IndicatorNames };
export type LandCardData = { sector: string; land: { id: string; label: string; by: Record<string, Pt[]> };
  output: { id: string; label: string; by: Record<string, Pt[]> };
  ratios: { label: string; unit: string; by: Record<string, Pt[]> }[];
  regions: { label: string; rows: { e: string; name: string; y: number; v: number }[] } | null;
  entities: string[]; names: Record<string, string>; units: IndicatorNames };
export type Centre = { id: string; name: string; country: string; country_name?: string; people: number | null; people_first: number | null;
  now: number | null; first: number | null; built_km2: number | null; built_first_km2: number | null; growth: number | null;
  built_growth: number | null; density: number | null; area: number | null; lat: number | null; lon: number | null; tree_pct?: number | null };
export type CentreDetail = Centre & { pop: Record<string, number>; built: Record<string, number>; geometry: GeoJSON.Geometry;
  cover: CityCover | null };
export type CityCover = { shares: Record<string, number>; tiles: number; missing: number; zoom: number; year: string; worked_out: string;
  name?: string; country?: string; people?: number | null; area_km2: number; tree_km2: number; trees_estimate: number;
  trees_per_person: number | null };
export type CoverList = { rows: (CityCover & { id: string })[]; job: { state: string; done?: number; total?: number; step?: string; error?: string };
  classes: Record<string, { name: string; color: string }>; trees_per_ha: number };
export type NzLand = { years: number[]; level: number; levels: Record<string, string>; region: string; y0: number; y1: number;
  classes: string[]; cover: Record<string, Record<string, number>>; flows: { from: string; to: string; ha: number }[];
  regions: { id: string; name: string; cover: Record<string, number>; total: number }[] };
export type StreetTrees = { council?: string; councils: { c: string; n: number }[]; total: number;
  species?: { name: string; species: string | null; n: number; height: number | null }[]; planted?: { y: number; n: number }[];
  bbox?: [number, number, number, number] | null };

export const land = {
  overview: (entity = "world") => get<LandOverview>("/land", { entity }),
  ranking: (indicator: string, start: number, per: "change" | "pct") => get<LandRanking>("/land/ranking", { indicator, start, per }),
  where: (year?: number) => get<LandWhere>("/land/where", { year }),
  climate: (entity: string) => get<LandClimate>(`/land/climate/${encodeURIComponent(entity)}`),
  card: (sector: string) => get<LandCardData>(`/land/card/${encodeURIComponent(sector)}`),
  cities: (o: { sort?: string; country?: string; limit?: number; search?: string }) => get<{ rows: Centre[]; total: number }>("/land/cities", o),
  outlines: (ids: string[]) => get<GeoJSON.FeatureCollection>("/land/outlines", { ids: ids.join(",") }),
  city: (cityId: string) => get<CentreDetail>(`/land/city/${encodeURIComponent(cityId)}`),
  cover: () => get<CoverList>("/land/cover"),
  coverStart: async (body: { ids?: string[]; top?: number; country?: string }) => {
    const r = await fetch("/api/v1/land/cover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
    return r.json();
  },
  nz: (o: { level?: number; region?: string; y0?: number; y1?: number }) => get<NzLand>("/land/nz", o),
  trees: (council?: string) => get<StreetTrees>("/land/trees", { council }),
};

// FAOSTAT's land kinds, drawn stacked: what the land is used for (they add up to the land area
// with "other land" on top).
export const LAND_KINDS: { id: string; label: string; color: () => string }[] = [
  { id: "land_cropland_ha", label: "Cropland", color: () => "#d9a441" },
  { id: "land_pasture_ha", label: "Meadows and pastures", color: () => "#a7c957" },
  { id: "land_forest_ha", label: "Forest", color: () => "#2d6a4f" },
];

// LCDB top groups and middle kinds get fixed colours, so a group keeps its colour across charts.
const LCDB_COLOURS: Record<string, string> = {
  "Artificial surfaces": "#c0392b", "Bare or lightly vegetated": "#b4b4b4", "Water bodies": "#2e86c1", Cropland: "#e59866",
  "Grassland, sedge and saltmarsh": "#c5d86d", "Scrub and shrubland": "#a9744f", Forest: "#1e8449",
  "Built-up and transport": "#c0392b", "Urban parkland": "#f1948a", "Mines and dumps": "#7b241c", "Bare ground": "#b4b4b4",
  "Snow and ice": "#e5e8e8", "Alpine vegetation": "#d7bde2", Water: "#2e86c1", "Orchards and vineyards": "#af7ac5",
  "Exotic grassland": "#c5d86d", "Tussock grassland": "#d4ac0d", Wetland: "#48c9b0", "Native scrub": "#a9744f",
  "Exotic scrub": "#f4d03f", "Native forest": "#145a32", "Exotic forest": "#52be80",
};
export function lcdbColour(name: string, i: number): string {
  return LCDB_COLOURS[name] ?? seriesColor(i);
}

const legend = (labels: string[]): EChartsOption["legend"] => ({
  top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, type: "scroll", data: labels, textStyle: { color: cssVar("--ink-2") },
});

// Land use stacked by kind, in hectares, % of land or hectares per person. HYDE's long run
// (cropland and grazing back to 1700) is drawn dashed before FAOSTAT starts.
export function landUseOption(o: LandOverview, mode: "ha" | "pct" | "person", from: number): EChartsOption {
  const base = chrome();
  const s = o.series;
  const area = new Map((s.land_area_ha ?? []).map(([y, v]) => [y, v]));
  const pop = new Map((s.pop_total ?? []).map(([y, v]) => [y, v]));
  const scale = (y: number, v: number): number | null => {
    if (mode === "ha") return v;
    if (mode === "pct") { const a = area.get(y) ?? [...area.values()].at(-1); return a ? (v / a) * 100 : null; }
    const p = pop.get(y); return p ? v / p : null;
  };
  const series: SeriesOption[] = LAND_KINDS.filter((k) => s[k.id]?.length).map((k) => ({
    type: "line", name: k.label, stack: "land", color: k.color(), symbol: "none", areaStyle: { opacity: 0.85 },
    lineStyle: { width: 1, color: cssVar("--surface") }, emphasis: { focus: "series" },
    data: s[k.id].filter(([y]) => y >= from).map(([y, v]) => [y, scale(y, v)]),
  }));
  const hyde = [["hyde_cropland_ha", "Cropland, HYDE (modelled)", "#d9a441"], ["hyde_grazing_ha", "Grazing, HYDE (modelled)", "#6a994e"]] as const;
  for (const [id, label, color] of hyde) {
    const pts = (s[id] ?? []).filter(([y]) => y >= from && y <= o.modelled_before + 10);
    if (pts.length) series.push({ type: "line", name: label, color, symbol: "none", lineStyle: { width: 2, type: "dashed" },
      data: pts.map(([y, v]) => [y, scale(y, v)]) });
  }
  const unit = mode === "ha" ? "ha" : mode === "pct" ? "%" : "ha a person";
  return {
    ...base, grid: { ...(base.grid as object), top: 52 }, legend: legend(series.map((x) => String(x.name))),
    yAxis: { type: "value", name: unit, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) },
      splitLine: { lineStyle: { color: cssVar("--grid") } }, nameTextStyle: { color: cssVar("--muted"), align: "left" } },
    series,
    tooltip: { ...(base.tooltip as object), confine: true, valueFormatter: (v) => (typeof v === "number" ? formatValue(v, unit, mode === "ha" ? 0 : 2) : "–") },
  };
}

// Plain lines, one per key, with an optional unit and dashed keys.
export function linesOption(lines: { label: string; pts: Pt[]; color?: string; dashed?: boolean; axis?: number }[], units: string[]): EChartsOption {
  const base = chrome();
  const years = lines.flatMap((l) => l.pts.map(([y]) => y));
  const lo = Math.min(...years), hi = Math.max(...years);
  return {
    ...base, grid: { ...(base.grid as object), top: lines.length > 1 ? 52 : 28 }, legend: lines.length > 1 ? legend(lines.map((l) => l.label)) : undefined,
    // A single year would give ECharts a zero-width axis; widen it and keep whole years.
    xAxis: { ...(base.xAxis as object), minInterval: 1, ...(years.length && lo === hi ? { min: lo - 1, max: hi + 1 } : {}) },
    yAxis: units.map((u, i) => ({ type: "value" as const, name: u, scale: true, position: i ? "right" as const : "left" as const,
      axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) },
      splitLine: { show: i === 0, lineStyle: { color: cssVar("--grid") } }, nameTextStyle: { color: cssVar("--muted") } })),
    series: lines.map((l, i) => ({ type: "line" as const, name: l.label, color: l.color ?? seriesColor(i), symbol: l.pts.length < 4 ? "circle" : "none", yAxisIndex: l.axis ?? 0,
      lineStyle: { width: 2, type: l.dashed ? "dashed" as const : "solid" as const }, data: l.pts })),
    tooltip: { ...(base.tooltip as object), confine: true, valueFormatter: (v) => (typeof v === "number" ? compact(v) : "–") },
  };
}

// Stacked bars by survey year (NZ land cover), one band per class.
export function stackedYearsOption(years: number[], classes: string[], value: (y: number, c: string) => number, unit: string): EChartsOption {
  const base = chrome();
  return {
    ...base, grid: { ...(base.grid as object), top: 64 }, legend: legend(classes),
    xAxis: { type: "category", data: years.map(String), axisLabel: { color: cssVar("--muted") } },
    yAxis: { type: "value", name: unit, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => compact(v) },
      splitLine: { lineStyle: { color: cssVar("--grid") } } },
    series: classes.map((c, i) => ({ type: "bar" as const, name: c, stack: "c", color: lcdbColour(c, i), emphasis: { focus: "series" as const },
      data: years.map((y) => value(y, c)) })),
    tooltip: { ...(base.tooltip as object), trigger: "axis", confine: true, valueFormatter: (v) => (typeof v === "number" ? `${compact(v)} ${unit}` : "–") },
  };
}

// From-to flows between two surveys as a Sankey (left: the earlier survey's class).
export function flowOption(flows: { from: string; to: string; ha: number }[], y0: number, y1: number, top = 25): EChartsOption {
  const f = flows.slice(0, top);
  const left = [...new Set(f.map((x) => x.from))];
  const right = [...new Set(f.map((x) => x.to))];
  const nodes = [...left.map((n) => ({ name: `${n} (${y0})`, itemStyle: { color: lcdbColour(n, 0) } })),
    ...right.map((n) => ({ name: `${n} (${y1})`, itemStyle: { color: lcdbColour(n, 1) } }))];
  return {
    backgroundColor: "transparent",
    tooltip: { trigger: "item", backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
      valueFormatter: (v) => (typeof v === "number" ? `${compact(v)} ha` : "") },
    series: [{ type: "sankey", left: 8, right: 160, top: 8, bottom: 8, nodeGap: 10, emphasis: { focus: "adjacency" },
      label: { color: cssVar("--ink-2"), fontSize: 11 }, lineStyle: { color: "gradient", opacity: 0.35 },
      data: nodes, links: f.map((x) => ({ source: `${x.from} (${y0})`, target: `${x.to} (${y1})`, value: x.ha })) }],
  };
}

export const hectares = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v >= 1e6 ? `${(v / 1e6).toFixed(v >= 1e8 ? 0 : 1)} million ha` : `${compact(v)} ha`);
