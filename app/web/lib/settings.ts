// The user's settings, shared by every component: loaded once from the API,
// defaults until then (or if the API is down), and updated in place on save.

import { useSyncExternalStore } from "react";
import { api, type Settings } from "@/lib/api";

export const DEFAULT_SETTINGS: Settings = {
  click_mode: "popup",
  hover_sparkline: true,
  popup_tabs: true,
  side_panel: true,
  disk_limit_gb: 100,
  pictures_limit_gb: 2,
  numbeo_daily: 20,
  wikipedia_countries_daily: 20,
  wikipedia_cities_daily: 10,
  wikipedia_background: true,
  history_paused: false,
  history_retention_days: 0,
  problem_banner: true,
  events_on_charts: true,
  projections_on_charts: true,
  profile_charts: "",
  profile_cards_hidden: "",
  profile_average: "",
  profile_saved: {},
  voting_compare: "USA,CHN,RUS,eu",
  crisiswatch_fetch: true,
  holidays_fetch: true,
  crisiswatch_backfill: 12,
  scrape_gap_seconds: 6,
  relations_scan: true,
  relations_indicators: "on",
  relations_min_countries: 30,
  relations_min_years: 10,
  relations_max_minutes: 15,
  relations_fdr: 0.05,
  relations_only_new: true,
  sectors_trade_fetch: true,
  sectors_trade_from: 2005,
  sectors_hidden: "",
  climate_fetch: true,
  climate_storms_from: 1980,
  climate_live_map: true,
  internet_speeds_fetch: true,
  internet_speeds_from: 2019,
  internet_speeds_per_refresh: 8,
  party_colours: false,
  party_office: "government",
  event_kinds: "recession,crisis,coup,conflict,disaster,sport,notable,user",
  disaster_min_deaths: 100,
  ranks_top_n: 10,
  forecast_horizon: 10,
  forecast_ranges: "80+95",
  forecast_official: true,
  base_map: "online",
  map_centre: "pacific",
  quality_show: "B",
  quality_type: "",
  quality_on_titles: false,
  markets_daily: true,
  storage_chart: "clock",
  storage_years: 5,
  fx_partners: {},
  basemap_regions: "nzl",
  basemap_world_zoom: 8,
  basemap_region_zoom: 15,
  basemap_limit_gb: 20,
  places_fetch: true,
  pack_nz: true,
  ai_enabled: true,
  ollama_url: "http://localhost:11434",
  ai_model: "",
  ai_model_compare: "",
  ai_compare_default: false,
  ai_temperature: 0.3,
  ai_context_tokens: 16384,
  ai_context_default: "data,description,events,highlight",
  ai_search_engine: "brave",
  searxng_url: "http://localhost:8080",
  ai_search_results: 5,
  ai_search_default: true,
  brave_daily_limit: 30,
  brave_monthly_limit: 0,
  brave_free_monthly: 1000,
  brave_price_per_1000: 5,
  highlight_menu: true,
};

let current: Settings = DEFAULT_SETTINGS;
let loading: Promise<void> | null = null;
const listeners = new Set<() => void>();

function set(next: Settings) {
  current = next;
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  loading ??= api.settings().then((r) => set({ ...DEFAULT_SETTINGS, ...r.settings })).catch(() => { loading = null; });
  return () => { listeners.delete(l); };
}

export function useSettings(): Settings {
  return useSyncExternalStore(subscribe, () => current, () => DEFAULT_SETTINGS);
}

export async function saveSettings(patch: Partial<Settings>): Promise<Settings> {
  set({ ...current, ...patch }); // show the change at once; the API's answer is the final word
  const r = await api.saveSettings(patch);
  set({ ...DEFAULT_SETTINGS, ...r.settings });
  return r.settings;
}
