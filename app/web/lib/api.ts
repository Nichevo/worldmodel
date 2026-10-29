// Typed helpers for the local worldmodel API (proxied at /api by next.config.mjs).

export type Entity = {
  entity_id: string;
  name: string;
  short_name: string;
  type: string;
  iso3: string | null;
  valid_from: string | null;
  valid_to: string | null;
};

export type GroupRef = { entity_id: string; short_name: string; type: string; valid_from: string | null; valid_to: string | null };

export type EntityDetail = Entity & {
  synonyms: string | null;
  description: string | null;
  groups: GroupRef[];
  members: GroupRef[];
  membership_history: { member_id: string; short_name: string; valid_from: string | null; valid_to: string | null }[];
  successions: { predecessor_id: string; successor_id: string; date: string; kind: string }[];
};

export type Indicator = {
  indicator_id: string;
  name: string;
  description: string;
  synonyms: string[];
  domain: string;
  unit: string;
  decimals: number;
  breakdowns: string;
  agg_method: string;
  first_year: number | null;
  last_year: number | null;
  last_estimate_year: number | null;
  available: boolean;
  sources: { source_id: string; series: string; rank: number; notes: string }[];
};

export type SeriesRow = {
  entity_id: string;
  indicator_id: string;
  period: string;
  value: number;
  status: "E" | "P";
  source_id: string;
  vintage: string;
  is_aggregate: boolean;
  coverage: number | null;
};

export type ProfileRow = {
  indicator_id: string;
  name: string;
  unit: string;
  decimals: number;
  period: string;
  value: number;
  source_id: string;
  vintage: string;
  is_aggregate: boolean;
  coverage: number | null;
};

export type Meta = {
  build_id: string;
  built_at: string;
  schema_version: string;
  warehouse: string;
  is_sample: boolean;
  vintages: { source_id: string; vintage: string; release: string; retrieved_at: string; origin: string; is_latest: boolean }[];
};

export type Source = {
  source_id: string;
  name: string;
  short_name: string;
  publisher: string;
  url: string;
  licence: string;
  licence_url: string;
  cadence: string;
  attribution: string;
  status: string;
};

export type Pyramid = {
  entity: string;
  year: number;
  groups: { age: string; male?: number; female?: number; total?: number }[];
  years_available: number[];
  status: string | null;
  source_id: string | null;
  vintage: string | null;
};

export type SearchHit = { kind: "entity" | "indicator"; id: string; name: string; detail: string };

export class ApiError extends Error {}

export async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const url = `/api/v1${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new ApiError(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => get<Meta>("/meta"),
  sources: () => get<Source[]>("/sources"),
  checks: () => get<{ check_id: string; kind: string; status: string; detail: string }[]>("/build-checks"),
  entities: (type?: string) => get<Entity[]>("/entities", { type }),
  entity: (id: string) => get<EntityDetail>(`/entities/${encodeURIComponent(id)}`),
  profile: (id: string) => get<ProfileRow[]>(`/entities/${encodeURIComponent(id)}/profile`),
  indicators: () => get<Indicator[]>("/indicators"),
  search: (q: string) => get<SearchHit[]>("/search", { q }),
  series: (indicator: string, entities: string[], start?: number, end?: number) =>
    get<{ rows: SeriesRow[] }>("/series", { indicator, entities: entities.join(","), start, end }).then((r) => r.rows),
  map: (indicator: string, year: number) =>
    get<{ rows: { entity_id: string; value: number; status: string }[] }>("/map", { indicator, year }).then((r) => r.rows),
  pyramid: (entity: string, year: number) => get<Pyramid>("/pyramid", { entity, year }),
};
