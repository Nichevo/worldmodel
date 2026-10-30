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
  main_year?: number | null; // latest estimate year with good country coverage: where maps open
  available: boolean;
  countries: number;
  default_on: boolean;
  enabled: boolean; // switched on in the Indicators page, so it appears in panel menus
  sources: { source_id: string; series: string; rank: number; notes: string; source_name: string | null; licence: string | null }[];
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

export type DatasetIndicator = {
  source_id: string;
  indicator_id: string;
  name: string;
  domain: string;
  first_year: number | null;
  last_year: number | null;
  last_estimate_year: number | null;
  countries: number;
  row_count: number;
};

export type Dataset = Source & {
  latest_vintage: { vintage: string; release: string; retrieved_at: string; origin: string } | null;
  indicators: DatasetIndicator[];
  row_count: number;
  on_demand: { stored: number; stale: number; budget: WikiBudget; background: boolean } | null; // Wikipedia
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

export type SavedLayout = { name: string; query: string; saved_at: string };

// The Settings page; defaults and ranges live in the contract (worldmodel_contract.local).
export type Settings = {
  click_mode: "popup" | "select";
  hover_sparkline: boolean;
  popup_tabs: boolean;
  side_panel: boolean;
  disk_limit_gb: number;
  pictures_limit_gb: number;
  numbeo_daily: number;
  wikipedia_countries_daily: number;
  wikipedia_cities_daily: number;
  wikipedia_background: boolean;
  history_paused: boolean;
  history_retention_days: number;
};

// Text sources about a country: the CIA Factbook (an edition per year, 1990-2025) and Wikidata facts.
export type TextField = { field: string; field_key: string; content: string };
export type Texts = {
  entity_id: string; source_id: string; editions: (number | null)[]; edition: number | null; vintage: string | null;
  sections: { section: string; fields: TextField[] }[];
};

export type WikiImage = {
  role: "photo" | "flag" | "map"; file: string; src: string | null; width: number | null; height: number | null;
  artist: string | null; licence: string | null; licence_url: string | null; page_url: string | null;
};
export type WikiBudget = { day: string; used: number; limit: number; background_limit: number };
export type Wikipedia = {
  status: "ok" | "stale" | "none" | "off"; message: string | null; budget: WikiBudget;
  page: {
    entity_id: string; title: string; url: string | null; description: string | null; extract: string;
    images: WikiImage[]; wikidata_item: string | null; fetched_at: string; licence: string;
  } | null;
};

export type HistoryKind = "page" | "view" | "indicator" | "pin" | "fetch";
export type HistoryEntry = {
  id: string; at: string; kind: HistoryKind; title: string; url?: string; entity?: string; indicator?: string;
  detail?: string; star: boolean; note: string;
};

export type Popup = {
  entity: string; name: string; type: string; indicator: string; year: number;
  value: number | null; status: string | null; rank: number | null; of: number;
  change10: { from_year: number; value: number } | null;
  region: { entity_id: string; name: string } | null;
  series: { entity: [number, number, string][]; region: [number, number, string][]; world: [number, number, string][] };
};

export type MapRange = { indicator: string; years: number[]; last_estimate_year: number | null; rows: Record<string, (number | null)[]> };

export type StorageLevel = "ok" | "warn" | "critical" | "full";
export type Storage = {
  home: string; total: number; level: StorageLevel; warn_at: number; critical_at: number; freeable: number;
  categories: { key: string; label: string; bytes: number }[];
  limits: { key: string; label: string; used: number; limit: number; level: StorageLevel }[];
};

export type RefreshSource = {
  source_id: string; status?: "new" | "unchanged" | "skipped" | "error"; vintage?: string; seconds?: number;
  download_bytes?: number; rows?: number; added?: number; changed?: number; removed?: number; error?: string; note?: string;
};
export type RefreshRun = {
  build_id: string | null; kind: "refresh" | "build"; status: "ok" | "failed"; started_at: string; finished_at: string | null;
  checks?: Record<"pass" | "warn" | "fail" | "skip", number>; sources: RefreshSource[];
  disk: Record<string, number> | null; backfilled?: boolean; error?: string;
};

export type WhatIfLevers = { tfr: number; e0: number; mig: number; extra: number; phase: number };
export type WhatIfSide = { male: number[]; female: number[] };
export type WhatIfSummary = { total: number; share_0_14: number; share_65_plus: number; old_age_dependency: number | null; median_age: number | null };
export type WhatIf = {
  entity: string; name: string; type: string; base_year: number; years: number[]; groups: string[];
  baseline: number[]; scenario: number[];
  births: { baseline: number[]; scenario: number[] }; deaths: { baseline: number[]; scenario: number[] };
  pyramids: Record<string, { baseline: WhatIfSide; scenario: WhatIfSide }>;
  inputs: Record<"tfr" | "e0" | "net_migration", { baseline: number[]; scenario: number[] }>;
  held: Record<string, number>;
  raw_error: { worst_total_pct: number | null; by_year: Record<string, { total_pct: number; worst_group_pct?: number }> };
  summary: ({ year: number } & Record<"baseline" | "scenario", WhatIfSummary>)[];
  ranges: Record<string, (number | null)[]>;
  levers: WhatIfLevers;
};
export type ForecastErrors = { n: number; bias: number | null; mae: number | null; rmse: number | null };
export type TrackRecord = {
  indicator: string; entity: string | null; name: string | null; releases: string[]; outcomes_from: string | null;
  sources: string[];
  stats: ({ season: "April" | "October"; horizon: number } & ForecastErrors)[];
  paths?: { release: string; points: [number, number][] }[];
  actual?: [number, number][];
  years?: ({ year: number } & ForecastErrors)[];
  countries?: ({ entity_id: string; name: string } & ForecastErrors)[];
};

export type SourceRef = { source_id: string; name: string };
export type ComparedIndicator = {
  indicator_id: string; name: string; unit: string; domain: string; countries: number; differing: number; sources: SourceRef[];
};
export type SourceComparison = {
  indicator: string; entity: string; name: string;
  sources: (SourceRef & { rank: number; points: [number, number, string][] })[];
  differences: { year: number; source_b: string; value_a: number; value_b: number; diff: number; rel: number | null; flagged: boolean }[];
};
export type Divergence = {
  indicator_id: string; indicator_name: string; unit: string; decimals: number; entity_id: string; entity_name: string; year: number;
  source_a: string; source_a_name: string; value_a: number; source_b: string; source_b_name: string; value_b: number;
  diff: number; rel: number | null; flagged: boolean;
};

async function send<T>(method: "PUT" | "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const d = (await res.json()).detail;
      detail = typeof d === "string" ? d : detail;
    } catch {}
    throw new ApiError(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => get<Meta>("/meta"),
  sources: () => get<Source[]>("/sources"),
  datasets: () => get<Dataset[]>("/datasets"),
  checks: () => get<{ check_id: string; kind: string; status: string; detail: string }[]>("/build-checks"),
  entities: (type?: string) => get<Entity[]>("/entities", { type }),
  entity: (id: string) => get<EntityDetail>(`/entities/${encodeURIComponent(id)}`),
  profile: (id: string) => get<ProfileRow[]>(`/entities/${encodeURIComponent(id)}/profile`),
  texts: (id: string, source = "cia_factbook", edition?: number | null) =>
    get<Texts>(`/entities/${encodeURIComponent(id)}/texts`, { source, edition: edition ?? undefined }),
  textHistory: (id: string, key: string, source = "cia_factbook") =>
    get<{ edition: number; field: string; content: string }[]>(`/entities/${encodeURIComponent(id)}/texts/history`, { key, source }),
  wikipedia: (id: string) => get<Wikipedia>(`/entities/${encodeURIComponent(id)}/wikipedia`),
  indicators: () => get<Indicator[]>("/indicators"),
  search: (q: string) => get<SearchHit[]>("/search", { q }),
  series: (indicator: string, entities: string[], start?: number, end?: number) =>
    get<{ rows: SeriesRow[] }>("/series", { indicator, entities: entities.join(","), start, end }).then((r) => r.rows),
  map: (indicator: string, year: number) =>
    get<{ rows: { entity_id: string; value: number; status: string }[] }>("/map", { indicator, year }).then((r) => r.rows),
  memberships: (q: { type?: string; group?: string }) =>
    get<{ group_id: string; group_name: string; member_id: string }[]>("/memberships", q),
  pyramid: (entity: string, year: number) => get<Pyramid>("/pyramid", { entity, year }),
  layouts: () => get<SavedLayout[]>("/layouts"),
  saveLayout: (name: string, query: string) => send<SavedLayout>("PUT", `/layouts/${encodeURIComponent(name)}`, { query }),
  deleteLayout: (name: string) => send<{ deleted: string }>("DELETE", `/layouts/${encodeURIComponent(name)}`),
  settings: () => get<{ settings: Settings; defaults: Settings }>("/settings"),
  saveSettings: (patch: Partial<Settings>) => send<{ settings: Settings; defaults: Settings }>("PUT", "/settings", patch),
  switchIndicators: (changes: Record<string, boolean>) => send<{ changed: number }>("PUT", "/indicator-switches", changes),
  resetIndicators: () => send<{ reset: boolean }>("DELETE", "/indicator-switches"),
  history: (q: { q?: string; kind?: string; starred?: boolean; since?: string; until?: string; limit?: number } = {}) =>
    get<HistoryEntry[]>("/history", { ...q, starred: q.starred ? "true" : undefined }),
  logHistory: (entry: { kind: HistoryKind; title: string; url?: string; entity?: string; indicator?: string; detail?: string }) =>
    send<{ entry: HistoryEntry | null }>("POST", "/history", entry),
  markHistory: (id: string, mark: { star?: boolean; note?: string }) => send<{ id: string; star: boolean; note: string }>("PATCH", `/history/${id}`, mark),
  clearHistory: (keepStarred = true, before?: string) =>
    send<{ deleted: number }>("DELETE", `/history?keep_starred=${keepStarred}${before ? `&before=${before}` : ""}`),
  popup: (entity: string, indicator: string, year: number) => get<Popup>("/popup", { entity, indicator, year }),
  mapRange: (indicator: string, start?: number, end?: number) => get<MapRange>("/map/range", { indicator, start, end }),
  storage: () => get<Storage>("/storage"),
  freeUp: () => send<{ removed: string[]; freed_bytes: number }>("POST", "/storage/free-up"),
  refreshLog: () => get<RefreshRun[]>("/refresh-log"),
  whatif: (entity: string, l: WhatIfLevers) => get<WhatIf>("/whatif", { entity, ...l }),
  trackRecord: (indicator: string, entity?: string) => get<TrackRecord>("/track-record", { indicator, entity }),
  comparedIndicators: () => get<ComparedIndicator[]>("/sources/indicators"),
  compareSources: (indicator: string, entity: string) => get<SourceComparison>("/sources/compare", { indicator, entity }),
  divergence: (q: { indicator?: string; entity?: string; flagged?: boolean; limit?: number }) =>
    get<Divergence[]>("/sources/divergence", { ...q, flagged: q.flagged ? "true" : undefined }),
};
