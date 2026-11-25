// The Details page behind every map layer: types and calls for /layer-details.

import { get } from "@/lib/api";
import { MAP_LAYERS, mapLayersHref } from "@/lib/workspace";

export type LayerSize = { label: string; unit: string; decimals: number; total: "sum" | "mean" | "max" };
export type LayerInfo = {
  id: string; one: string; many: string; kind: "stored" | "lines" | "trees" | "live" | "events"; note: string;
  name: string | null; description: string | null; source: string | null; vintage: string | null;
  by_country: boolean; country_from: string; size: LayerSize | null; category: string | null;
  fields: { key: string; label: string }[];
  official: { indicator: string; label: string; of: "size" | "count"; coverage: boolean }[];
  indicators: Record<string, string>; group_label: string;
};
export type LayerRow = {
  key: string; name: string; entity_id: string | null; type?: string; count: number; per_m: number | null; per_10k_km2: number | null;
  with_size: number; size_total: number | null; size_per_1000: number | null; largest: { name: string; size: number } | null;
  official: { value: number | null; coverage: number | null }[];
};
export type LayerDetail = {
  layer: LayerInfo;
  totals: { count: number; countries?: number; with_size?: number; size_total?: number | null; placed?: number;
    largest?: { name: string; size: number; entity_id: string | null } | null };
  countries: LayerRow[]; groups: LayerRow[];
  sizes: { label: string; count: number; missing?: boolean }[];
  categories: { label: string; count: number; size_total: number | null }[];
  by_list?: { list: string; count: number; only: number | null; hospital: number; unsure: number; clinic: number }[];
};
export type LayerItem = {
  item_id: string; name: string; countries: string[]; country_names: string[]; lat: number; lon: number; size: number | null;
  category: string | null; url: string | null; placed: boolean | null; fields: Record<string, unknown>; group: string | null;
};
export type LayerOverview = { id: string; many: string; kind: string; count: number | null; countries: number | null;
  size: string | null; category: string | null; available: boolean };
export type CountryLayer = { layer_id: string; many: string; one: string; count: number; rank: number; of: number;
  size: { label: string; unit: string; value: number | null } | null };

export type Grade = "good" | "part" | "thin" | "unknown";
export type CoverageRow = { entity_id: string; name: string; count: number; per_m: number | null; official: number | null;
  basis: string | null; coverage: number | null; estimated: boolean; grade: Grade };
export type LayerCoverage = { layer: LayerInfo; countries: CoverageRow[]; grades: Partial<Record<Grade, number>>; cuts: Record<string, number> };
export type Gap = { city_id: string; name: string; entity_id: string; lat: number; lon: number; population: number; nearest_km: number | null };
export type LayerGaps = { towns: Gap[]; total?: number; checked: number; km: number; people: number; note?: string;
  by_country?: { entity_id: string; name: string; towns: number; people: number }[] };

export const layerApi = {
  coverage: (id: string) => get<LayerCoverage>(`/layer-details/${encodeURIComponent(id)}/coverage`),
  gaps: (id: string, country?: string) => get<LayerGaps>(`/layer-details/${encodeURIComponent(id)}/gaps`, country ? { country } : {}),
  list: () => get<LayerOverview[]>("/layer-details"),
  detail: (id: string) => get<LayerDetail>(`/layer-details/${encodeURIComponent(id)}`),
  items: (id: string, p: { country?: string; q?: string; sort?: "size" | "name"; limit?: number; offset?: number }) =>
    get<{ rows: LayerItem[]; total: number }>(`/layer-details/${encodeURIComponent(id)}/items`, p),
  country: (entity: string) => get<CountryLayer[]>(`/layer-details/country/${encodeURIComponent(entity)}`),
};

// The layers whose items the Details page can count (the rest say why not).
export const DETAIL_LAYERS = new Set([
  "hospitals", "military_bases", "ports", "ports_all", "airports", "power_plants", "lng_terminals", "universities", "companies",
  "major_cities", "transit_stations", "heritage_sites", "visited_sites", "volcanoes", "earthquakes", "tide_gauges",
  "antarctic_stations", "cable_landings", "chokepoints", "cables", "gas_pipelines", "oil_pipelines", "street_trees",
  "fires_now", "fires_week", "heat_now", "city_stress", "conflict_events",
]);
export const detailsHref = (id: string, country?: string) => `/layers/${id}${country ? `?country=${encodeURIComponent(country)}` : ""}`;

export function layerName(id: string): string {
  return MAP_LAYERS.find((m) => m.id === id)?.label ?? id.replace(/_/g, " ");
}

// The main map with this layer on.
export function showOnMapHref(id: string): string | null {
  const m = MAP_LAYERS.find((x) => x.id === id);
  return m ? mapLayersHref(m.letter) : null;
}

// A number as the page shows it: whole numbers with separators, big ones shortened.
export function fmt(v: number | null | undefined, decimals = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const a = Math.abs(v);
  if (a >= 1e12) return `${+(v / 1e12).toFixed(2)} trillion`;
  if (a >= 1e9) return `${+(v / 1e9).toFixed(2)} bn`;
  if (a >= 1e7) return `${+(v / 1e6).toFixed(1)} m`;
  return v.toLocaleString("en", { minimumFractionDigits: 0, maximumFractionDigits: decimals });
}

// A rate per million or per 10,000 km²: two significant figures for small ones.
export function rate(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  if (v === 0) return "0";
  if (v < 1) return v.toPrecision(2);
  return v.toLocaleString("en", { maximumFractionDigits: v < 10 ? 1 : 0 });
}
