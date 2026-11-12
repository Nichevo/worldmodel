// The stories on the Stories page, in gallery order. Each is a list of steps (see lib/story.ts);
// every sentence is worked out from the figures when the page opens.

import { ELEC_KINDS } from "@/components/ElectricityMap";
import { ordinal, pct, times, type Story } from "@/lib/story";

const KEY = [{ id: "NZL", name: "New Zealand" }, { id: "AUS", name: "Australia" }, { id: "GBR", name: "United Kingdom" }, { id: "USA", name: "United States" }];
const WORLD = { id: "world", name: "World" };
const NZ = { id: "NZL", name: "New Zealand" };

const fertility: Story = {
  id: "fertility", title: "The great fertility fall", colour: "#c0392b",
  blurb: "In 1950 most of the world had five or more children per woman. Now most countries have fewer than two.",
  sources: "UN World Population Prospects (estimates to the latest year, projections after).",
  steps: [
    { kind: "map", indicator: "tfr", year: 1950, kicker: "1950",
      say: (d) => `In ${d.ranking.year}, ${d.count((v) => v >= 5)} of ${d.ranking.rows.length} countries had five or more children per woman; the world as a whole had ${d.fmt(d.row("world")?.value)}.` },
    { kind: "map", indicator: "tfr", kicker: "Now",
      say: (d) => `By ${d.ranking.year}, only ${d.count((v) => v >= 5)} countries still had five or more, and ${d.count((v) => v < 2.1)} were below 2.1, the rate that keeps a population steady without migration.` },
    { kind: "count", indicator: "tfr", label: "below 2.1 children per woman", test: (v) => v < 2.1, kicker: "Below replacement",
      say: (d) => {
        const y0 = d.years.find((y) => y >= 1970) ?? d.years[0], y1 = d.lastEstimate ?? d.years.at(-1)!;
        const a = d.at(y0), b = d.at(y1), c = d.at(2050);
        return `Countries below replacement went from ${a?.count ?? "–"} in ${y0} to ${b?.count ?? "–"} in ${y1}${c ? `; the UN expects ${c.count} of ${c.total} by 2050` : ""}.`;
      } },
    { kind: "lines", indicator: "tfr", entities: [WORLD, ...KEY], kicker: "To 2100",
      say: (d) => {
        const w = d.last("world"), e = d.end("world");
        return `The world fell from ${d.fmt(d.at("world", 1950))} in 1950 to ${d.fmt(w?.value)} in ${w?.year}${e && w && e.year > w.year ? `, and the UN's middle path has it at ${d.fmt(e.value)} by ${e.year}` : ""}.`;
      } },
    { kind: "bars", indicator: "tfr", top: 8, order: "asc", also: ["NZL", "AUS", "GBR", "USA"], highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => { const r = d.row("NZL"); return r ? `New Zealand: ${d.fmt(r.value)} in ${d.ranking.year}, ${ordinal(r.rank)} highest of ${d.ranking.rows.length}${r.ten_years_before !== null ? `, from ${d.fmt(r.ten_years_before)} ten years before` : ""}. These are the lowest anywhere, with the four key countries added.` : "New Zealand has no figure yet."; } },
  ],
};

const electricity: Story = {
  id: "electricity", title: "Where the world's electricity comes from", colour: ELEC_KINDS.solar.color,
  blurb: "Coal still makes the most power, but solar and wind are the fastest risers. Who switched, and where New Zealand's comes from.",
  sources: "Our World in Data energy (Ember, Energy Institute, EIA).",
  steps: [
    { kind: "lines", indicator: "coal_share_elec", indicators: ["coal_share_elec", "gas_share_elec", "solar_share_elec", "wind_share_elec", "hydro_share_elec"],
      labels: ["Coal", "Gas", "Solar", "Wind", "Hydro"], colors: [ELEC_KINDS.coal.color, ELEC_KINDS.gas.color, ELEC_KINDS.solar.color, ELEC_KINDS.wind.color, ELEC_KINDS.hydro.color],
      entities: [WORLD], from: 2000, kicker: "The world",
      say: (d) => {
        const c = d.last("world", 0), s = d.last("world", 2), w = d.last("world", 3);
        return c ? `Coal made ${d.fmt(c.value, 0)} of the world's electricity in ${c.year}${d.at("world", 2000, 0) !== null ? ` (${d.fmt(d.at("world", 2000, 0), 0)} in 2000)` : ""}; solar and wind together made ${d.fmt((s?.value ?? 0) + (w?.value ?? 0), 2)}, from almost nothing in 2000.` : "World figures are not loaded yet.";
      } },
    { kind: "view", view: "electricity", kicker: "On the map",
      say: "Each source's share, zoomed out for the world, in for each continent and then each country: the faded bar is ten years before." },
    { kind: "bars", indicator: "solar_share_elec", by: "change", top: 10, also: ["NZL"], highlight: ["NZL"], kicker: "Fastest switchers",
      say: (d) => {
        const best = [...d.ranking.rows].filter((r) => r.ten_years_before !== null).sort((a, b) => (b.value - b.ten_years_before!) - (a.value - a.ten_years_before!))[0];
        return best ? `${best.name} added the most solar: from ${d.fmt(best.ten_years_before)} of its electricity to ${d.fmt(best.value)} in ten years to ${d.ranking.year}.` : "No ten-year change to show yet.";
      } },
    { kind: "lines", indicator: "hydro_share_elec", indicators: ["hydro_share_elec", "renewables_share_elec", "gas_share_elec", "coal_share_elec"],
      labels: ["Hydro", "All renewables", "Gas", "Coal"], colors: [ELEC_KINDS.hydro.color, ELEC_KINDS.other.color, ELEC_KINDS.gas.color, ELEC_KINDS.coal.color],
      entities: [NZ], from: 1990, kicker: "Where New Zealand sits",
      say: (d) => {
        const h = d.last("NZL", 0), r = d.last("NZL", 1);
        return h ? `New Zealand: hydro made ${d.fmt(h.value, 0)} of its electricity in ${h.year}, and renewables of every kind ${d.fmt(r?.value, 1)}: geothermal and wind fill most of the rest.` : "New Zealand's figures are not loaded yet.";
      } },
  ],
};

const cities: Story = {
  id: "cities", title: "Cities that exploded", colour: "#8e2a1c",
  blurb: "Lagos, Dhaka and Kinshasa have grown many times over while Tokyo and London barely moved.",
  sources: "GHSL urban centres (European Commission JRC): people in each city's built-up area, 1975 to 2030.",
  steps: [
    { kind: "cities", names: ["Lagos", "Dhaka", "Kinshasa", "Tokyo", "London"], kicker: "Fifty years",
      say: (d) => {
        const g = d.cities.map((c) => ({ c, a: c.pts[0]?.[1] ?? 0, b: c.pts.find((q) => q[2])?.[1] ?? c.pts.at(-1)?.[1] ?? 0 }));
        const fast = [...g].sort((x, y) => y.b / (y.a || 1) - x.b / (x.a || 1))[0];
        const slow = [...g].sort((x, y) => x.b / (x.a || 1) - y.b / (y.a || 1))[0];
        return `From ${d.first} to today, ${fast.c.name} grew ${times(fast.b, fast.a)} over; ${slow.c.name} grew by ${pct(slow.b - slow.a, slow.a)}.`;
      } },
    { kind: "view", view: "cities", kicker: "The largest cities",
      say: "Every large city as a bubble, by continent, coloured by how much it has grown: press Play to watch them swell." },
    { kind: "bars", indicator: "urban_share", top: 0, also: ["JPN", "GBR", "AUS", "NZL", "USA", "CHN", "NGA", "IND", "BGD"], highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => { const r = d.row("NZL"); return r ? `${d.fmt(r.value)} of New Zealanders live in towns and cities (${d.ranking.year}), ${ordinal(r.rank)} of ${d.ranking.rows.length} countries.` : "New Zealand has no figure yet."; } },
  ],
};

const arctic: Story = {
  id: "arctic", title: "The Arctic's shrinking summer", colour: "#2c4f9e",
  blurb: "The sea ice around the North Pole now melts back further each September than it did forty years ago.",
  sources: "NSIDC Sea Ice Index (daily extent), NASA GISTEMP, NOAA Mauna Loa CO2, World Bank.",
  steps: [
    { kind: "view", view: "seaice", kicker: "The year round",
      say: "Each ring is a year: the further in, the less ice. The summer low, in September, has moved in the most." },
    { kind: "lines", indicator: "co2_ppm", entities: [WORLD], kicker: "What drives it", about: "carbon dioxide in the air (NOAA Mauna Loa)",
      say: (d) => { const l = d.last("world"); const f = d.rows[0]?.[0]; return l && f ? `Carbon dioxide in the air: ${d.fmt(f.value)} in ${f.period}, ${d.fmt(l.value)} in ${l.year}.` : "CO2 figures are not loaded yet."; } },
    { kind: "lines", indicator: "temp_anomaly_world", entities: [WORLD], kicker: "Warmer", about: "the world's temperature (NASA GISTEMP)",
      say: (d) => { const l = d.last("world"); return l ? `The world was ${d.fmt(l.value)} warmer than its 1951-1980 average in ${l.year}.` : "Temperature figures are not loaded yet."; } },
    { kind: "bars", indicator: "co2_per_capita", top: 10, also: ["NZL", "AUS", "GBR", "USA"], highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => { const r = d.row("NZL"); return r ? `New Zealand put out ${d.fmt(r.value)} of CO2 a person in ${d.ranking.year}, ${ordinal(r.rank)} of ${d.ranking.rows.length} countries.` : "New Zealand has no figure yet."; } },
  ],
};

const nz20: Story = {
  id: "nz-in-numbers", title: "New Zealand in 20 numbers", colour: "#111111",
  blurb: "Twenty figures that sum up the country, where each puts it among the world's countries, and what changed in ten years.",
  sources: "UN, World Bank, IMF, OWID and others: each figure's own page names its source.",
  steps: [
    { kind: "tiles", entity: "NZL", max: 20, kicker: "At a glance",
      indicators: ["pop_total", "tfr", "life_expectancy", "median_age", "pop_share_65_plus", "net_migration_rate", "urban_share", "gdp_per_capita_usd",
        "gdp_growth", "inflation", "unemployment", "govt_debt_gdp", "military_spending_gdp", "renewables_share_elec", "co2_per_capita",
        "homicide_rate", "tertiary_enrolment", "gini", "hdi", "democracy_eiu", "forest_share_land", "old_age_dependency_ratio", "hydro_share_elec"],
      say: (d) => {
        // its highest placings among countries, by share of the way down the list
        const best = [...d.rows].sort((a, b) => a.row.rank / a.of - b.row.rank / b.of).slice(0, 3);
        const list = best.map((r) => `${((x) => x.charAt(0).toLowerCase() + x.slice(1))(r.ind.name.replace(/ \(.*\)$/, "").replace(/,.*$/, ""))} (${ordinal(r.row.rank)} of ${r.of})`);
        return `${d.rows.length} figures; New Zealand places highest on ${list.slice(0, -1).join(", ")}${list.length > 1 ? " and " : ""}${list.at(-1) ?? ""}.`;
      } },
    { kind: "lines", indicator: "pop_total", entities: [NZ], from: 1950, kicker: "People",
      say: (d) => { const l = d.last("NZL"), e = d.end("NZL"); return l ? `${d.fmt(l.value)} people in ${l.year}, from ${d.fmt(d.at("NZL", 1950))} in 1950${e && e.year > l.year ? `; ${d.fmt(e.value)} expected by ${e.year}` : ""}.` : "Population figures are not loaded yet."; } },
    { kind: "lines", indicator: "gdp_per_capita_usd", entities: KEY, from: 1990, kicker: "Income",
      say: (d) => { const l = d.last("NZL"), a = d.last("AUS"); return l ? `GDP per person: ${d.fmt(l.value)} in ${l.year}${a ? `, against Australia's ${d.fmt(a.value)}` : ""}.` : "Income figures are not loaded yet."; } },
  ],
};

export const STORIES: Story[] = [fertility, electricity, cities, arctic, nz20];
export const storyById = (id: string) => STORIES.find((s) => s.id === id);
