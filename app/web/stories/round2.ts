// The third set of stories (fifteen). Like the others, every sentence is worked out from the
// figures when the page opens, and each ends on where New Zealand sits.

import { ordinal, pct, type Named, type RankData, type Story } from "@/lib/story";

const NZ = { id: "NZL", name: "New Zealand" };
const AU = { id: "AUS", name: "Australia" };
const UK = { id: "GBR", name: "United Kingdom" };
const US = { id: "USA", name: "United States" };
const KEY = [NZ, AU, UK, US];
const KEY_IDS = ["NZL", "AUS", "GBR", "USA"];
const WORLD = { id: "world", name: "World" };
const e = (id: string, name: string): Named => ({ id, name });

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
// "2023-04-01" -> "April 2023"
const month = (iso: string) => `${MONTHS[+iso.slice(5, 7) - 1] ?? ""} ${iso.slice(0, 4)}`.trim();

function whereNz(d: RankData, what: string, after = ""): string {
  const r = d.row("NZL");
  if (!r) return "New Zealand has no figure yet.";
  const ten = r.ten_years_before !== null && r.ten_years_before !== undefined ? `, from ${d.fmt(r.ten_years_before)} ten years before` : "";
  return `New Zealand: ${d.fmt(r.value)} ${what} in ${d.ranking.year}, ${ordinal(r.rank)} of ${d.ranking.rows.length} countries${ten}.${after ? ` ${after}` : ""}`;
}
const top3 = (d: RankData) => d.ranking.rows.slice(0, 3).map((r) => `${r.name} (${d.fmt(r.value)})`).join(", ");

// ---------------------------------------------------------------- people
const religion: Story = {
  id: "no-religion", group: "people", title: "Losing our religion", colour: "#7d5a9e",
  blurb: "\"No religion\" is now the most common answer in New Zealand, and close to it in Australia and the UK. Elsewhere faith is holding.",
  sources: "Pew Research Center religious composition, national censuses (through the app's religion figures).",
  steps: [
    { kind: "map", indicator: "rel_none_share", kicker: "No religion",
      say: (d) => `Share of people with no religion, ${d.ranking.year}: highest in ${top3(d)}; ${d.count((v) => v < 5)} of ${d.ranking.rows.length} countries are under 5%.` },
    { kind: "bars", indicator: "rel_none_share", top: 12, also: KEY_IDS, highlight: ["NZL"], kicker: "The least religious",
      say: (d) => { const a = d.row("AUS"), u = d.row("GBR"), s = d.row("USA");
        return whereNz(d, "with no religion", a && u && s ? `Australia ${d.fmt(a.value)}, the UK ${d.fmt(u.value)}, the US ${d.fmt(s.value)}.` : ""); } },
    { kind: "bars", indicator: "rel_largest_share", top: 10, order: "asc", also: KEY_IDS, highlight: ["NZL"], kicker: "Where no one faith dominates",
      say: (d) => { const r = d.row("NZL"); const t = d.ranking.rows.at(-1);
        return r ? `The largest group (religious or not) is only ${d.fmt(r.value)} of New Zealanders. In ${t?.name ?? "the most uniform countries"} it is ${d.fmt(t?.value)}.` : "Share of the largest religious group."; } },
  ],
};

const trust: Story = {
  id: "trust", group: "people", title: "Trust, happiness and each other", colour: "#2e7d6b",
  blurb: "The Nordics and New Zealand say most people can be trusted; much of Latin America and Africa says the opposite. Does trust go with being happy?",
  sources: "World Values Survey and European Values Study (through Our World in Data); waves run in different years in each country.",
  steps: [
    { kind: "map", indicator: "wvs_trust", kicker: "Most people can be trusted",
      say: (d) => `Share saying most people can be trusted: ${top3(d)} at the top; ${d.count((v) => v < 15)} of ${d.ranking.rows.length} countries are under 15% (latest survey, up to ${d.ranking.year}).` },
    { kind: "bubbles", x: "wvs_trust", y: "wvs_happy", latest: true, highlight: [...KEY_IDS, "DNK", "NOR", "BRA", "CHN"], kicker: "Trust and happiness",
      say: (d) => { const n = d.at("NZL", d.last), b = d.at("BRA", d.last);
        return n ? `New Zealanders: ${d.fmtX(n.x)} trust most people, ${d.fmtY(n.y)} say they are happy${b ? `; Brazilians ${d.fmtX(b.x)} and ${d.fmtY(b.y)}` : ""}. Trusting countries tend to be happy ones, though plenty of low-trust countries are happy too.` : "Trust against happiness."; } },
    { kind: "bars", indicator: "wvs_trust", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "saying most people can be trusted") },
  ],
};

const schooling: Story = {
  id: "schooling", group: "people", title: "The great schooling", colour: "#336699",
  blurb: "In 1970 the typical adult in most countries had a few years of school. Now most have ten or more, and university is normal in rich countries.",
  sources: "Wittgenstein Centre (years of schooling, highest education), UNESCO (through the World Bank).",
  steps: [
    { kind: "count", indicator: "wic_mys", label: "where adults average 10 or more years of school", test: (v) => v >= 10, kicker: "Ten years or more",
      say: (d) => { const y1 = d.lastEstimate ?? d.years.at(-1)!; const a = d.years.find((y) => y >= 1970) ?? d.years[0];
        const c = d.at(2050);
        return `Countries where adults average ten or more years of school: ${d.at(a)?.count ?? "–"} in ${a}, ${d.at(y1)?.count ?? "–"} in ${y1}${c ? `, and ${c.count} expected by 2050` : ""}.`; } },
    { kind: "lines", indicator: "tertiary_enrolment", entities: [...KEY, e("KOR", "South Korea")], from: 1980, kicker: "University",
      say: (d) => { const n = d.last("NZL"), k = d.last("KOR"), n0 = d.at("NZL", 1980);
        return n ? `University and other tertiary enrolment in New Zealand: ${d.fmt(n.value)} of the age group in ${n.year}${n0 !== null ? `, from ${d.fmt(n0)} in 1980` : ""}${k ? `; South Korea ${d.fmt(k.value)}` : ""}. Figures over 100% count older students.` : "Tertiary enrolment."; } },
    { kind: "bars", indicator: "literacy_rate", top: 10, order: "asc", kicker: "Still left behind",
      say: (d) => { const t = d.ranking.rows.at(-1); return t ? `Adult literacy is lowest in ${t.name} (${d.fmt(t.value)}, ${d.ranking.year}); ${(() => { const k = d.count((v) => v < 50); return k === 1 ? "1 country is" : `${k} countries are`; })()} under half.` : "Literacy."; } },
    { kind: "bars", indicator: "wic_edu_post_secondary", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "of adults with education after school") },
  ],
};

// ---------------------------------------------------------------- money, homes and work
const wages: Story = {
  id: "what-a-wage-buys", group: "money", title: "What a wage buys", colour: "#9c6b1d",
  blurb: "Minimum wages, typical pay and prices side by side, at equal buying power: why Australian pay goes further than New Zealand's.",
  sources: "ILO (minimum wage, average earnings, in PPP dollars), World Bank (price level).",
  steps: [
    { kind: "bars", indicator: "ilo_min_wage_ppp", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Minimum wage",
      say: (d) => { const n = d.row("NZL"), a = d.row("AUS"); return n ? `A month on the minimum wage buys ${d.fmt(n.value)} of goods in New Zealand at equal buying power (${d.ranking.year}), ${ordinal(n.rank)} of ${d.ranking.rows.length}${a ? `; in Australia ${d.fmt(a.value)}` : ""}.` : "Minimum wages at equal buying power."; } },
    { kind: "bars", indicator: "ilo_earnings_ppp", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Typical pay",
      say: (d) => whereNz(d, "average monthly earnings at equal buying power") },
    { kind: "bars", indicator: "price_level_ratio", top: 0, also: [...KEY_IDS, "CHE", "NOR", "JPN", "DEU", "CHN", "IND", "MEX"], highlight: ["NZL"], kicker: "What things cost",
      say: (d) => { const n = d.row("NZL"); return n ? `Prices in New Zealand are ${d.fmt(n.value)} times US prices at market exchange rates (${d.ranking.year}). Above 1 means dearer than the US.` : "Price level."; } },
  ],
};

const crises: Story = {
  id: "how-often", group: "money", title: "How often things go wrong", colour: "#8a2f2f",
  blurb: "Banking crises, defaults and runaway inflation come round more often than people expect. Base rates from two hundred years of records.",
  sources: "Reinhart and Rogoff, Global Crises Data by Country (saved by hand in var\\manual\\crisis_history); the app's Episodes.",
  steps: [
    { kind: "count", indicator: "crisis_banking", label: "in a banking crisis", test: (v) => v >= 1, kicker: "Banking crises",
      say: (d) => { const n = d.counts.length; const peak = d.counts.indexOf(Math.max(...d.counts));
        const any = d.counts.filter((c) => c > 0).length;
        return `Some country was in a banking crisis in ${any} of the ${n} years on record; the worst year was ${d.years[peak]}, with ${d.counts[peak]} at once.`; } },
    { kind: "count", indicator: "crisis_default_external", label: "in default on foreign debt", test: (v) => v >= 1, kicker: "Defaults",
      say: (d) => { const peak = d.counts.indexOf(Math.max(...d.counts)); const a = d.at(1985);
        return `Defaults come in waves: ${d.counts[peak]} countries were in default on foreign debt in ${d.years[peak]}${a ? `, ${a.count} in 1985` : ""}.`; } },
    { kind: "lines", indicator: "rr_inflation", entities: [UK, US, NZ, AU], from: 1800, episodes: true, kicker: "Inflation since 1800",
      bands: [{ from: 1914, to: 1918, label: "First World War" }, { from: 1939, to: 1945, label: "Second World War" }],
      say: (d) => { const uk = d.rows[0].filter((r) => r.entity_id === "GBR"); const hi = [...uk].sort((a, b) => b.value - a.value)[0];
        return hi ? `British prices rose ${d.fmt(hi.value)} in ${hi.period}, the fastest on this record. Wars and the 1970s oil shocks stand out.` : "Inflation since 1800."; } },
  ],
};

const commodities: Story = {
  id: "milk-meat-logs", group: "money", title: "Milk, meat and logs", colour: "#4f7a28",
  blurb: "New Zealand lives off a few commodity prices. World food prices, what New Zealand's exports fetch, and the dollar.",
  sources: "FAO Food Price Index, ANZ Commodity Price Index, Reserve Bank of New Zealand, World Bank.",
  steps: [
    { kind: "monthly", from: 2000, series: [{ indicator: "ffpi_food", entity: "world", label: "All food", color: "#4f7a28" },
      { indicator: "ffpi_dairy", entity: "world", label: "Dairy", color: "#2c4f9e" }, { indicator: "ffpi_meat", entity: "world", label: "Meat", color: "#b3541e" }], kicker: "World food prices",
      say: (d) => { const da = d.series[1]; return da?.max && da.last ? `World dairy prices peaked at ${da.max[1].toFixed(0)} in ${month(da.max[0])} (2014-2016 = 100) and were ${da.last[1].toFixed(0)} in ${month(da.last[0])}.` : "FAO food price indices."; } },
    { kind: "monthly", from: 2000, index: true, series: [{ indicator: "anz_dairy", entity: "NZL", label: "Dairy", color: "#2c4f9e" },
      { indicator: "anz_meat", entity: "NZL", label: "Meat and wool", color: "#b3541e" }, { indicator: "anz_forestry", entity: "NZL", label: "Forestry", color: "#4f7a28" }], kicker: "What New Zealand sells",
      say: (d) => { const parts = d.series.filter((s) => s.last && s.first).map((s) => `${s.label.toLowerCase()} ${s.last![1] >= 100 ? "up" : "down"} ${Math.abs(s.last![1] - 100).toFixed(0)}%`);
        const y0 = d.series.find((s) => s.first)?.first?.[0].slice(0, 4);
        return parts.length ? `Since ${y0}, in world prices: ${parts.join(", ")} (ANZ Commodity Price Index).` : "ANZ commodity prices."; } },
    { kind: "lines", indicator: "rbnz_nzd_usd", entities: [NZ], from: 1985, kicker: "The kiwi dollar",
      say: (d) => { const l = d.last("NZL"); const lo = [...(d.rows[0] ?? [])].filter((r) => r.entity_id === "NZL").sort((a, b) => a.value - b.value)[0];
        return l ? `A New Zealand dollar bought ${d.fmt(l.value)} US dollars on average in ${l.year}${lo ? `; the low was ${d.fmt(lo.value)} in ${lo.period}` : ""}.` : "NZ dollar in US dollars."; } },
    { kind: "bars", indicator: "agriculture_share_gdp", top: 0, also: [...KEY_IDS, "IRL", "DNK", "NLD", "CHL", "ARG", "BRA", "IND"], highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "of GDP from farming, forestry and fishing", "The farm share of the whole economy is small; its share of exports is far larger.") },
  ],
};

// ---------------------------------------------------------------- war, power and politics
const coups: Story = {
  id: "coups", group: "power", title: "The age of coups", colour: "#5b3a6b",
  blurb: "Coups nearly died out after 2000, then came back across the Sahel. Every attempt since 1950.",
  sources: "Powell and Thyne, Global Instances of Coups.",
  steps: [
    { kind: "events", event: "coup", from: 1950, show: "years", labels: { successful: "Succeeded", failed: "Failed" }, kicker: "Every attempt",
      say: (d) => { const dec = (a: number, b: number) => d.years.filter((y) => y.year >= a && y.year <= b).reduce((s, y) => s + y.total, 0);
        return `${dec(1960, 1969)} coup attempts in the 1960s, ${dec(2000, 2009)} in the 2000s and ${dec(2020, 2029)} since 2020.`; } },
    { kind: "events", event: "coup", from: 1950, show: "countries", kicker: "Where",
      say: (d) => { const t = d.countries.slice(0, 3); return t.length ? `Most attempts since 1950: ${t.map((c) => `${c.name} (${c.n})`).join(", ")}.` : "Coup attempts by country."; } },
    { kind: "events", event: "coup", from: 2010, show: "countries", kicker: "Since 2010",
      say: (d) => { const n = d.years.reduce((s, y) => s + (y.by.successful ?? 0), 0); return `Since 2010, ${n} ${n === 1 ? "coup has" : "coups have"} succeeded. New Zealand, Australia, the UK and the US have had none in this record.`; } },
  ],
};

const turnout: Story = {
  id: "who-still-votes", group: "power", title: "Who still votes", colour: "#2d4b73",
  blurb: "Turnout has fallen in most rich democracies, and the young vote far less than the old, in New Zealand and the US alike.",
  sources: "International IDEA, New Zealand Electoral Commission, US Census Bureau voting supplement.",
  steps: [
    { kind: "lines", indicator: "turnout_parliamentary", entities: KEY, from: 1945, kicker: "Turnout",
      say: (d) => { const n = d.last("NZL"), n0 = d.at("NZL", 1984), a = d.last("AUS");
        return n ? `${d.fmt(n.value)} of registered New Zealanders voted in ${n.year}${n0 !== null ? `, against ${d.fmt(n0)} in 1984` : ""}${a ? `; in Australia, where voting is compulsory, ${d.fmt(a.value)}` : ""}.` : "Parliamentary turnout."; } },
    { kind: "lines", indicator: "nz_turnout_age_18_24", indicators: ["nz_turnout_age_18_24", "nz_turnout_age_70_plus"], labels: ["Aged 18 to 24", "Aged 70 and over"], sameAxis: true,
      entities: [NZ], from: 1990, kicker: "Young and old in New Zealand",
      say: (d) => { const y = d.last("NZL", 0), o = d.last("NZL", 1); return y && o ? `In ${y.year}, ${d.fmt(y.value)} of enrolled 18 to 24 year olds voted, against ${d.fmt(o.value, 1)} of those 70 and over.` : "Turnout by age."; } },
    { kind: "lines", indicator: "us_voted_age_18_24", indicators: ["us_voted_age_18_24", "us_voted_age_65_plus"], labels: ["Aged 18 to 24", "Aged 65 and over"], sameAxis: true,
      entities: [US], from: 1980, kicker: "Young and old in the US",
      say: (d) => { const y = d.last("USA", 0), o = d.last("USA", 1); return y && o ? `In the US in ${y.year}, ${d.fmt(y.value)} of 18 to 24 year olds voted, against ${d.fmt(o.value, 1)} of those 65 and over.` : "US turnout by age."; } },
    { kind: "bars", indicator: "turnout_parliamentary", top: 0, also: [...KEY_IDS, "BEL", "SWE", "DNK", "DEU", "CAN", "JPN", "FRA", "IRL"], highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "turnout at the last parliamentary election", "Belgium and Australia make voting compulsory.") },
  ],
};

// ---------------------------------------------------------------- energy, climate and nature
const forests: Story = {
  id: "forests", group: "energy", title: "Forests lost and found", colour: "#2f6b3a",
  blurb: "Brazil and Indonesia cleared forest while Europe, China and New Zealand planted. Land cover since 1990.",
  sources: "FAOSTAT land use, Global Forest Watch tree cover loss, ESA WorldCover (land cover maps).",
  steps: [
    { kind: "lines", indicator: "land_forest_pct", entities: [NZ, AU, e("BRA", "Brazil"), e("IDN", "Indonesia"), e("CHN", "China")], from: 1990, kicker: "Forest share of land",
      say: (d) => { const b0 = d.at("BRA", 1990), b = d.last("BRA"), c0 = d.at("CHN", 1990), c = d.last("CHN");
        return b && b0 !== null ? `Forest covered ${d.fmt(b0)} of Brazil in 1990 and ${d.fmt(b.value)} in ${b.year}${c && c0 !== null ? `; China went the other way, from ${d.fmt(c0)} to ${d.fmt(c.value)}` : ""}.` : "Forest share of land."; } },
    { kind: "bars", indicator: "gfw_tree_cover_loss_ha", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Trees lost",
      say: (d) => { const t = d.ranking.rows[0]; return t ? `${t.name} lost the most tree cover in ${d.ranking.year} (${d.fmt(t.value)}). Loss counts fires and plantation harvests as well as clearing.` : "Tree cover loss."; } },
    { kind: "bars", indicator: "land_forest_pct", by: "change", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Gaining forest",
      say: (d) => { const r = d.row("NZL"); return r && r.ten_years_before !== null ? `New Zealand's forest share went from ${d.fmt(r.ten_years_before)} to ${d.fmt(r.value)} in the ten years to ${d.ranking.year}.` : "Ten-year change in forest share."; } },
    { kind: "view", view: "landcompare", with: ["NZL", "AUS"], kicker: "Side by side",
      say: "New Zealand and Australia drawn to the same scale, coloured by land cover. Pick a class to see where it is." },
  ],
};

const warmer: Story = {
  id: "warmer", group: "energy", title: "A warmer world", colour: "#c25a1a",
  blurb: "Every country is warmer than it was. Which are warming fastest, how New Zealand compares, and which cities face a heatwave this week.",
  sources: "NASA GISTEMP, ERA5 (Copernicus, through Our World in Data), Open-Meteo forecasts for the map's heatwave layer.",
  steps: [
    { kind: "lines", indicator: "temp_anomaly_world", entities: [WORLD], from: 1880, kicker: "The world", about: "the world's temperature (NASA GISTEMP)",
      say: (d) => { const l = d.last("world"); return l ? `The world was ${d.fmt(l.value)} warmer in ${l.year} than its 1951-1980 average.` : "World temperature."; } },
    { kind: "lines", indicator: "temp_anomaly", entities: KEY, from: 1950, kicker: "The four",
      say: (d) => { const n = d.last("NZL"), u = d.last("GBR"); return n ? `Against their own 1991-2020 averages, New Zealand was ${d.fmt(n.value)} in ${n.year}${u ? `, the UK ${d.fmt(u.value)}` : ""}. Land far from the sea warms faster than islands.` : "Temperature against 1991-2020."; } },
    { kind: "map", indicator: "temp_anomaly", diverging: true, kicker: "Everywhere",
      say: (d) => `In ${d.ranking.year}, ${d.count((v) => v > 0)} of ${d.ranking.rows.length} countries were warmer than their 1991-2020 average; the most above it: ${top3(d)}.` },
    { kind: "layer", layer: "heat_now", top: 10, also: ["AUS", "USA"], kicker: "This week",
      say: (d) => d.rows.length ? `${d.total} big cities are forecast to reach 35°C on several days this week; the most are in ${d.rows[0].name} (${d.rows[0].v}).` : "No big city faces a heatwave this week." },
  ],
};

const sea: Story = {
  id: "mostly-sea", group: "energy", title: "A country that is mostly sea", colour: "#1f5f8b",
  blurb: "New Zealand's sea area is about fifteen times its land. Who owns the oceans, and the cables that run under them.",
  sources: "Marine Regions (exclusive economic zones), World Bank (land area), TeleGeography submarine cables (map layers).",
  steps: [
    { kind: "bars", indicator: "eez_area_km2", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "The biggest seas",
      say: (d) => { const t = d.ranking.rows[0], n = d.row("NZL"); return n ? `${t.name} has the largest sea area (${d.fmt(t.value)} km², counting its territories); New Zealand's ${d.fmt(n.value)} km² is ${ordinal(n.rank)}.` : "Sea area."; } },
    { kind: "bars", indicator: "eez_area_km2", over: "land_area", overName: "Sea area for every km² of land", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Sea against land",
      say: (d) => { const n = d.row("NZL"), a = d.row("AUS"); return n ? `New Zealand has ${d.fmt(n.value)} times as much sea as land${a ? `, Australia ${d.fmt(a.value)} times` : ""}. Small island states top the list.` : "Sea area over land area."; } },
    { kind: "layer", layer: "cables", top: 10, also: KEY_IDS, kicker: "Undersea cables",
      say: (d) => { const n = d.row("NZL"); return `${d.total} undersea cables carry the world's internet; ${d.rows[0]?.name ?? "–"} touches the most (${d.rows[0]?.v ?? "–"})${n ? `, New Zealand ${n.v}` : ""}.`; } },
  ],
};

// ---------------------------------------------------------------- places up close
const tasman: Story = {
  id: "tasman-gap", group: "places", title: "The Tasman gap", colour: "#b08a00",
  blurb: "In 1970 New Zealanders and Australians had similar incomes. Now Australians earn far more, and New Zealanders keep moving across.",
  sources: "World Bank (income, output per worker), ILO (earnings), UN (migration).",
  steps: [
    { kind: "lines", indicator: "gdp_per_capita_usd", entities: [NZ, AU], from: 1970, kicker: "Income per person",
      say: (d) => { const n = d.last("NZL"), a = d.last("AUS"), n0 = d.at("NZL", 1970), a0 = d.at("AUS", 1970);
        return n && a ? `GDP per person in US dollars: ${n0 != null && a0 != null ? `New Zealand ${d.fmt(n0)} and Australia ${d.fmt(a0)} in 1970; ` : ""}${d.fmt(n.value)} and ${d.fmt(a.value)} in ${n.year}, a gap of ${pct(a.value - n.value, n.value)}.` : "GDP per person."; } },
    { kind: "lines", indicator: "gdp_per_worker", entities: [NZ, AU, UK, US], from: 1991, kicker: "Output per worker",
      say: (d) => { const n = d.last("NZL"), a = d.last("AUS"); return n && a ? `Each New Zealand worker produced ${d.fmt(n.value)} in ${n.year} (constant dollars), Australia's ${d.fmt(a.value)}: Australians work with more machinery and more mining.` : "Output per worker."; } },
    { kind: "bars", indicator: "ilo_earnings_ppp", top: 0, also: [...KEY_IDS, "CAN", "IRL", "DEU", "JPN", "KOR"], highlight: ["NZL"], kicker: "Pay",
      say: (d) => { const n = d.row("NZL"), a = d.row("AUS"); return n && a ? `Average monthly earnings at equal buying power: Australia ${d.fmt(a.value)}, New Zealand ${d.fmt(n.value)} (${d.ranking.year}).` : "Average earnings."; } },
    { kind: "lines", indicator: "net_migration_rate", entities: [NZ, AU], from: 1970, kicker: "Moving",
      say: (d) => { const n = d.last("NZL"), a = d.last("AUS"); return n && a ? `Net migration per 1,000 people in ${n.year}: New Zealand ${d.fmt(n.value)}, Australia ${d.fmt(a.value)}. New Zealanders can live and work in Australia without a visa.` : "Net migration."; } },
  ],
};

const nzRegions: Story = {
  id: "nz-regions", group: "places", title: "New Zealand's regions", colour: "#3c3c3c",
  blurb: "Auckland against the rest: growth, ages, incomes and who owns their home, across the sixteen regions.",
  sources: "Stats NZ regional population estimates and census.",
  steps: [
    { kind: "states", country: "NZL", indicator: "nzreg_population", growth: 10, label: "Population growth over ten years", kicker: "Growth",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1); return t && b ? `In the ten years to ${d.year}, ${t.name} grew fastest (${d.fmt(t.value)}) and ${b.name} slowest (${d.fmt(b.value)}).` : "Population growth by region."; } },
    { kind: "states", country: "NZL", indicator: "nzreg_median_age", show: "bars", kicker: "Ages",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1); return t && b ? `The median age is ${d.fmt(t.value)} in ${t.name} and ${d.fmt(b.value)} in ${b.name} (${d.year}).` : "Median age by region."; } },
    { kind: "states", country: "NZL", indicator: "nzreg_born_overseas", kicker: "Born overseas",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1); return t && b ? `${d.fmt(t.value)} of ${t.name}'s people were born overseas, against ${d.fmt(b.value)} in ${b.name} (${d.year}).` : "Born overseas by region."; } },
    { kind: "states", country: "NZL", indicator: "nzreg_median_income", show: "bars", kicker: "Incomes",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1); return t && b ? `Median personal income: ${d.fmt(t.value)} in ${t.name}, ${d.fmt(b.value)} in ${b.name} (${d.year}).` : "Median income by region."; } },
    { kind: "states", country: "NZL", indicator: "nzreg_home_ownership", show: "bars", kicker: "Owning a home",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1); return t && b ? `Home ownership is highest in ${t.name} (${d.fmt(t.value)}) and lowest in ${b.name} (${d.fmt(b.value)}, ${d.year}).` : "Home ownership by region."; } },
  ],
};

// ---------------------------------------------------------------- technology and ideas
const ai: Story = {
  id: "ai-race", group: "ideas", title: "The AI race", colour: "#5a4fcf",
  blurb: "Who writes the AI research, who uses AI tools most per person, and how fast firms are taking it up.",
  sources: "OpenAlex via Our World in Data (AI papers), the Anthropic Economic Index (AI use per person), OECD and Eurostat (firms using AI).",
  steps: [
    { kind: "bars", indicator: "ai_publications_per_million", top: 10, also: [...KEY_IDS, "CHN"], highlight: ["NZL"], kicker: "Research",
      say: (d) => whereNz(d, "AI research papers per million people", `${d.ranking.rows[0]?.name ?? "–"} writes the most per person.`) },
    { kind: "lines", indicator: "ai_publications_per_million", entities: [...KEY, e("CHN", "China"), e("SGP", "Singapore")], from: 2000, kicker: "Over time",
      say: (d) => { const c = d.last("CHN"), c0 = d.at("CHN", 2010); return c && c0 !== null ? `China went from ${d.fmt(c0)} AI papers per million people in 2010 to ${d.fmt(c.value)} in ${c.year}.` : "AI papers per million people."; } },
    { kind: "bars", indicator: "ai_claude_use_per_capita_index", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Using AI",
      say: (d) => whereNz(d, "on an index of AI use per working-age person (1 = what its population share would predict)") },
    { kind: "bars", indicator: "ai_use_enterprises", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Firms",
      say: (d) => { const t = d.ranking.rows[0]; return t ? `${d.fmt(t.value)} of firms in ${t.name} use AI (${d.ranking.year}), the most of ${d.ranking.rows.length} countries with figures.` : "Firms using AI."; } },
  ],
};

const research: Story = {
  id: "ideas-inventions", group: "ideas", title: "Ideas and inventions", colour: "#0f7c8c",
  blurb: "Israel and South Korea spend the most on research. Patents, scientists and research money, and where New Zealand sits.",
  sources: "UNESCO and OECD (through the World Bank), WIPO (through Our World in Data).",
  steps: [
    { kind: "bars", indicator: "rd_spending_gdp", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Research money",
      say: (d) => whereNz(d, "of GDP spent on research and development", `${d.ranking.rows[0]?.name ?? "–"} spends ${d.fmt(d.ranking.rows[0]?.value)}.`) },
    { kind: "lines", indicator: "rd_spending_gdp", entities: [...KEY, e("KOR", "South Korea"), e("ISR", "Israel")], from: 1996, kicker: "Over time",
      say: (d) => { const k = d.last("KOR"), k0 = d.at("KOR", 1996), n = d.last("NZL"); return k && k0 !== null ? `South Korea raised research spending from ${d.fmt(k0)} of GDP in 1996 to ${d.fmt(k.value)} in ${k.year}${n ? `; New Zealand ${d.fmt(n.value)}` : ""}.` : "R&D spending."; } },
    { kind: "bars", indicator: "patents_per_million", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Patents",
      say: (d) => whereNz(d, "patent applications per million people") },
    { kind: "bars", indicator: "researchers_per_million", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "researchers per million people") },
  ],
};

export const ROUND2_STORIES: Story[] = [religion, trust, schooling, wages, crises, commodities, coups, turnout, forests, warmer, sea, tasman, nzRegions, ai, research];
