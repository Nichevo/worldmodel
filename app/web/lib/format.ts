// Number formatting for values with units from the indicator catalogue.

export function formatValue(value: number | null | undefined, unit: string, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "no data";
  const abs = Math.abs(value);
  if (unit === "persons" || unit.includes("dollars")) {
    const money = unit.includes("dollars") && !unit.includes("per person");
    const prefix = unit === "US dollars" || unit === "US dollars per person" ? "$" : "";
    let text: string;
    if (abs >= 1e12) text = `${(value / 1e12).toFixed(2)} trillion`;
    else if (abs >= 1e9) text = `${(value / 1e9).toFixed(2)} billion`;
    else if (abs >= 1e6) text = `${(value / 1e6).toFixed(2)} million`;
    else text = Math.round(value).toLocaleString("en");
    return money && !prefix ? `${text} intl $` : `${prefix}${text}`;
  }
  const n = value.toLocaleString("en", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  return unit === "percent" ? `${n}%` : n;
}

export function shortUnit(unit: string): string {
  if (unit === "percent") return "%";
  return unit;
}

export function compact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${+(value / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `${+(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${+(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${+(value / 1e3).toFixed(1)}k`;
  return `${+value.toFixed(2)}`;
}

export const SOURCE_LABEL: Record<string, string> = {
  un_wpp: "UN World Population Prospects",
  imf_weo: "IMF World Economic Outlook",
  world_bank_wdi: "World Bank WDI",
  owid_energy: "Our World in Data energy (Ember, Energy Institute, EIA)",
  owid_grapher: "Our World in Data charts (UCDP conflict deaths)",
  cia_factbook: "CIA World Factbook (1990-2025 editions)",
  wikidata: "Wikidata",
  powell_thyne: "Powell and Thyne coup data",
  ucdp_acd: "UCDP/PRIO Armed Conflict Dataset",
  emdat: "EM-DAT (CRED, UCLouvain)",
  notable: "Curated notable episodes",
};

export const SOURCE_SHORT: Record<string, string> = {
  un_wpp: "UN WPP", imf_weo: "IMF WEO", world_bank_wdi: "WDI", owid_energy: "OWID energy", owid_grapher: "OWID charts",
  cia_factbook: "Factbook", wikidata: "Wikidata", powell_thyne: "Powell & Thyne", ucdp_acd: "UCDP", emdat: "EM-DAT",
  notable: "Curated", worldmodel: "From the data",
};
