// Typed helpers for the local worldmodel API (proxied at /api by next.config.mjs).

export type Entity = {
  entity_id: string;
  name: string;
  short_name: string;
  type: string;
  iso3: string | null;
  iso2?: string | null;
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
  ratio?: { numerator: string; denominator: string; multiplier: number }; // one of your ratios
  grade?: Grade | null; // A core, B good, C usable, D exploratory (yours when you set one)
  type?: MeasureType; // level, per person, rate or share...
  starred?: boolean; // kept in every drop-down whatever its grade
};

export type Grade = "A" | "B" | "C" | "D";
export type QualityShow = "A" | "B" | "C" | "all" | "starred";
export type MeasureType = "level" | "per_person" | "rate" | "index" | "money" | "count" | "projection";
export type QualityScore = "history" | "up_to_date" | "coverage" | "standing" | "health" | "definition";
export type IndicatorQuality = { scores: Record<QualityScore, number>; notes: Record<QualityScore, string>; definition: string;
  source_id: string; grade: Grade; worked_grade: Grade; overridden?: boolean; starred: boolean; type: MeasureType };
export type QualityList = { scores: Record<QualityScore, string>; grades: Record<Grade, string>; types: Record<MeasureType, string>;
  weights: Record<QualityScore, number>; indicators: Record<string, IndicatorQuality> };
export type QualityChange = { indicator_id: string; name: string; from?: Grade; to?: Grade; note?: string };
export type QualitySummary = { totals: Record<Grade, number>; by_domain: Record<string, Record<Grade, number>>;
  by_source: Record<string, Record<Grade, number>>; since: string | null;
  changes: { lost: QualityChange[]; gained: QualityChange[]; stale: QualityChange[]; flagged: QualityChange[]; starred_fell: QualityChange[] } | null;
  starred: { indicator_id: string; name: string; grade: Grade | null }[] };
export const GRADE_TEXT: Record<Grade, string> = { A: "Core", B: "Good", C: "Usable", D: "Exploratory" };
export const TYPE_TEXT: Record<MeasureType, string> = { level: "Level", per_person: "Per person", rate: "Rate or share",
  index: "Index or score", money: "Money", count: "Count", projection: "Projection" };

export type Ratio = { id: string; name: string; numerator: string; denominator: string; multiplier: number; unit: string;
  decimals: number; description: string };

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
  trend?: [number, number][]; // the last ten years, for a sparkline and the change since the year before
  rank?: number | null; // among countries, highest first, in the same year and source
  of?: number | null;
  better?: "higher" | "lower" | "neither";
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

export type EnergyFlow = {
  entity: string;
  year: number | null;
  years: number[];
  unit?: string;
  source_id?: string | null;
  vintage?: string | null;
  nodes: { name: string; kind: "source" | "electricity" | "use" | "loss" }[];
  links: { source: string; target: string; value: number }[];
  totals: { primary_supply: number; supply_by_group: Record<string, number>; electricity_generated: number;
    use_by_sector: Record<string, number> } | null;
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

// The same request already on its way is shared rather than sent twice (the menu, the banner
// and the page often ask for /meta, /storage or /problems at the same moment).
const inFlight = new Map<string, Promise<unknown>>();

export function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const url = `/api/v1${path}${qs.toString() ? `?${qs}` : ""}`;
  const known = inFlight.get(url);
  if (known) return known as Promise<T>;
  const p = fetchJson<T>(url).finally(() => inFlight.delete(url));
  inFlight.set(url, p);
  return p;
}

async function fetchJson<T>(url: string): Promise<T> {
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
  problem_banner: boolean;
  events_on_charts: boolean;
  projections_on_charts: boolean; // projected years (dashed) on charts
  chart_end_labels: boolean; // names and latest values at the line ends instead of a legend
  chart_values: boolean; // values written on bars
  chart_findings: boolean; // chart titles say what the chart shows
  event_labels: boolean; // event bands named on the chart
  profile_charts: string; // indicator ids charted on country pages, in order ("" = standard set, "none" = none)
  profile_cards_hidden: string; // country page cards switched off
  profile_average: string; // a group whose average joins country page charts of rates ("" for none)
  profile_saved: Record<string, { charts: string; hidden: string }>; // named country page set-ups
  voting_compare: string; // who a country's UN votes are compared with (ids; eu = EU members' average)
  crisiswatch_fetch: boolean;
  holidays_fetch: boolean; // refresh reads public holidays (Nager.Date) // refresh reads CrisisWatch, one month's page at a time
  crisiswatch_backfill: number; // older months filled in per refresh
  scrape_gap_seconds: number; // seconds between pages read by the scraping tools
  relations_scan: boolean; // look for relationships after each refresh
  relations_indicators: "on" | "all"; // the indicators switched on, or every one (overnight)
  relations_min_countries: number;
  relations_min_years: number;
  relations_max_minutes: number;
  relations_fdr: number; // share of reported pairs allowed to be chance finds
  relations_only_new: boolean; // skip the scan when nothing it reads has changed
  sectors_trade_fetch: boolean; // refresh downloads BACI trade by product
  sectors_trade_from: number; // first year of trade kept
  sectors_hidden: string; // sectors left off the Sectors page, comma-separated ids
  climate_fetch: boolean; // refresh fetches the climate sources
  climate_storms_from: number; // first year of storm tracks kept
  climate_live_map: boolean; // the storms map asks GDACS for what is happening now
  power_fetch: boolean; // refresh reads WRI power plants and gridfinder power lines
  hazards_live: boolean; // the map's fires, heatwave and coral layers read NASA, Open-Meteo and NOAA when on
  internet_speeds_fetch: boolean; // refresh reads Ookla's open Speedtest files
  internet_speeds_from: number; // first year of internet speeds kept
  internet_speeds_per_refresh: number; // Ookla files read in one refresh at most
  party_colours: boolean; // country page charts coloured by the governing party
  party_office: "government" | "state";
  event_kinds: string;
  disaster_min_deaths: number;
  transport_min_deaths: number; // air, sea and rail accidents from this many deaths
  ranks_top_n: number; // lines on a Ranks panel unless it sets its own (0 = all)
  forecast_horizon: number; // years the Forecast button looks ahead
  forecast_ranges: "80+95" | "80" | "none";
  forecast_official: boolean; // also draw the IMF's, OECD's and World Bank's own projections
  base_map: "online" | "local" | "plain"; // map detail under the colours
  map_centre: "pacific" | "atlantic"; // where world maps open centred
  quality_show: QualityShow; // indicator drop-downs list grades up to this (starred ones always)
  quality_type: "" | MeasureType; // and only this measure type
  quality_on_titles: boolean; // the grade beside chart titles
  markets_daily: boolean; // refresh fetches daily exchange rates and gas storage
  storage_chart: "clock" | "lines"; // how the Storage page draws a year
  storage_years: number; // years in the band and average a year is set against
  fx_partners: Record<string, string>; // country id -> its Currency card's partners (comma-separated ids)
  discover_on: boolean; discover_checks: string; discover_keep: number; discover_key_countries: string; discover_key_boost: number;
  discover_merge: boolean; discover_tune: boolean; discover_ai: boolean; discover_better: Record<string, "higher" | "lower" | "neither">;
  news_on: boolean; news_sources: string; news_feeds: string; news_reliefweb_app: string; news_keep_days: number; news_every_hours: number;
  basemap_regions: string; // countries (lower-case ISO3, comma-separated) the local map file holds in full detail
  basemap_world_zoom: number;
  basemap_region_zoom: number;
  basemap_limit_gb: number;
  places_fetch: boolean; // refresh fetches metro and rail, universities and companies
  map_hospital_beds: number; // the Hospitals map layer shows hospitals with at least this many beds
  map_hospitals_unsized: boolean; // ... and well-known hospitals with no bed count
  wikipedia_empires_daily: number; // Long history: Wikipedia pages for empires, dynasties and voyages
  history_borders_fetch: boolean; // refresh fetches Cliopatria's borders
  nature_zones_fetch: boolean; // refresh reads the Köppen-Geiger climate zones once
  nature_climate_extras_fetch: boolean; // Berkeley Earth, PSMSL tide gauges, ND-GAIN
  nature_pollution_fetch: boolean; // UN SDG water and protected key areas
  nature_species_fetch: boolean; // GRIIS, IUCN Red List, EPPO
  nature_protected_fetch: boolean; // WDPA protected areas
  transport_ports_fetch: boolean; // PortWatch, World Port Index, shipping lanes
  transport_air_fetch: boolean; // OurAirports, Eurostat airport traffic
  transport_waterways_fetch: boolean; // inland waterways and river freight
  tourism_fetch: boolean; // UNESCO World Heritage sites
  rivers_fetch: boolean; // HydroRIVERS and HydroBASINS
  cables_fetch: boolean; // TeleGeography undersea cables
  energy_infrastructure_fetch: boolean; // GEM pipelines and LNG terminals
  live_planes: boolean; // the map's Planes now layer
  live_ships: boolean; // the map's Ships now layer
  land_history_fetch: boolean; // HYDE land use back to 1700
  land_cities_fetch: boolean; // GHSL urban centres
  land_trees_fetch: boolean; // Global Forest Watch and council tree lists
  land_nz_fetch: boolean; // NZ LCDB and MPI forestry files saved by hand
  land_city_cover: boolean; // city land cover from the WorldCover pictures
  land_cover_year: "2021" | "2020";
  crowd_polymarket: boolean; // refresh reads Polymarket questions
  crowd_metaculus: boolean; // refresh reads Metaculus (needs METACULUS_TOKEN)
  crowd_manifold: boolean; // refresh reads Manifold questions
  crowd_comments: boolean; // Metaculus comments on followed and busy questions
  crowd_mine: boolean; // your own Metaculus forecasts
  crowd_categories: string; // comma list of politics, economics, geopolitics, climate, science
  crowd_move_points: number; // a move this many points in a week is news
  crowd_score_days: number; // crowd scored on its chance this many days before closing
  inbox_downloads: boolean; // also file recent downloads whose source is certain (copied, never moved)
  inbox_downloads_days: number;
  inbox_downloads_folder: string; // blank: your own Downloads folder
  sources_off: string; // comma-separated sources switched off: never fetched, never on the To do list
  schedule_on: boolean;
  schedule_often: "weekly" | "daily";
  schedule_day: string;
  schedule_time: string;
  backup_on_update: boolean;
  backup_folder: string;
  backup_keep: number;
  backup_big_mb: number;
  views_fetch: boolean; // ViEWS conflict forecasts
  predictions_on_charts: boolean; // your predictions as dots on charts
  api_public_on: boolean; // the public API for scripts, Python, Excel and AI assistants
  api_daily_limit: number; // calls a day per key
  digest_on: boolean; // the weekly digest on the Briefing
  watchlist_on: boolean; // watchlist alerts on the Briefing
  map_look: "plain" | "relief" | "satellite" | "night" | "landcover"; // under the country colours
  relief_style: "classic" | "grey" | "satellite";
  relief_shading: number; // 0..1
  map_colours_over: number; // 0..1, how solid the country colours are over a picture
  night_year: "2016" | "2012" | "latest";
  map_3d: boolean;
  map_3d_exaggeration: number;
  map_tiles: "local_first" | "online";
  map_tiles_starter: boolean;
  map_true_size: boolean;
  space_fetch: boolean;
  space_values: boolean;
  zones_scenario: string; // ssp126, ssp245 or ssp585 for future climate zones
  history_series_fetch: boolean; // refresh fetches long-run figures (OWID)
  history_events_fetch: boolean; // refresh fetches events far back (Wikidata) and NOAA's hazards
  history_event_min_links: number; // events shown: articles in at least this many Wikipedias
  history_events_on_charts: boolean; // events as marks on the long charts
  map_history_year: number; // the year the Map's "World in year" layer shows
  pack_nz: boolean; // refresh fetches the New Zealand pack
  ai_enabled: boolean; // Ask AI buttons, AI notes page, highlight menu's Ask AI
  ollama_url: string;
  ai_model: string; // "" = the first model installed
  ai_model_compare: string; // "" = no side-by-side model
  ai_compare_default: boolean; // side by side from the start
  ai_temperature: number;
  ai_context_tokens: number;
  ai_context_default: string; // context parts ticked by default: data,description,events,highlight
  ai_search_engine: "brave" | "searxng" | "off";
  searxng_url: string;
  ai_search_results: number;
  ai_search_default: boolean; // Search the web ticked when the box opens
  brave_daily_limit: number; // 0 = no limit
  brave_monthly_limit: number; // 0 = no limit
  brave_free_monthly: number;
  brave_price_per_1000: number;
  highlight_menu: boolean; // selecting text shows Ask AI / Save highlight
  start_page: "briefing_after_refresh" | "briefing" | "map"; // what the app opens on
  briefing_days: number; // the Briefing's Happening lane looks back this far
  map_open_layers: string; // layer letters the opening map turns on
  map_window: "7d" | "30d" | "90d" | "1y"; // time window for timed map layers
  map_layer_sets: Record<string, string>; // your own quick sets: name -> layer letters
  news_watch_words: string; // comma-separated words that put a news item on the map
  news_watch_outlets: number; // outlets needed before a reported item shows on the map
  world_dataverse_fetch: boolean; // refresh downloads WORLD Policy's files from Harvard Dataverse
  world_dataverse_name: string;
  world_dataverse_email: string;
  world_dataverse_institution: string;
  world_dataverse_position: string;
  world_dataverse_purpose: string;
  world_dataverse_datasets: string;
  flags_on: boolean; // small flags beside country names
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

// The Long history page (years are whole numbers, negative for BC).
export type LongPower = {
  id: string; name: string; era: "then" | "now" | "dynasty"; group: string | null; entity: string | null; colour: string | null;
  wikipedia: string | null; has_borders: boolean; from?: number; to?: number; peak_km2?: number; peak_year?: number;
};
export type LongSeriesMeta = { name: string; unit: string; from: string; source: string; note?: string };
export type LongFactorMeta = { id: string; name: string; how: string; series?: string[]; periods?: string };
export type LongOverview = {
  counts: { polities: number; long_series: number; history_events: number };
  powers: LongPower[]; dynasties: string[]; regions: { id: string; name: string }[];
  pacific: { id: string; name: string; note: string }; series: Record<string, LongSeriesMeta>;
  factors: LongFactorMeta[]; stages: { n: number; name: string; about: string }[]; event_kinds: Record<string, string>;
  voyages: { id: string; name: string; who: string; power: string | null; from: number; to: number }[];
};
export type LongSize = { id: string; name: string; colour: string | null; group: string | null; points: [number, number | null][] };
export type LongFrame = { key: string; name: string; from: number; to: number; area_km2: number };
export type LongEvent = {
  event_id: string; kind: string; title: string; year: number; end_year: number | null; month: number | null; day: number | null;
  lat: number | null; lon: number | null; place: string | null; entity_id: string | null; region: string | null;
  deaths: number | null; size: number | null; size_unit: string | null; links: number | null; url: string | null;
  source_id: string; when: string;
};
export type LongVoyage = { id: string; name: string; who: string; power: string | null; wikipedia: string;
  stops: { year: number; place: string; lat: number; lon: number }[] };
export type LongPowerCard = {
  id: string; name: string; era: string; group: string | null; entity: string | null; colour: string | null; wikipedia: string | null;
  frames: LongFrame[]; bbox: [number, number, number, number] | null; from: number | null; to: number | null;
  peak: LongFrame | null; events: LongEvent[]; voyages: LongVoyage[]; sizes: [number, number | null][];
};
export type GeoFeature = { type: "Feature"; geometry: GeoJSON.Geometry; properties: Record<string, unknown> };
export type GeoCollection = { type: "FeatureCollection"; features: GeoFeature[]; year?: number };
export type LongRuled = { step: number; regions: { id: string; name: string; note?: string | null;
  segments: { name: string; from: number; to: number; area_km2: number; hue: number; china: boolean }[] }[] };
export type LongLine = { entity: string; entity_name: string; series: string; name: string; unit: string; source: string;
  note: string | null; points: [number, number][] };
export type LongRegionPop = { id: string; name: string; points: [number, number][]; countries: number };
export type LongFactors = {
  countries: string[]; years: number[]; note: string | null;
  factors: { id: string; name: string; how: string; lines: { entity: string; name: string; points: [number, number][] }[] }[];
  index: { entity: string; name: string; points: [number, number][] }[];
};
export type LongThenNow = { measure: string; name: string; note: string | null;
  lines: { id: string; name: string; colour: string | null; points: [number, number | null][]; peak: [number, number] | null }[] };
export type LongCycle = { stages: { n: number; name: string; about: string }[];
  countries: { entity: string; name: string; stage: number | null; reasons: string[]; order_began: number | null;
    figures: Record<string, { value: number; year: number; avg5: number }> }[] };
export type LongCountry = { entity_id: string; name: string; series: LongLine[]; capital: { name: string; lat: number; lon: number } | null;
  ruled: { name: string; part: string; from: number; to: number; hue: number }[]; events: LongEvent[] };

export type HistoryKind = "page" | "view" | "indicator" | "pin" | "fetch" | "ai" | "highlight";
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

// The countries behind a by-country indicator: where a country's migrants come from (in) or live (out).
export type Partners = {
  indicator: string; entity: string; direction: "in" | "out"; year: number | null; years: number[]; total: number | null;
  rows: { entity_id: string; name: string; value: number; source_id: string }[];
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

// One distinct failure from the refresh log (worldmodel_contract.local.problems).
export type Problem = {
  key: string; kind: "check" | "fetch" | "build"; title: string; explain: string; todo: string; summary: string;
  examples: string[]; times: number; in_a_row: number; first_seen: string; last_seen: string; open: boolean;
  fixed_at: string | null; build_id: string | null; check_id?: string; source_id?: string;
};

// Dated events and episodes (/events), and the around-the-event view (/around).
export type EventRow = {
  event_id: string; entity_id: string; entity_name: string | null; source_id: string; kind: string; subkind: string | null;
  title: string; start_date: string; end_date: string | null; precision: "day" | "month" | "year"; size: number | null;
  size_unit: string | null; deaths: number | null; affected: number | null; damage_usd: number | null; place: string | null;
  url: string | null; detail: string | null; color?: string | null; milestone_id?: string;
};
export type EventKind = { kind: string; n: number; sources: string[]; first: string; last: string; subkinds: { subkind: string; n: number }[] };
export type Milestone = { id: string; entity_id: string; title: string; start_date: string; end_date: string | null;
  subkind: string | null; note: string; url: string | null };
export type EventQuery = { entities?: string[]; members?: boolean; kinds?: string[]; sources?: string[]; start?: string;
  end?: string; min_size?: number; q?: string; limit?: number };
export type Around = {
  indicator: { indicator_id: string; name: string; unit: string }; mode: "value" | "index"; compare: string; offsets: number[];
  events: { event_id: string; entity_id: string; entity_name: string | null; title: string; kind: string; subkind: string | null;
    year: number; start_date: string; values: (number | null)[]; compare: (number | null)[] | null; compare_id?: string | null; diff: (number | null)[] | null }[];
  mean: (number | null)[]; mean_compare: (number | null)[] | null; mean_diff: (number | null)[] | null; n: number; note: string;
};

// The world beyond borders: UN voting, CrisisWatch, and places beyond any one country.
export type Voting = {
  entity: string; name: string; lines: { id: string; name: string; points: [number, number][] }[];
  ideal: [number, number][]; closest: { entity_id: string; name: string; value: number }[];
  furthest: { entity_id: string; name: string; value: number }[]; closest_year: number | null; council: EventRow[];
};
export type CrisisWatchMonth = {
  months: string[]; month: string | null;
  rows: { entity_id: string; name: string; subkind: string; title: string; detail: string | null; place: string | null; url: string | null; score: number }[];
};
export type BeyondOther = { entity_id: string; short_name: string; name: string; type: "organisation" | "bloc" | "alliance" | "armed_group";
  description: string | null; valid_from: string | null; valid_to: string | null; sanctions_on: number; first_year: number | null;
  most_imposed: number | null; events: number };
export type Zone = {
  entity_id: string; short_name: string; name: string; description: string | null; indicators: string[]; by_country: string[];
  layers: string[]; treaties: { treaty: string; joined: number; signed_only: number; title: string | null }[];
};

// Laws and rules as values by year.
// The relationship scan (run after each refresh): pairs of figures worth a look.
export type RelationLabel = "together" | "first" | "holds";
export type RelationScan = { build_id: string; finished_at: string; seconds: number; partial: boolean; stale: boolean;
  indicators: number; pairs_possible: number; pairs_tested: number; pairs_thin: number; pairs_kept: number;
  label_counts: Record<RelationLabel, number>; events_tested: number; events_kept: number;
  settings: Record<string, number | string>; domains: string[]; labels: Record<RelationLabel, string>;
  groups: Record<string, string>; event_kinds: string[] };
export type RelationPair = { x: string; y: string; x_name: string; y_name: string; x_domain: string; y_domain: string;
  x_unit: string; y_unit: string; labels: RelationLabel[]; score: number; n_obs: number; n_countries: number;
  year_from: number; year_to: number; r: number; r_two_way: number; q_together: number; beta: number | null;
  slope: number | null; q_holds: number | null; control_used: boolean; first: "x" | "y" | "both" | null; best_lag: number | null;
  q_x_first: number; q_y_first: number; countries_x_first: number | null; countries_y_first: number | null;
  countries_tested: number | null; lags: (number | null)[]; groups: Record<string, [number, number, number]>;
  in_drivers: boolean; near_same: boolean; same_source: boolean; note: string; saved_driver?: boolean; flipped?: boolean;
  built_from?: string | null };
export type BuiltFilter = "last" | "hide" | "only" | "mixed";
export type RelationList = { scan: RelationScan | null; total: number; rows: RelationPair[] };
export type RelationDetail = { pair: RelationPair | null; x: string; y: string; kind_x: string; kind_y: string;
  points: [string, number, number, number][]; names: Record<string, string> };
export type EventLink = { kind: string; indicator_id: string; name: string; domain: string; n_events: number; h: number[];
  effect: (number | null)[]; se: (number | null)[]; n: number[]; effect_3: number; p: number; q: number;
  significant: boolean; built_in: boolean; diverging_before: boolean; pre_trend: number | null; unit: string };
export type Driver = { id: string; driver: string; target: string; slope: number; lag: number; driver_name: string;
  target_name: string; driver_unit: string; target_unit: string; target_kind: "pct" | "diff"; added_at: string };
export type ApiKey = { source: string; name: string; signup: string | null; how: string | null; unlocks: string | null;
  limits: string | null; status: string; active: boolean; env: { name: string; set: boolean }[] };

export type LawRule = { indicator_id: string; name: string; description: string; unit: string; decimals: number; domain: string;
  countries: number; first: number; last: number };
export type LawMap = { indicator: { indicator_id: string; name: string; description: string; unit: string; decimals: number };
  years: number[]; year: number | null; rows: { entity_id: string; name: string; value: number; since: number | null }[] };
export type EntityLaws = { entity: string; rules: { indicator_id: string; name: string; unit: string; decimals: number; year: number;
  value: number; source_id: string; since: number | null; changed: boolean }[]; changes: EventRow[] };

export type WhatIfLevers = { tfr: number; e0: number; mig: number; extra: number; phase: number; hold: number }; // hold: 1 = fertility stays as in the base year
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
  source: string; source_name: string; seasons: string[];
  stats: ({ season: string; horizon: number } & ForecastErrors)[];
  paths?: { release: string; points: [number, number][] }[];
  actual?: [number, number][];
  years?: ({ year: number } & ForecastErrors)[];
  countries?: ({ entity_id: string; name: string } & ForecastErrors)[];
};

export type ForecastPoint = { year: number; mean: number; lo80: number; hi80: number; lo95: number; hi95: number };
export type Forecast = {
  indicator: string; entity: string; unit: string; decimals: number; source: string;
  model: string; model_name: string; transform: "log" | "none"; history_start: number; history_end: number; last_value: number;
  models: { id: string; name: string; mae: number | null; n: number }[]; backtest_origins: number; backtest_depth: number;
  points: ForecastPoint[];
  backtest: { origin: number; year: number; forecast: number; actual: number }[];
  official: { source_id: string; name: string; release: string; points: [number, number][] }[];
};
export type Forecaster = {
  source_id: string; name: string; releases: number | null;
  this_year: ForecastErrors; this_year_common: ForecastErrors; this_year_common_years: number;
  next_year: ForecastErrors; next_year_common: ForecastErrors; next_year_common_years: number;
};

export type Topic = { id: string; name: string; intro: string; map: string; indicators: string[]; missing: string[] };
export type RankingRow = { entity_id: string; name: string; value: number; status: string; source_id: string;
  ten_years_before: number | null; rank: number };
export type Ranking = { indicator: string; year: number | null; rows: RankingRow[]; world: RankingRow | null };

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

// Local AI (Ollama) and web search; see app/api/worldmodel_api/ai.py.
export type AIModel = { name: string; size: number | null; parameters: string | null; family: string | null; quantization: string | null;
  vision?: boolean }; // can take pictures
export type SearchUsage = {
  engine: string; today: number; month: number; daily_limit: number | null; monthly_limit: number | null;
  free_monthly: number; price_per_1000: number; estimated_cost_usd: number; by_day: Record<string, number>;
};
export type AIStatus = {
  enabled: boolean; ollama: { url: string; ok: boolean; error: string | null; version: string | null };
  models: AIModel[]; default_model: string | null; compare_model: string | null;
  search: { engine: string; ready: boolean; why: string | null; brave_key: boolean; usage: SearchUsage };
};
export type WebResult = { title: string; url: string; snippet: string };
export type WebSearch = { query: string; results: WebResult[]; engine?: string; usage?: SearchUsage };
export type ContextPart = { label: string; text: string };
export type AIStats = {
  prompt_tokens: number | null; answer_tokens: number | null; tokens_per_s: number | null; first_token_s: number | null;
  load_s: number | null; total_s: number | null; error?: string;
};
export type AIAnswer = {
  id: string; created_at: string; question: string; context: ContextPart[]; model: string; temperature: number;
  web: WebSearch | null; answer: string; stats: AIStats; title: string; page: string; entity: string | null;
  indicator: string | null; group: string | null; rating: -1 | 0 | 1; tags: string[]; note: string;
  picture?: string; // "sent", or why the chart picture was not sent
};
export type AIUsage = {
  models: { model: string; questions: number; prompt_tokens: number; answer_tokens: number; tokens_per_s: number | null;
    first_token_s: number | null; thumbs_up: number; thumbs_down: number; with_web: number }[];
  questions_by_day: Record<string, number>; search: SearchUsage;
};
export type AskEvent =
  | { type: "start"; id: string; model: string }
  | { type: "thinking" }
  | { type: "token"; text: string }
  | { type: "done"; answer: AIAnswer }
  | { type: "error"; message: string; id?: string };

// Highlights: things kept, see app/api/worldmodel_api/highlights.py.
export type HighlightKind = "text" | "chart" | "table" | "answer";
export type HighlightTable = { columns: string[]; rows: (string | number | null)[][]; unit?: string | null };
export type Highlight = {
  id: string; kind: HighlightKind; created_at: string; updated_at: string | null; title: string; text: string;
  page_url: string; page_title: string; entities: string[]; indicator: string | null; query: string | null;
  table: HighlightTable | null; answer_id: string | null; question: string | null; model: string | null;
  sources: string | null; tags: string[]; note: string; picture: boolean;
};
export type NewHighlight = Partial<Omit<Highlight, "id" | "created_at" | "updated_at" | "picture">> & { kind: HighlightKind; picture?: string };

// Streams one answer: calls onEvent for each line the API sends.
export async function askStream(body: Record<string, unknown>, onEvent: (e: AskEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch("/api/v1/ai/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch {}
    onEvent({ type: "error", message: detail });
    return;
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) onEvent(JSON.parse(line) as AskEvent);
    }
  }
  if (buf.trim()) onEvent(JSON.parse(buf) as AskEvent);
}

export async function send<T>(method: "PUT" | "POST" | "PATCH" | "DELETE", path: string, body?: unknown): Promise<T> {
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

// Cities (GeoNames list; populations from UN WUP; costs from WhereNext and Numbeo).
export type CityRow = {
  city_id: string; name: string; country_id: string; country: string | null; admin1: string | null; lat: number; lon: number;
  capital: "national" | "regional" | ""; geonames_population: number | null; population: number | null;
  population_year: number | null; population_2035: number | null; wn_cost_index: number | null;
  wn_monthly_cost_usd: number | null; numbeo_cost_index: number | null; numbeo_purchasing_power: number | null;
};
export type CitySeries = {
  indicator_id: string; name: string; unit: string; decimals: number; description: string; source: string;
  source_name: string | null; points: { year: number; value: number; status: string }[];
};
export type CityDetail = {
  city: CityRow & { ascii_name: string; timezone: string | null; elevation: number | null; feature_code: string };
  series: CitySeries[]; others: CityRow[]; places?: PlaceRow[];
};
// Metro and rail systems, universities and big companies (Wikidata), biggest first.
export type PlaceKind = "transit" | "university" | "company";
export type PlaceRow = {
  place_id: string; kind: PlaceKind; subkind: string | null; name: string; country_id: string; country: string | null;
  city_id: string | null; city: string | null; lat: number | null; lon: number | null; founded: string | null; url: string | null;
  size: number | null;
  facts: { length_km?: number; stations?: number; riders?: number; riders_year?: number; students?: number; students_year?: number;
    revenue?: number; currency?: string; revenue_year?: number; revenue_usd?: number; staff?: number; staff_year?: number;
    industry?: string; wikidata?: string };
};
export type NumbeoCompare = {
  places: { kind: "cities" | "countries"; id: string; name: string; country_id: string | null; url: string | null; fetched_at: string | null;
    summary: { single_without_rent?: number; family_without_rent?: number }; values: Record<string, number>;
    before: Record<string, number> | null; before_fetched_at: string | null }[];
  items: { item: string; section: string }[];
  years: number[]; year: number | null; since: number | null;
};
export type NumbeoPrices = {
  name: string; budget: { day: string; used: number; limit: number };
  prices: { url: string; fetched_at: string; currency: string; city: string | null; country: string;
    items: { section: string; item: string; value: number }[];
    summary: { single_without_rent?: number; family_without_rent?: number } } | null;
};

// Looking after the sources: the To do list, the inbox, jobs started from the app, every source's health.
export type TodoItem = {
  key: string; kind: "inbox" | "load" | "download" | "failing" | "check" | "key" | "form"; title: string; why: string;
  source_id: string | null; link: string | null; command: string | null; button: "assign" | "load" | "get" | "refresh" | "key" | null;
  what: string | null; folder: string | null; uses: number; uses_names: string[]; order: number;
  name?: string; candidates?: string[]; env?: string[]; times?: number; todo_text?: string;
  mark?: { done?: string; snooze_until?: string; at?: string };
};
export type TodoList = { items: TodoItem[]; count: number; hidden: TodoItem[] };
export type InboxState = {
  inbox: string; downloads: string | null; downloads_on: boolean; downloads_days: number;
  waiting: { name: string; size: number; source_id: string | null; candidates: string[]; how: string; candidate_names: Record<string, string> }[];
  recent: { at: string; name: string; from: string; source_id: string; source_name: string; how: string; to: string }[];
  sources: { source_id: string; name: string }[];
};
export type Job = {
  running: boolean; kind: "refresh" | "inbox" | "get" | "backup" | "load" | null; label: string | null; lines: string[];
  exit_code: number | null; sources?: string[]; started_at?: string; finished_at?: string | null; by?: "app" | "outside";
  progress?: { total: number; done: number; current: string | null; started_at: string; finished_at: string | null; seconds_left: number | null };
};
export type SourceHealth = {
  source_id: string; name: string; publisher: string; cadence: string; url: string;
  state: "failing" | "never" | "due" | "ok" | "off"; off: boolean; by_hand: boolean; method: string | null;
  last_ok: string | null; loaded: string | null; release: string | null; rows: number | null; due: string | null; bytes: number;
  failing: string | null; note: string; uses: number; uses_names: string[]; group: string; fetched: boolean; scraper: boolean; on_demand: boolean;
};
export type Upkeep = {
  schedule: { available: boolean; exists: boolean; next_run?: string; status?: string };
  backup_folder: string; backups: { name: string; bytes: number; at: string }[]; env_file: string;
};
export type ManualFile = {
  source_id: string; name: string; by_hand: boolean; optional: boolean; get: string; what: string; cadence: string; folder: string;
  files: string[]; last_loaded: string | null; todo: "download" | "load" | null; why: string; command: string;
};

export type ScraperRun = { at: string; planned: number; read: number; stopped: string | null; url: string; gap_seconds: number };
export type Scraper = {
  source_id: string; name: string; run: string; reads: string; setting: string | null;
  setting_value: number | boolean | string | null; last_run: ScraperRun | null; last_loaded: string | null;
  today: string | null; problem: string | null;
};
export type Scrapers = { gap_seconds: number; sources: Scraper[] };
export type FetchMethod = "auto" | "site" | "verify" | "file";
export type FetchWay = {
  source_id: string; name: string; can: Exclude<FetchMethod, "auto">[]; kind: "download" | "api" | "pages" | null;
  kind_label: string; choice: FetchMethod; auto: Exclude<FetchMethod, "auto">; method: Exclude<FetchMethod, "auto">;
  since: string | null; why: string | null; retry_from: string | null; last_kind: string | null; last_error: string | null;
  last: { at: string; status: string; note: string } | null;
};
export type FetchWays = { written_at: string | null; labels: Record<FetchMethod, string>; blocked_in_a_row: number; sources: FetchWay[] };

// ----------------------------------------------------------------------------- climate
export type IndName = Record<string, { name: string; unit: string; decimals: number }>;
export type EnsoPhase = { name: string; strength: string; value: number; month: string } | null;
export type ClimateOverview = {
  world: Record<string, [number, number][]>; monthly: Record<string, [string, number][]>;
  sea_ice: Record<string, [number, number][]>; ice_sheets: Record<string, [number, number][]>;
  enso: EnsoPhase; names: IndName; emission_maps: string[];
};
export type ClimateHead = { id: string; label: string; value: string; note: string; tone: string; tab: string; spark: number[] };
export type ClimateHeadlines = {
  keys: string[]; home: string; heads: ClimateHead[]; records: { level: "record" | "decade"; text: string; tab: string }[];
  compare: { id: string; title: string; note?: string; rows: { entity_id: string; name: string; value: number; year: number; text: string; note?: string }[] }[];
  lines: { id: string; name: string; points: [number, number][] }[]; finding: string;
};
export type HeadTileData = { id: string; label: string; value: string; note: string; tone: string; tab: string };
export type Ranked = { indicator: string; name: string; unit: string; decimals: number; year: number; of: number; lower_better: boolean; line: string;
  min: number; max: number; rows: { entity_id: string; name: string; value: number; year: number; rank: number | null; key: boolean }[];
  guide: { value: number; label: string; meeting: number | null } | null };
export type Recovery = { indicator: string; base: number; finding: string;
  lines: { id: string; name: string; points: [number, number][]; latest: number; year: number; of_base: number | null }[] };
export type LandCover = { entity: string; name?: string; first?: number; last?: number; finding?: string;
  parts: { id: string; label: string; points: [number, number][]; latest: number | null; change: number | null }[] };
export type Hazards = { fires: number | null; fires_window: string | null; enabled: boolean;
  hot: { name: string; peak: number; day: string; days: number }[] | null; reefs: { name: string; level: number; label: string }[] | null };
export type LandMix = { entity: string; name: string; year: number; since: number; finding: string;
  parts: { id: string; label: string; indicator: string | null; ha: number | null; share: number; year: number; change: number | null }[] } | null;
export type CountryPorts = { entity: string; to?: string; finding: string; total_12m?: number; change?: number | null;
  ports: { port_id: string; name: string; calls_12m: number; change: number | null; months: [string, number][] }[] };
export type ClimateDisaster = { kind: string; subkind: string; title: string; start_date: string; deaths: number | null;
  affected: number | null; damage_usd: number | null; source_id: string };
export type ClimateCountry = {
  entity: string; temperature: Record<string, [number, number][]>; gases: Record<string, [number, number][]>;
  sectors: Record<string, [number, number][]>; consumption: Record<string, [number, number][]>;
  net_zero: { year: number; status: number | null } | null; carbon_price: [number, number][]; wildfire_area: [number, number][];
  projections: Record<string, [number, number | null, number | null, number | null][]>;
  disasters: ClimateDisaster[]; enso: { el_nino?: string; la_nina?: string; temp_r?: number; years?: number } | null; names: IndName;
};
export type ClimateEnso = {
  series: Record<string, [string, number][]>; phase: EnsoPhase;
  episodes: { subkind: string; title: string; start_date: string; end_date: string | null; size: number }[];
  notes: Record<string, { name: string; el_nino: string; la_nina: string }>;
  link: { entity_id: string; name: string; temp_r: number; years: number; note: boolean }[];
};
export type ClimateStorms = { years: number[]; basins: string[]; counts: number[][]; strong: number[]; strong_by?: number[][]; total?: number };
export type ClimateLive = { rows: { id: string; type: string; name: string; alert: string; country: string; from: string; lon: number; lat: number; url: string }[];
  off?: boolean; error?: string; fetched?: string };
export type ClimatePolicy = { rows: { entity_id: string; name: string; net_zero_year?: number; net_zero_status?: number; carbon_price?: number;
  carbon_price_year?: number; ghg_per_capita?: number; co2_share_world?: number; paris?: string | null }[]; paris_count: number };

// ----------------------------------------------------------------------------- climate zones, pollution, nature
export type ZoneDef = { n: number; code: string; name: string; colour: string; group: string };
export type ZonesInfo = { zones: ZoneDef[]; groups: { code: string; name: string; colour: string }[]; scenarios: Record<string, string>;
  periods: { period: string; scenario: string }[]; scenario: string };
export type ZoneTwin = { city_id: string; name: string; population: number; now: string | null; later: string | null;
  twin: { name: string; country_id: string; city_id: string } | null };
// variant (central, low, high) -> year -> zone code (or group letter) -> % of land
export type ZonesCountry = { entity: string; zones: Record<string, Record<string, Record<string, number>>>;
  groups: Record<string, Record<string, Record<string, number>>>; people: Record<string, number>; people_note?: string;
  twins: ZoneTwin[]; scenario?: string; legend: Omit<ZonesInfo, "periods" | "scenario"> };
export type Pledge = { year: number; base_year: number; cut: number; cut_high?: number; note: string; base_value: number | null;
  target: number | null; target_low: number | null };
export type Pledges = { entity: string; indicator: string; pledges: Pledge[]; note: string };
export type NatureEvent = { kind: string; subkind: string | null; title: string; start_date: string | null; end_date: string | null; precision?: string;
  place: string | null; url: string | null; detail: string | null; entities: string[] };
export type IndicatorNames = Record<string, { name: string; unit: string; decimals: number }>;
export type Latest = Record<string, { year: number; value: number; source_id: string }>;
export type PollutionPage = { tabs: Record<"air" | "water" | "ocean" | "borders", string[]>; names: IndicatorNames; events: NatureEvent[] };
export type PollutionCountry = PollutionPage & { entity: string; latest: Latest };
// ----------------------------------------------------------------------------- transport, tourism, networks
export type Chokepoint = { id: string; name: string; now: number | null; year_before: number | null; change: number | null; capacity: number | null; as_of: string };
export type PortRow = { port_id: string; name: string; entity_id: string | null; calls: number; import_t: number | null; export_t: number | null; year: number };
export type AirportRow = { airport: string; name: string | null; entity_id: string | null; year: number; passengers: number | null; freight_t: number | null };
export type Accident = { subkind: string | null; title: string; start_date: string | null; place: string | null; url: string | null; detail: string | null;
  deaths: number | null; entities: string[] };
export type TransportPage = { tabs: Record<"sea" | "air" | "land" | "safety", string[]>; names: IndicatorNames; chokepoints: Chokepoint[]; choke_finding?: string;
  ports: PortRow[]; airports: AirportRow[]; infrastructure: NatureEvent[]; accidents: Accident[]; min_deaths: number;
  loaded: Record<string, number>; chokepoint_shores: Record<string, string[]> };
export type NetworkItem = { id: string; name: string | null; rfs?: number | null; planned?: boolean | null; status?: string | null;
  area?: number; share?: number; of_country?: number | null; transboundary?: boolean; countries?: number };
export type TransportCountry = { entity: string; tabs: TransportPage["tabs"]; names: IndicatorNames; latest: Latest; ports: PortRow[];
  airports: AirportRow[]; accidents: Accident[]; infrastructure: NatureEvent[]; networks?: Record<string, NetworkItem[]>; counts?: Record<string, number> };
export type ChokepointSeries = { id: string; name: string; points: { week: string; transits: number; tankers: number | null; container: number | null;
  dry_bulk: number | null; cargo: number | null; capacity: number | null }[]; depends: { id: string; name: string }[] };
export type TourismPage = { tabs: Record<"visitors" | "money" | "standing" | "nz", string[]>; names: IndicatorNames;
  top: { entity_id: string; name: string; year: number; value: number; indicator: string }[]; loaded: Record<string, number> };
export type HeritageSite = { name: string; type: string | null; year: number | null; danger?: number; url?: string; about?: string };
export type TourismCountry = { entity: string; tabs: TourismPage["tabs"]; names: IndicatorNames; latest: Latest;
  origins: { id: string; name: string; year: number; value: number; indicator: string }[]; sites: HeritageSite[] };
export type Pest = { code: string; name: string; kind: string; note: string; countries: number; loaded: boolean;
  here?: { present: boolean; statuses: string[] } | null };
export type Comeback = { name: string; countries: string[]; from: string; to: string; how: string; url: string };
export type Restoration = { name: string; countries: string[]; start: number; what: string; url: string };
export type NaturePage = { losing: string[]; invasive: string[]; recovering: string[]; names: IndicatorNames; disease: NatureEvent[];
  pest_events: NatureEvent[]; pests: Pest[]; comebacks: Comeback[]; restoration: Restoration[]; protected: { n: number; km2: number | null } };
export type NatureCountry = { entity: string; latest: Latest; names: IndicatorNames;
  species: { scientific_name: string; category: string; year: number | null; url: string | null }[]; pests: Pest[];
  events: NatureEvent[]; comebacks: Comeback[]; restoration: Restoration[] };

// ----------------------------------------------------------------------------- sectors
export type SectorRank = { entity_id: string; name: string; value: number; share: number | null };
export type SectorMeasure = {
  year: number; years: number[]; rows: SectorRank[]; total: [number, number][];
  concentration: [number, number | null, number | null, number][]; countries: number;
};
export type SectorLead = { year: number; total: number; top: string; top_name: string; top_share: number } | null;
export type SectorCard = {
  id: string; name: string; group: string; kind: string; feeds: string; hidden: boolean; nz: boolean;
  stages: { id: string; name: string; unit: string; exports: SectorLead; production: SectorLead }[];
};
export type SectorList = { groups: Record<string, string>; sectors: SectorCard[]; has_trade: boolean };
// The Sectors overview and the Commodity prices tab.
export type PriceStats = { date: string; value: number; m1: number | null; y1: number | null; y5: number | null; y10: number | null;
  low10: number; high10: number; pos10: number; first: string; real_vs_1980?: number };
export type PriceItem = PriceStats & { id: string; name: string; unit: string; decimals: number; spark: number[] };
export type PriceGroup = { id: string; name: string; sector_group: string | null; index: PriceItem | null; items: PriceItem[] };
export type TradeGroup = { id: string; name: string; year: number; value: number; since: number; then: number; sectors: number;
  top: { entity_id: string; name: string; share: number }[] };
export type SectorOverview = {
  heads: { world_trade: { year: number; value: number; then_year: number; then: number } | null;
    rises: PriceItem[]; falls: PriceItem[];
    concentrated: { sector: string; name: string; stage: string; top: { entity_id: string; name: string; share: number | null } }[] };
  board: PriceGroup[]; trade_groups: TradeGroup[];
  nz: { sector: string; name: string; stage: string; share: number; rank: number; of: number; year: number; price_y1: number | null }[];
  sectors: Record<string, {
    trade: { year: number; value: number; since: number; then: number } | null; price: PriceItem | null;
    makers: { stage: string; year: number; rows: { entity_id: string; name: string; share: number | null }[] } | null;
    nz: { stage: string; what: "exports" | "production"; share: number; rank: number; of: number; year: number } | null }>;
};
export type PriceRow = PriceStats & { id: string; name: string; unit: string; decimals: number; source_id: string | null;
  group: string; group_name: string; sectors: { id: string; name: string }[] };
export type PricesTable = { items: PriceRow[]; groups: { id: string; name: string }[]; deflator: [number, number][] };
export type PriceSeries = { series: { id: string; name: string; unit: string; points: [string, number][] }[]; deflator: [number, number][] };
export type PriceSide = { entity_id: string; name: string; value: number; share: number | null; of_own: number | null };
export type PriceTrade = { stage: string; stage_name: string; sector: string; sellers: PriceSide[]; buyers: PriceSide[];
  sellers_year?: number; buyers_year?: number };
export type SectorRoute = { from: string; from_name: string; to: string; to_name: string; value: number };
export type SectorReliance = { entity_id: string; name: string; production: number; imports: number; exports: number; use: number; reliance: number };
export type SectorStage = {
  id: string; name: string; unit: string; hs: string[]; production_indicator: string | null; production_unit: string;
  how: { inputs?: string; energy?: string; time?: string; waste?: string } | null;
  exports: SectorMeasure | null; imports: SectorMeasure | null; production: SectorMeasure | null; reserves: SectorMeasure | null;
  exports_tonnes: [number, number][]; unit_value: [number, number][]; reliance: SectorReliance[]; routes: SectorRoute[];
  country: { entity_id: string; name: string; series: Record<string, [number, number][]>;
    rank: Record<string, { rank: number | null; of: number; listed: boolean }> };
};
export type SectorCompany = { name: string; country: string; country_name: string; step: string; step_name: string; note: string; nz: boolean };
export type SectorPrice = { id: string; name: string; unit: string; points: [string, number][] };
export type SectorDetail = {
  id: string; name: string; group: string; group_name: string; kind: string; feeds: string; sources: string;
  stages: SectorStage[]; prices: SectorPrice[]; companies: SectorCompany[]; high_hhi: number;
  electric?: { sales_share: Record<string, [number, number][]>; stock_share: Record<string, [number, number][]>;
    names: Record<string, string>; ranking: { entity_id: string; name: string; year: number; value: number }[] };
  battery?: {
    chemistries: Record<string, string | number>[]; high_hhi: number;
    materials: { material: string; sector: string; name: string;
      steps: { stage: string; name: string; year: number; top: SectorRank[]; top3: number | null; hhi: number | null; high: boolean }[] }[];
    rules: { country: string; name: string; year: number; text: string }[];
  };
};
export type ChapterRow = {
  chapter: string; name: string; exports: number | null; imports: number | null; balance: number;
  exports_since: number | null; imports_since: number | null; exports_change: number | null; imports_change: number | null;
  export_partners: { entity_id: string; name: string; value: number }[]; import_partners: { entity_id: string; name: string; value: number }[];
};
export type StandPart = { year: number; value: number; rank: number; of: number; share: number | null };
export type CountryStage = { sector: string; sector_name: string; group: string; stage: string; name: string; unit: string;
  exports?: StandPart; imports?: StandPart; production?: StandPart };
export type SectorsByCountry = {
  country: string; name: string; year: number | null; since: number | null; years: number[];
  chapters: ChapterRow[]; totals: [number, number, number][]; stages: CountryStage[];
  economy: { id: string; name: string; points: [number, number][] }[];
};

// Markets: a currency against its partners, storage levels, and a country's regions.
export type FxPartner = { entity_id: string; name: string; currency: string | null; currency_name: string | null; points: [string, number][] };
export type FxData = {
  entity: string; currency: string | null; currency_name: string | null; mode: "rate" | "index"; partners: FxPartner[];
  first_year: number | null; last_date: string | null; default_partners: boolean; step?: "day" | "week" | "month"; start?: number; end?: number;
  twi: { name: string; points: [string, number][] }[];
  choices: { entity_id: string; currency: string; name: string; currency_name: string }[];
};
export type StorageItem = { indicator_id: string; entity_id: string; entity_name: string; group: string; name: string; unit: string;
  decimals: number; frequency: string; last: string; points: number;
  region_id: string | null; region: string | null; subregion_id: string | null; subregion: string | null; summable: boolean };
export type StorageTotals = {
  indicator_id: string; name: string; unit: string; decimals: number; frequency: string; by: "region" | "subregion" | "country";
  group: string | null; group_name: string; step: "year" | "month"; periods: string[];
  parts: { id: string; name: string; points: [string, number | null][] }[]; countries: number[]; total: [string, number][] };
export type StorageSeries = {
  indicator_id: string; entity_id: string; entity_name: string; name: string; unit: string; decimals: number; frequency: string;
  year: number; years_back: number[]; band: { day: number; low: number; high: number; mean: number }[];
  years: Record<string, [number, number, string][]>;
  latest: { date: string; value: number; average: number | null; year_ago: number | null };
  events: { title: string; kind: string; date: string; day: number }[];
};
export type Regions = {
  country: string; regions: { entity_id: string; name: string; code: string }[];
  measures: { indicator_id: string; name: string; unit: string; decimals: number; source: string | null; years: number[];
    values: Record<string, Record<string, number>> }[];
};

export type Tone = "good" | "bad" | "neutral";
export type Find = {
  key: string; kind: string; category: string; tone: Tone; better?: string; score: number; rank_score: number;
  headline: string; detail: string; entities: string[]; indicator_id?: string; indicator_name?: string; unit?: string; decimals?: number;
  source_id?: string; years?: number[]; value?: number | null; tags: string[]; my_tags: string[]; rating: number; never: boolean;
  first_seen?: string | null; new?: boolean; stale?: boolean; pair?: [string, string];
  merged?: number; members?: { entity_id: string; name: string; detail: string; value?: number | null }[]; // one find for several countries
  chart?: { series: { entity_id: string; name: string; points: [number, number][] }[]; mark: number[] };
  // news items
  source?: string; outlet?: string; date?: string; url?: string | null; topic?: string;
};
export type NewsState = { on: boolean; running: boolean; finished_at?: string | null; due: boolean;
  errors: Record<string, { at: string; error: string }>; last: Record<string, { at: string; items: number }> };
export type DiscoverTab = "finds" | "interesting" | "hidden" | "news";
export type DiscoverFeed = {
  items: Find[]; total: number; names: Record<string, string>; build_id: string; last_visit: string | null; new_count: number;
  facets: { categories: Record<string, number>; kinds: Record<string, number>; tones: Record<string, number>;
    entities: Record<string, number>; tags: Record<string, number> };
  kinds: Record<string, string>; categories: string[]; never: string[]; news: NewsState;
};

// The Briefing, the "Latest on" strip and the map's events: one shared card for everything
// (see app/api/worldmodel_api/briefing.py).
export type BriefKind = "feed" | "find" | "event" | "due" | "yours";
export type BriefCard = {
  kind: BriefKind; key: string; title: string; detail: string; date: string | null; entities: string[]; source: string;
  url: string | null; href: string | null; tone: Tone; group: string | null;
  rating?: string | number; word?: string; confirmed?: boolean; n_outlets?: number; new?: boolean;
  find_kind?: string; chart?: Find["chart"]; // Discover finds: their kind and small chart
};
export type Briefing = {
  days: number; since: string; build_id: string; crisiswatch_month: string | null; key_countries: string[];
  names: Record<string, string>; news_due: boolean;
  lanes: { happening: BriefCard[]; found: BriefCard[]; due: BriefCard[]; yours: BriefCard[] };
};
export type EntityLatest = {
  entity_id: string; days: number; cards: BriefCard[]; names: Record<string, string>;
  crisiswatch: { month: string; subkind: string; label: string; detail: string | null; place: string | null; url: string | null;
    previous: string | null } | null;
};
export type MapEvent = EventRow & { group: string };
export type WatchHit = {
  key: string; word: string; words: string[]; date: string; entity_id: string; entities: string[]; headline: string;
  detail: string; url: string | null; outlets: string[]; urls: string[]; n_outlets: number; confirmed: boolean;
  confirmed_by?: string; place: { name: string; lat: number; lon: number } | null; group: string; tone: Tone;
};
export type MapEvents = { start: string; end: string; events: MapEvent[]; watch: WatchHit[]; words: string[] };


// Religion and languages (/religion, /languages and each country's mix).
export type RelGroup = { id: string; name: string };
export type RelPoint = { year: number; projected: boolean; shares: Record<string, number>; edition?: number; text?: string; people?: number };
export type Religion = {
  groups: RelGroup[]; sources: { id: string; name: string }[]; years: number[]; world: Record<string, RelPoint[]>;
  map: { year: number | null; group: string; since: number | null;
    rows: { entity_id: string; source: string; largest: string; largest_share: number; share: number; change?: number }[] };
};
export type EntityReligion = { entity_id: string; groups: RelGroup[]; sources: { id: string; name: string; points: RelPoint[] }[] };
export type Languages = {
  top: { code: string; name: string; speakers: number; home?: number; countries: number; official_in: number }[];
  lang: string; lang_name: string;
  map: { entity_id: string; share: number; official: number | null }[];
  main: { entity_id: string; code: string; name: string; share: number }[];
  counts: { entity_id: string; lang_count?: number; lang_endangered?: number; lang_official_count?: number }[];
  languages: { code: string; name: string }[];
};
export type CrisisWave = { year: number; share: number; count: number; of: number };
export type Crises = {
  kinds: { id: string; name: string }[];
  selected: string[];
  years: [number, number] | null;
  waves: Record<string, CrisisWave[]>;
  strips: { entity_id: string; years: number; spells: { kind: string; from: number; to: number }[] }[];
  countries: number;
};
export type EntityLanguages = {
  entity_id: string;
  languages: { code: string; name: string; share: number | null; speakers: number | null; official: string | null }[];
  counts: Record<string, number>;
  endangered: { name: string; status: string; family: string; level: number }[];
  factbook: { edition: number; content: string } | null;
};

// Series asked for within a few milliseconds of each other for the same countries and years
// (a country page draws dozens of charts at once) go in one /series-many request: browsers
// open only six connections at a time, so dozens of small requests queue behind each other.
type SeriesWait = { indicator: string; resolve: (r: SeriesRow[]) => void; reject: (e: unknown) => void };
const seriesQueue = new Map<string, { params: Record<string, string | number | undefined>; waits: SeriesWait[] }>();
function batchedSeries(indicator: string, entities: string[], start?: number, end?: number): Promise<SeriesRow[]> {
  const key = `${entities.join(",")}|${start ?? ""}|${end ?? ""}`;
  return new Promise((resolve, reject) => {
    let q = seriesQueue.get(key);
    if (!q) {
      q = { params: { entities: entities.join(","), start, end }, waits: [] };
      seriesQueue.set(key, q);
      setTimeout(() => {
        seriesQueue.delete(key);
        const waits = q!.waits;
        if (waits.length === 1) {
          get<{ rows: SeriesRow[] }>("/series", { indicator: waits[0].indicator, ...q!.params }).then((r) => waits[0].resolve(r.rows), waits[0].reject);
          return;
        }
        const ids = [...new Set(waits.map((w) => w.indicator))];
        const chunks: string[][] = [];
        for (let i = 0; i < ids.length; i += 60) chunks.push(ids.slice(i, i + 60));
        for (const chunk of chunks) {
          get<Record<string, SeriesRow[]>>("/series-many", { indicators: chunk.join(","), ...q!.params })
            .then((by) => waits.filter((w) => chunk.includes(w.indicator)).forEach((w) => w.resolve(by[w.indicator] ?? [])))
            .catch((e) => waits.filter((w) => chunk.includes(w.indicator)).forEach((w) => w.reject(e)));
        }
      }, 8);
    }
    q.waits.push({ indicator, resolve, reject });
  });
}

export const api = {
  briefing: (days?: number) => get<Briefing>("/briefing", { days }),
  entityLatest: (id: string, days = 30) => get<EntityLatest>(`/entities/${encodeURIComponent(id)}/latest`, { days }),
  mapEvents: (start: string, end: string) => get<MapEvents>("/map-events", { start, end }),
  discover: (o: { tab?: DiscoverTab; category?: string; kind?: string; tone?: string; entity?: string; tag?: string; q?: string;
    sort?: string; new?: string; since?: string; until?: string; limit?: number; offset?: number } = {}) => get<DiscoverFeed>("/discover", o),
  discoverMark: (key: string, change: { rating?: number; tags?: string[]; tone?: Tone | null }) =>
    send<{ key: string; rating: number; my_tags: string[]; tone: Tone }>("PUT", `/discover/${encodeURIComponent(key)}`, change),
  discoverNever: (kind: string, on: boolean) => send<{ never: string[] }>("PUT", `/discover-never/${encodeURIComponent(kind)}`, { on }),
  discoverSeen: () => send<{ last_visit: string }>("POST", "/discover-seen"),
  discoverEntity: (entity: string, limit = 5) => get<{ items: Find[]; total: number }>(`/discover-entity/${encodeURIComponent(entity)}`, { limit }),
  discoverRescan: () => send<{ finds: number }>("POST", "/discover-rescan"),
  newsFetch: (force = false) => send<NewsState & { started: boolean }>("POST", `/news/fetch${force ? "?force=true" : ""}`),
  fx: (entity: string, o: { partners?: string; start?: number; end?: number; mode?: "rate" | "index" } = {}) =>
    get<FxData>(`/fx/${encodeURIComponent(entity)}`, o),
  storageList: () => get<StorageItem[]>("/storage-levels"),
  storageSeries: (indicator: string, entity: string, years?: number) =>
    get<StorageSeries>(`/storage-levels/${encodeURIComponent(indicator)}/${encodeURIComponent(entity)}`, { years }),
  storageTotals: (indicator: string, o: { by?: string; group?: string; step?: string; top?: number } = {}) =>
    get<StorageTotals>(`/storage-levels/${encodeURIComponent(indicator)}/totals`, o),
  regions: (country: string) => get<Regions>(`/regions/${encodeURIComponent(country)}`),
  manualFiles: () => get<ManualFile[]>("/manual-files"),
  scrapers: () => get<Scrapers>("/scrapers"),
  fetchMethods: () => get<FetchWays>("/fetch-methods"),
  setFetchMethod: (id: string, method: FetchMethod) => send<FetchWay>("PUT", `/fetch-methods/${encodeURIComponent(id)}`, { method }),
  cities: (q: { country?: string; q?: string; min_population?: number; limit?: number; sort?: string } = {}) =>
    get<{ rows: CityRow[]; note: string | null }>("/cities", q),
  places: (q: { kind?: PlaceKind; country?: string; city?: string; q?: string; limit?: number } = {}) =>
    get<{ rows: PlaceRow[]; note: string | null }>("/places", q),
  city: (id: string) => get<CityDetail>(`/cities/${encodeURIComponent(id)}`),
  cityWikipedia: (id: string) => get<Wikipedia>(`/cities/${encodeURIComponent(id)}/wikipedia`),
  numbeo: (kind: "cities" | "entities", id: string) => get<NumbeoPrices>(`/${kind}/${encodeURIComponent(id)}/numbeo`),
  fetchNumbeo: (kind: "cities" | "entities", id: string, name?: string) =>
    send<NumbeoPrices>("POST", `/${kind}/${encodeURIComponent(id)}/numbeo`, { name: name || null }),
  meta: () => get<Meta>("/meta"),
  aiStatus: () => get<AIStatus>("/ai/status"),
  aiSearch: (question: string, model?: string, query?: string) => send<WebSearch>("POST", "/ai/search", { question, model, query }),
  aiAnswers: (q: { q?: string; entity?: string; indicator?: string; model?: string; limit?: number } = {}) => get<AIAnswer[]>("/ai/answers", q),
  aiPatchAnswer: (id: string, patch: { rating?: -1 | 0 | 1; tags?: string[] | string; note?: string }) => send<AIAnswer>("PATCH", `/ai/answers/${id}`, patch),
  aiDeleteAnswer: (id: string) => send<{ deleted: string }>("DELETE", `/ai/answers/${id}`),
  aiStats: () => get<AIUsage>("/ai/stats"),
  highlights: (q: { q?: string; kind?: string; tag?: string; entity?: string } = {}) =>
    get<{ items: Highlight[]; tags: { tag: string; count: number }[] }>("/highlights", q),
  addHighlight: (item: NewHighlight) => send<Highlight>("POST", "/highlights", item),
  patchHighlight: (id: string, patch: { title?: string; note?: string; tags?: string[] | string }) => send<Highlight>("PATCH", `/highlights/${id}`, patch),
  deleteHighlight: (id: string) => send<{ deleted: string }>("DELETE", `/highlights/${id}`),
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
  quality: () => get<QualityList>("/quality"),
  qualitySummary: () => get<QualitySummary>("/quality/summary"),
  setQuality: (id: string, change: { starred?: boolean; grade?: Grade | null }) =>
    send<IndicatorQuality>("PUT", `/quality/${encodeURIComponent(id)}`, change),
  search: (q: string) => get<SearchHit[]>("/search", { q }),
  series: (indicator: string, entities: string[], start?: number, end?: number) => batchedSeries(indicator, entities, start, end),
  map: (indicator: string, year: number) =>
    get<{ rows: { entity_id: string; value: number; status: string }[] }>("/map", { indicator, year }).then((r) => r.rows),
  memberships: (q: { type?: string; group?: string }) =>
    get<{ group_id: string; group_name: string; member_id: string }[]>("/memberships", q),
  pyramid: (entity: string, year: number) => get<Pyramid>("/pyramid", { entity, year }),
  energyFlow: (entity: string, year?: number) => get<EnergyFlow>("/energy-flow", year ? { entity, year } : { entity }),
  partners: (indicator: string, entity: string, direction: "in" | "out", year?: number, limit = 10) =>
    get<Partners>("/partners", { indicator, entity, direction, year, limit }),
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
  problems: () => get<Problem[]>("/problems"),
  events: (q: EventQuery) => get<EventRow[]>("/events", {
    entities: q.entities?.join(","), members: q.members ? "true" : undefined, kinds: q.kinds?.join(","),
    sources: q.sources?.join(","), start: q.start, end: q.end, min_size: q.min_size, q: q.q, limit: q.limit }),
  numbeoCompare: (q: { year?: number; since?: number } = {}) => get<NumbeoCompare>("/numbeo/compare", q),
  eventKinds: () => get<EventKind[]>("/events/kinds"),
  milestones: () => get<Milestone[]>("/milestones"),
  addMilestone: (m: Partial<Milestone>) => send<Milestone>("POST", "/milestones", m),
  saveMilestone: (id: string, m: Partial<Milestone>) => send<Milestone>("PUT", `/milestones/${id}`, m),
  deleteMilestone: (id: string) => send<{ deleted: string }>("DELETE", `/milestones/${id}`),
  ratios: () => get<Ratio[]>("/ratios"),
  addRatio: (r: Partial<Ratio>) => send<Ratio>("POST", "/ratios", r),
  changeRatio: (id: string, r: Partial<Ratio>) => send<Ratio>("PUT", `/ratios/${id}`, r),
  deleteRatio: (id: string) => send<{ deleted: string }>("DELETE", `/ratios/${id}`),
  voting: (entity: string, compare?: string) => get<Voting>(`/entities/${encodeURIComponent(entity)}/voting`, { compare }),
  crisiswatch: (month?: string) => get<CrisisWatchMonth>("/crisiswatch", { month }),
  religion: (year?: number, group?: string, since?: number) => get<Religion>("/religion", { year, group, since }),
  entityReligion: (id: string) => get<EntityReligion>(`/entities/${encodeURIComponent(id)}/religion`),
  languages: (lang?: string, top?: number) => get<Languages>("/languages", { lang, top }),
  crises: (kind?: string, start?: number, entity?: string) => get<Crises>("/crises", { kind, start, entity }),
  entityLanguages: (id: string) => get<EntityLanguages>(`/entities/${encodeURIComponent(id)}/languages`),
  zones: () => get<Zone[]>("/zones"),
  beyondOthers: () => get<BeyondOther[]>("/beyond/others"),
  relationships: (q: { label?: string; domain?: string; group?: string; q?: string; indicator?: string; drivers?: boolean;
    hide_same?: boolean; first?: boolean; hide_same_source?: boolean; built?: BuiltFilter; limit?: number; offset?: number }) =>
    get<RelationList>("/relationships", { ...q, built: q.built && q.built !== "last" ? q.built : undefined, drivers: q.drivers ? "true" : undefined, first: q.first ? "true" : undefined,
      hide_same: q.hide_same === false ? "false" : undefined, hide_same_source: q.hide_same_source ? "true" : undefined }),
  climate: () => get<ClimateOverview>("/climate"),
  ranked: (indicator: string, keys: string) => get<Ranked>(`/look/ranked/${encodeURIComponent(indicator)}?keys=${encodeURIComponent(keys)}`),
  recovery: (indicator: string, keys: string) => get<Recovery>(`/look/recovery/${encodeURIComponent(indicator)}?keys=${encodeURIComponent(keys)}`),
  landCover: (entity: string) => get<LandCover>(`/look/land-cover/${encodeURIComponent(entity)}`),
  hazards: (entity: string) => get<Hazards>(`/hazards/${encodeURIComponent(entity)}`),
  landMix: (entity: string) => get<LandMix>(`/look/land-mix/${encodeURIComponent(entity)}`),
  transportHeads: (home: string) => get<HeadTileData[]>(`/transport/heads?home=${encodeURIComponent(home)}`),
  countryPorts: (entity: string) => get<CountryPorts>(`/transport/ports/${encodeURIComponent(entity)}`),
  climateHeadlines: (keys: string) => get<ClimateHeadlines>(`/climate/headlines?keys=${encodeURIComponent(keys)}`),
  climateCountry: (id: string) => get<ClimateCountry>(`/climate/country/${encodeURIComponent(id)}`),
  climateEnso: () => get<ClimateEnso>("/climate/enso"),
  climateStorms: () => get<ClimateStorms>("/climate/storms"),
  climateLive: () => get<ClimateLive>("/climate/live"),
  climatePolicy: () => get<ClimatePolicy>("/climate/policy"),
  climatePledges: (id: string) => get<Pledges>(`/climate/pledges/${encodeURIComponent(id)}`),
  climateZones: () => get<ZonesInfo>("/climatezones"),
  climateZonesCountry: (id: string, scenario?: string) => get<ZonesCountry>(`/climatezones/country/${encodeURIComponent(id)}`, { scenario }),
  pollution: () => get<PollutionPage>("/pollution"),
  transport: () => get<TransportPage>("/transport"),
  transportCountry: (id: string) => get<TransportCountry>(`/transport/country/${encodeURIComponent(id)}`),
  chokepoint: (id: string, start?: number) => get<ChokepointSeries>(`/transport/chokepoint/${encodeURIComponent(id)}${start ? `?start=${start}` : ""}`),
  tourism: () => get<TourismPage>("/tourism"),
  tourismCountry: (id: string) => get<TourismCountry>(`/tourism/country/${encodeURIComponent(id)}`),
  pollutionCountry: (id: string) => get<PollutionCountry>(`/pollution/country/${encodeURIComponent(id)}`),
  nature: () => get<NaturePage>("/nature"),
  natureCountry: (id: string) => get<NatureCountry>(`/nature/country/${encodeURIComponent(id)}`),
  protectedAreas: (b: { west: number; south: number; east: number; north: number; limit?: number }) =>
    get<GeoJSON.FeatureCollection>("/nature/protected", b),
  sectors: () => get<SectorList>("/sectors"),
  sectorsOverview: () => get<SectorOverview>("/sectors/overview"),
  sectorPrices: () => get<PricesTable>("/sectors/prices"),
  sectorPriceSeries: (ids: string[]) => get<PriceSeries>("/sectors/prices/series", { ids: ids.join(",") }),
  sectorPriceTrade: (id: string) => get<PriceTrade>(`/sectors/prices/${encodeURIComponent(id)}/trade`),
  sector: (id: string, q: { year?: number; country?: string } = {}) => get<SectorDetail>(`/sectors/${encodeURIComponent(id)}`, q),
  sectorsByCountry: (q: { country?: string; year?: number; since?: number }) => get<SectorsByCountry>("/sectors/by-country", q),
  relationPair: (x: string, y: string) => get<RelationDetail>("/relationships/pair", { x, y }),
  eventLinks: (q: { kind?: string; indicator?: string; built_in?: boolean; diverging?: boolean }) =>
    get<{ scan: RelationScan | null; total: number; rows: EventLink[] }>("/relationships/events",
      { ...q, built_in: q.built_in ? "true" : undefined, diverging: q.diverging ? "true" : undefined }),
  drivers: () => get<Driver[]>("/drivers"),
  addDriver: (driver: string, target: string) => send<Driver>("POST", "/drivers", { driver, target }),
  deleteDriver: (id: string) => send<{ deleted: string }>("DELETE", `/drivers/${encodeURIComponent(id)}`),
  keys: () => get<ApiKey[]>("/keys"),
  setKey: (env: string, value: string) => send<{ env: string; set: boolean; file: string }>("PUT", `/keys/${env}`, { value }),
  todo: () => get<TodoList>("/todo"),
  todoMark: (key: string, action: "done" | "snooze" | "clear", days?: number) =>
    send<TodoList>("PUT", `/todo/${encodeURIComponent(key)}`, { action, days }),
  inbox: () => get<InboxState>("/inbox"),
  inboxAssign: (name: string, source_id: string) => send<{ filed: unknown; job: Job }>("POST", "/inbox/assign", { name, source_id }),
  job: () => get<Job>("/jobs"),
  startJob: (kind: Job["kind"], sources?: string[]) => send<Job>("POST", "/jobs", { kind, sources }),
  sourceHealth: () => get<{ sources: SourceHealth[]; off: string[] }>("/source-health"),
  upkeep: () => get<Upkeep>("/upkeep"),
  setSchedule: (on: boolean, often: string, day: string, time: string) =>
    send<{ ok: boolean; message: string; schedule: Upkeep["schedule"] }>("PUT", "/upkeep/schedule", { on, often, day, time }),
  laws: () => get<LawRule[]>("/laws"),
  lawMap: (indicator: string, year?: number) => get<LawMap>(`/laws/${encodeURIComponent(indicator)}`, { year }),
  entityLaws: (entity: string) => get<EntityLaws>(`/entities/${encodeURIComponent(entity)}/laws`),
  around: (q: { indicator: string; event_id?: string; entity?: string; kind?: string; subkind?: string; q?: string;
    before?: number; after?: number; compare?: string; mode?: string; min_size?: number }) => get<Around>("/around", q),
  whatif: (entity: string, l: WhatIfLevers) => get<WhatIf>("/whatif", { entity, ...l }),
  trackRecord: (indicator: string, entity?: string, source = "imf_weo") => get<TrackRecord>("/track-record", { indicator, entity, source }),
  compareForecasters: (indicator: string, entity?: string) =>
    get<{ indicator: string; entity: string | null; forecasters: Forecaster[] }>("/track-record/compare", { indicator, entity }),
  forecast: (indicator: string, entity: string, horizon: number, official = true) =>
    get<Forecast>("/forecast", { indicator, entity, horizon, official: official ? "true" : "false" }),
  topics: () => get<Topic[]>("/topics"),
  topic: (id: string) => get<Topic>(`/topics/${id}`),
  ranking: (indicator: string, year?: number) => get<Ranking>(`/indicators/${indicator}/ranking`, { year }),
  comparedIndicators: () => get<ComparedIndicator[]>("/sources/indicators"),
  compareSources: (indicator: string, entity: string) => get<SourceComparison>("/sources/compare", { indicator, entity }),
  longOverview: () => get<LongOverview>("/long"),
  longSizes: (powers?: string[]) => get<LongSize[]>("/long/sizes", { powers: powers?.join(",") }),
  longPower: (id: string) => get<LongPowerCard>(`/long/power/${encodeURIComponent(id)}`),
  longShape: (key: string) => get<GeoFeature>(`/long/shape/${encodeURIComponent(key)}`),
  longExpansion: (id: string) => get<GeoCollection>(`/long/power/${encodeURIComponent(id)}/expansion`),
  longWorld: (year: number, geometry = true) => get<GeoCollection>("/long/world", { year, geometry: geometry ? undefined : "false" }),
  longShapes: (keys: string[]) => send<Record<string, GeoJSON.Geometry>>("POST", "/long/shapes", { keys }),
  longRuled: (step = 10) => get<LongRuled>("/long/ruled", { step }),
  longSeries: (entities: string[], series: string[], start?: number, end?: number) =>
    get<LongLine[]>("/long/series", { entities: entities.join(","), series: series.join(","), start, end }),
  longRegions: () => get<LongRegionPop[]>("/long/regions"),
  longEvents: (q: { start?: number; end?: number; kind?: string; region?: string; entity?: string; bbox?: string; limit?: number; min_links?: number } = {}) =>
    get<LongEvent[]>("/long/events", q),
  longVoyages: (power?: string) => get<LongVoyage[]>("/long/voyages", { power }),
  longFactors: (start = 1500, step = 10) => get<LongFactors>("/long/factors", { start, step }),
  longThenNow: (measure: string, powers?: string[]) => get<LongThenNow>("/long/thenandnow", { measure, powers: powers?.join(",") }),
  longCycle: (entities?: string[]) => get<LongCycle>("/long/cycle", { entities: entities?.join(",") }),
  longWikipedia: (id: string) => get<Wikipedia>(`/long/wikipedia/${encodeURIComponent(id)}`),
  longCountry: (id: string) => get<LongCountry>(`/long/country/${encodeURIComponent(id)}`),
  divergence: (q: { indicator?: string; entity?: string; flagged?: boolean; limit?: number }) =>
    get<Divergence[]>("/sources/divergence", { ...q, flagged: q.flagged ? "true" : undefined }),
};

// ----------------------------------------------------------------------------- public API (Settings > API access)
export type PublicKey = { id: string; name: string; start: string; made: string; last_used: string | null; today: number; total: number; daily_limit: number | null };
export type ApiCall = { at: string; who: string; from: string; path: string; query: string; status: number };
export type ApiAccess = { on: boolean; daily_limit: number; keys: PublicKey[]; recent: ApiCall[]; local: boolean; mcp_command: string };
export const apiAccess = {
  get: () => get<ApiAccess>("/api-access"),
  make: (name: string) => send<{ id: string; name: string; key: string }>("POST", "/api-access/keys", { name }),
  revoke: (id: string) => send<{ ok: boolean }>("DELETE", `/api-access/keys/${id}`),
};
