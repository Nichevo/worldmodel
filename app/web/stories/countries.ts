// "How countries changed": one story per country, each opening on the country then and now (every
// figure in an early year and its latest, and where it sat among countries), then the lines that
// tell its story against neighbours and New Zealand. Every sentence is worked out from the figures
// when the page opens; the shaded periods are typed in here.

import { ordinal, times, type Named, type SeriesData, type Story, type ThenNowData } from "@/lib/story";

const e = (id: string, name: string): Named => ({ id, name });
const NZ = e("NZL", "New Zealand"), AU = e("AUS", "Australia"), UK = e("GBR", "United Kingdom"), US = e("USA", "United States");
const WORLD = e("world", "World");

// ---------------------------------------------------------------- sentence helpers
type Pt = { year: number; value: number };
// The first estimate in or after a year.
function near(d: SeriesData, id: string, year: number, layer = 0): Pt | null {
  const r = (d.rows[layer] ?? []).filter((x) => x.entity_id === id && x.status !== "P" && +x.period >= year).sort((a, b) => +a.period - +b.period)[0];
  return r ? { year: +r.period, value: r.value } : null;
}
// The highest (or lowest) estimate on record, in or after a year.
function peak(d: SeriesData, id: string, low = false, from = 0, layer = 0): Pt | null {
  const rs = (d.rows[layer] ?? []).filter((x) => x.entity_id === id && x.status !== "P" && +x.period >= from);
  if (!rs.length) return null;
  const r = rs.reduce((a, b) => ((low ? b.value < a.value : b.value > a.value) ? b : a));
  return { year: +r.period, value: r.value };
}
// The first year a test passes (projections included, so "expected by" works).
function firstWhen(d: SeriesData, id: string, test: (v: number) => boolean, layer = 0): { year: number; value: number; proj: boolean } | null {
  const r = (d.rows[layer] ?? []).filter((x) => x.entity_id === id).sort((a, b) => +a.period - +b.period).find((x) => test(x.value));
  return r ? { year: +r.period, value: r.value, proj: r.status === "P" } : null;
}
// The first year one place's figure passes another's (estimates only).
function overtakes(d: SeriesData, a: string, b: string, layer = 0): number | null {
  const of = (id: string) => new Map((d.rows[layer] ?? []).filter((x) => x.entity_id === id && x.status !== "P").map((x) => [+x.period, x.value]));
  const A = of(a), B = of(b);
  const years = [...A.keys()].filter((y) => B.has(y)).sort((x, y) => x - y);
  if (!years.length || A.get(years[0])! > B.get(years[0])!) return null; // ahead from the start
  return years.find((y) => A.get(y)! > B.get(y)!) ?? null;
}
const missing = (what: string) => `${what} are not loaded yet.`;

// Then and now: "from X in 1970 to Y in 2023".
function tn(d: ThenNowData, id: string): string {
  const r = d.get(id);
  if (!r?.then || !r.now) return "";
  return `from ${d.fmt(r.ind, r.then.value)} in ${r.then.year} to ${d.fmt(r.ind, r.now.value)} in ${r.now.year}`;
}
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);
const short = (name: string) => lower(name.replace(/ \(.*\)$/, ""));
// Figures where moving up the table is plainly good news, so a climb is worth naming.
const GOOD_UP = new Set(["gdp_per_capita_constant_usd", "gdp_ppp_per_capita", "gni_per_capita_atlas", "life_expectancy", "tertiary_enrolment", "primary_completion",
  "internet_users_share", "electricity_access", "measles_immunisation", "vdem_liberal", "women_in_parliament", "high_tech_share_exports", "exports_share_gdp", "rd_spending_gdp"]);
function climb(d: ThenNowData): string {
  const pos = (q: { rank: number; of: number }) => (q.of > 1 ? (q.of - q.rank) / (q.of - 1) : 0.5);
  const up = d.rows.filter((r) => r.then && r.now && GOOD_UP.has(r.ind.indicator_id)).map((r) => ({ r, by: pos(r.now!) - pos(r.then!) }))
    .sort((x, y) => y.by - x.by)[0];
  if (!up || up.by <= 0.05) return "";
  const { r } = up;
  return ` Its biggest climb among countries: ${short(r.ind.name)}, from ${ordinal(r.then!.rank)} of ${r.then!.of} to ${ordinal(r.now!.rank)} of ${r.now!.of}.`;
}
// The opening sentence: the lead figure then and now, in words the story gives, then the biggest climb.
function opening(d: ThenNowData, who: string, lead: string, what: string, after = ""): string {
  const a = tn(d, lead);
  if (!a) return `${who} in ${d.from} and now: ${d.rows.length} figures.${climb(d)}`;
  return `${what.charAt(0).toUpperCase()}${what.slice(1)} went ${a}.${after ? ` ${after}` : ""}${climb(d)}`;
}

// ---------------------------------------------------------------- South Korea
const KOR = e("KOR", "South Korea");
const korea: Story = {
  id: "country-south-korea", group: "countries", title: "South Korea: from aid to advanced", colour: "#0f4c81",
  blurb: "In 1960 South Korea was about as poor as Ghana. Now it out-earns much of Europe, has free elections, and has the world's lowest birth rate.",
  sources: "World Bank WDI, UN World Population Prospects, V-Dem (through Our World in Data).",
  steps: [
    { kind: "thennow", entity: "KOR", from: 1970, kicker: "1970 and now",
      indicators: ["gdp_per_capita_constant_usd", "life_expectancy", "infant_mortality", "tfr", "urban_share", "agriculture_share_gdp", "manufacturing_share_gdp",
        "exports_share_gdp", "high_tech_share_exports", "tertiary_enrolment", "median_age", "vdem_liberal"],
      say: (d) => opening(d, "South Korea", "gdp_per_capita_constant_usd", "GDP per person in South Korea (US dollars, prices held steady)") },
    { kind: "lines", indicator: "gdp_per_capita_constant_usd", entities: [KOR, e("GHA", "Ghana"), e("PHL", "Philippines"), NZ, WORLD], from: 1960, kicker: "Income",
      bands: [{ from: 1997, to: 1998, label: "Asian financial crisis" }],
      say: (d) => {
        const k0 = near(d, "KOR", 1960), g0 = near(d, "GHA", 1960), k = d.last("KOR"), g = d.last("GHA"), n = d.last("NZL");
        if (!k0 || !k) return missing("Income figures");
        return `GDP per person in South Korea grew ${times(k.value, k0.value)} over between ${k0.year} and ${k.year}${g0 && g ? `; Ghana's grew ${times(g.value, g0.value)}` : ""}.${n ? ` South Korea is now at ${d.fmt(k.value)}, against New Zealand's ${d.fmt(n.value)}.` : ""}`;
      } },
    { kind: "lines", indicator: "vdem_liberal", entities: [KOR, e("JPN", "Japan"), NZ], from: 1948, kicker: "Democracy",
      bands: [{ from: 1950, to: 1953, label: "Korean War" }, { from: 1961, to: 1979, label: "Park Chung-hee" }, { from: 1980, to: 1987, label: "Chun Doo-hwan" }],
      say: (d) => {
        const a = near(d, "KOR", 1985), k = d.last("KOR");
        return a && k ? `V-Dem's liberal democracy score for South Korea rose from ${d.fmt(a.value)} in ${a.year} to ${d.fmt(k.value)} in ${k.year} (0 to 1) after the 1987 protests won direct presidential elections.` : missing("Democracy scores");
      } },
    { kind: "lines", indicator: "tfr", entities: [KOR, e("JPN", "Japan"), NZ, WORLD], from: 1960, to: 2050, kicker: "Fewer children",
      say: (d) => {
        const a = near(d, "KOR", 1960), k = d.last("KOR"), w = d.last("world");
        return a && k ? `South Korean women had ${d.fmt(a.value)} children each in ${a.year} and ${d.fmt(k.value)} in ${k.year}${w ? `, against ${d.fmt(w.value)} for the world` : ""}: the population is now shrinking.` : missing("Fertility figures");
      } },
    { kind: "bars", indicator: "tfr", top: 8, order: "asc", also: ["NZL", "JPN"], highlight: ["KOR", "NZL"], kicker: "Where it sits",
      say: (d) => { const k = d.row("KOR"), n = d.row("NZL"), last = d.ranking.rows.length;
        return k ? `South Korea's ${d.fmt(k.value)} children per woman is ${k.rank === last ? "the lowest in the world" : `${ordinal(last - k.rank + 1)} lowest of ${last}`} (${d.ranking.year})${n ? `; New Zealand ${d.fmt(n.value)}` : ""}.` : missing("Fertility figures"); } },
  ],
};

// ---------------------------------------------------------------- China
const CHN = e("CHN", "China"), IND = e("IND", "India");
const china: Story = {
  id: "country-china", group: "countries", title: "China: the biggest change of all", colour: "#b22222",
  blurb: "Since 1980 China has gone from one of the poorest countries to the world's factory, moved hundreds of millions to cities, and now has fewer babies than Japan.",
  sources: "World Bank WDI (including the poverty line of $3 a day), UN World Population Prospects, Our World in Data (CO2).",
  steps: [
    { kind: "thennow", entity: "CHN", from: 1980, kicker: "1980 and now",
      indicators: ["gdp_per_capita_constant_usd", "poverty_extreme", "life_expectancy", "infant_mortality", "urban_share", "tfr", "manufacturing_share_gdp",
        "exports_share_gdp", "tertiary_enrolment", "co2_per_capita", "internet_users_share", "pop_share_65_plus"],
      say: (d) => opening(d, "China", "gdp_per_capita_constant_usd", "GDP per person in China (US dollars, prices held steady)") },
    { kind: "lines", indicator: "gdp_usd", entities: [CHN, US, e("JPN", "Japan"), IND], from: 1980, kicker: "The size of the economy",
      bands: [{ from: 2001, to: 2001, label: "Joins the WTO" }],
      say: (d) => {
        const c0 = near(d, "CHN", 1980), u0 = near(d, "USA", 1980), c = d.last("CHN"), u = d.last("USA"), j = overtakes(d, "CHN", "JPN");
        return c && u && c0 && u0 ? `China's economy was ${Math.round((100 * c0.value) / u0.value)}% the size of America's in ${c0.year} at market exchange rates, and ${Math.round((100 * c.value) / u.value)}% in ${c.year}${j ? `; it passed Japan in ${j}` : ""}.` : missing("GDP figures");
      } },
    { kind: "lines", indicator: "poverty_extreme", entities: [CHN, IND, WORLD], from: 1981, kicker: "Out of poverty",
      say: (d) => {
        const c0 = near(d, "CHN", 1981), c = d.last("CHN"), w = d.last("world");
        return c0 && c ? `Share of Chinese living below the World Bank's extreme poverty line: ${d.fmt(c0.value)} in ${c0.year}, ${d.fmt(c.value)} in ${c.year}${w ? ` (world: ${d.fmt(w.value)})` : ""}. No country has lifted more people out of poverty.` : missing("Poverty figures");
      } },
    { kind: "lines", indicator: "urban_share", entities: [CHN, IND, WORLD, NZ], from: 1960, kicker: "To the cities",
      say: (d) => {
        const c0 = near(d, "CHN", 1980), c = d.last("CHN"), half = firstWhen(d, "CHN", (v) => v >= 50);
        return c0 && c ? `${d.fmt(c0.value)} of Chinese lived in towns and cities in ${c0.year} and ${d.fmt(c.value)} in ${c.year}${half ? `; more than half ${half.proj ? "are expected to" : "have"} since ${half.year}` : ""}.` : missing("Urban figures");
      } },
    { kind: "lines", indicator: "tfr", entities: [CHN, IND, e("JPN", "Japan"), NZ], from: 1960, to: 2050, kicker: "Fewer children",
      bands: [{ from: 1980, to: 2015, label: "One-child policy" }],
      say: (d) => {
        const c0 = near(d, "CHN", 1965), c = d.last("CHN"), j = d.last("JPN");
        return c0 && c ? `Chinese women had ${d.fmt(c0.value)} children each in ${c0.year} and ${d.fmt(c.value)} in ${c.year}${j ? `, ${c.value < j.value ? "now fewer than" : "against"} Japan's ${d.fmt(j.value)}` : ""}. The fall came mostly before the one-child policy, and went on after it ended.` : missing("Fertility figures");
      } },
    { kind: "lines", indicator: "co2_per_capita", entities: [CHN, US, UK, NZ, WORLD], from: 1980, kicker: "Smoke",
      say: (d) => {
        const c = d.last("CHN"), g = d.last("GBR"), n = d.last("NZL"), pass = overtakes(d, "CHN", "GBR");
        return c ? `A person in China now puts out ${d.fmt(c.value)} of CO2 a year (${c.year})${g ? `, against ${d.fmt(g.value)} for a Briton` : ""}${n ? ` and ${d.fmt(n.value)} for a New Zealander` : ""}${pass ? `; China passed Britain in ${pass}` : ""}.` : missing("CO2 figures");
      } },
  ],
};

// ---------------------------------------------------------------- Ireland
const IRL = e("IRL", "Ireland");
const ireland: Story = {
  id: "country-ireland", group: "countries", title: "Ireland: from leaving to arriving", colour: "#1f7a4d",
  blurb: "For a century people left Ireland. Then came the Celtic Tiger, a crash and a bailout, and now one of the highest incomes in the world.",
  sources: "World Bank WDI, IMF (government debt), UN World Population Prospects (migration).",
  steps: [
    { kind: "thennow", entity: "IRL", from: 1980, kicker: "1980 and now",
      indicators: ["gdp_per_capita_constant_usd", "gni_per_capita_atlas", "unemployment", "net_migration_rate", "govt_debt_gdp", "fdi_inflows_gdp", "exports_share_gdp",
        "agriculture_share_gdp", "tertiary_enrolment", "life_expectancy", "tfr", "pop_total"],
      say: (d) => opening(d, "Ireland", "net_migration_rate", "net migration into Ireland (per 1,000 people a year)", "Irish GDP is swollen by big foreign companies booking profits there, so national income (GNI) is the fairer guide to income.") },
    { kind: "lines", indicator: "net_migration_rate", entities: [IRL, NZ, UK], from: 1950, kicker: "Leaving, then arriving",
      bands: [{ from: 1995, to: 2007, label: "Celtic Tiger" }, { from: 2008, to: 2013, label: "Crash and bailout" }],
      say: (d) => {
        const lo = peak(d, "IRL", true), hi = peak(d, "IRL"), l = d.last("IRL");
        return lo && hi ? `Ireland lost ${d.fmt(Math.abs(lo.value))} per 1,000 people a year to migration in ${lo.year}, and gained ${d.fmt(hi.value)} per 1,000 in ${hi.year}${l ? `; ${l.value >= 0 ? "a gain" : "a loss"} of ${d.fmt(Math.abs(l.value))} in ${l.year}` : ""}.` : missing("Migration figures");
      } },
    { kind: "lines", indicator: "gni_per_capita_atlas", entities: [IRL, UK, NZ, e("DNK", "Denmark")], from: 1970, kicker: "Income",
      bands: [{ from: 1995, to: 2007, label: "Celtic Tiger" }, { from: 2008, to: 2013, label: "Crash and bailout" }],
      say: (d) => {
        const i0 = near(d, "IRL", 1980), u0 = near(d, "GBR", 1980), i = d.last("IRL"), u = d.last("GBR");
        return i0 && u0 && i && u ? `Irish national income per person was ${Math.round((100 * i0.value) / u0.value)}% of Britain's in ${i0.year} and ${Math.round((100 * i.value) / u.value)}% in ${i.year} (${d.fmt(i.value)}, World Bank Atlas method).` : missing("Income figures");
      } },
    { kind: "lines", indicator: "unemployment", entities: [IRL, UK, NZ], from: 1991, kicker: "Jobs",
      bands: [{ from: 2008, to: 2013, label: "Crash and bailout" }],
      say: (d) => {
        const hi = peak(d, "IRL", false, 2005), lo = peak(d, "IRL", true, 1995), l = d.last("IRL");
        return hi && l ? `Irish unemployment ${lo && lo.year < hi.year ? `was ${d.fmt(lo.value)} in ${lo.year}, ` : ""}hit ${d.fmt(hi.value)} in ${hi.year} and was ${d.fmt(l.value)} in ${l.year}.` : missing("Unemployment figures");
      } },
    { kind: "lines", indicator: "govt_debt_gdp", entities: [IRL, UK, NZ], from: 1990, kicker: "The bill",
      bands: [{ from: 2010, to: 2013, label: "EU-IMF bailout" }],
      say: (d) => {
        const lo = peak(d, "IRL", true, 2000), hi = peak(d, "IRL", false, 2008), l = d.last("IRL");
        return lo && hi && l ? `Government debt went from ${d.fmt(lo.value)} of GDP in ${lo.year} to ${d.fmt(hi.value)} in ${hi.year} after the state stood behind the banks, and back to ${d.fmt(l.value)} by ${l.year}.` : missing("Government debt figures");
      } },
  ],
};

// ---------------------------------------------------------------- Rwanda
const RWA = e("RWA", "Rwanda"), BDI = e("BDI", "Burundi"), UGA = e("UGA", "Uganda");
const rwanda: Story = {
  id: "country-rwanda", group: "countries", title: "Rwanda after 1994", colour: "#c78a00",
  blurb: "Thirty years after the genocide, Rwandans live twenty years longer, far fewer children die, and its parliament has more women than any other.",
  sources: "World Bank WDI, UN World Population Prospects, Inter-Parliamentary Union (through the World Bank).",
  steps: [
    { kind: "thennow", entity: "RWA", from: 1995, kicker: "1995 and now",
      indicators: ["life_expectancy", "under5_mortality", "gdp_per_capita_constant_usd", "poverty_extreme", "electricity_access", "tfr", "women_in_parliament",
        "measles_immunisation", "primary_completion", "urban_share", "internet_users_share", "hiv_prevalence"],
      say: (d) => opening(d, "Rwanda", "under5_mortality", "the number of Rwandan children dying before five (per 1,000 born)") },
    { kind: "lines", indicator: "life_expectancy", entities: [RWA, BDI, UGA, WORLD], from: 1960, kicker: "Living longer",
      bands: [{ from: 1994, to: 1994, label: "Genocide against the Tutsi" }],
      say: (d) => {
        const lo = peak(d, "RWA", true), r = d.last("RWA"), w = d.last("world");
        return lo && r ? `Life expectancy in Rwanda fell to ${d.fmt(lo.value)} in ${lo.year}, so many died that year. By ${r.year} it was ${d.fmt(r.value)}${w ? `, against ${d.fmt(w.value)} for the world` : ""}.` : missing("Life expectancy figures");
      } },
    { kind: "lines", indicator: "under5_mortality", entities: [RWA, BDI, UGA, WORLD], from: 1990, kicker: "Children",
      say: (d) => {
        const a = near(d, "RWA", 2000), r = d.last("RWA"), b = d.last("BDI");
        return a && r ? `Of every 1,000 children born in Rwanda, ${d.fmt(a.value)} died before turning five in ${a.year} and ${d.fmt(r.value)} in ${r.year}${b ? ` (Burundi next door: ${d.fmt(b.value)})` : ""}.` : missing("Child death figures");
      } },
    { kind: "lines", indicator: "gdp_per_capita_constant_usd", entities: [RWA, BDI, UGA], from: 1990, kicker: "Income",
      say: (d) => {
        const a = near(d, "RWA", 1995), r = d.last("RWA"), b0 = near(d, "BDI", 1995), b = d.last("BDI");
        return a && r ? `GDP per person in Rwanda grew ${times(r.value, a.value)} over from ${a.year} to ${r.year}${b0 && b ? `; Burundi's ${b.value >= b0.value ? `grew ${times(b.value, b0.value)}` : "fell"}` : ""}. It is still poor: ${d.fmt(r.value)} a year.` : missing("Income figures");
      } },
    { kind: "bars", indicator: "women_in_parliament", top: 10, also: ["NZL", "AUS", "GBR", "USA"], highlight: ["RWA", "NZL"], kicker: "Where it sits",
      say: (d) => { const r = d.row("RWA"), n = d.row("NZL");
        return r ? `${d.fmt(r.value)} of seats in Rwanda's lower house are held by women (${d.ranking.year}), ${ordinal(r.rank)} of ${d.ranking.rows.length}${n ? `; New Zealand ${d.fmt(n.value)}, ${ordinal(n.rank)}` : ""}.` : missing("Figures on women in parliament"); } },
  ],
};

// ---------------------------------------------------------------- Poland
const POL = e("POL", "Poland"), UKR = e("UKR", "Ukraine");
const poland: Story = {
  id: "country-poland", group: "countries", title: "Poland since communism", colour: "#a4243b",
  blurb: "Poland and Ukraine started the 1990s about equally well off. Poland joined the EU and never had a recession for 30 years; the gap is now huge.",
  sources: "World Bank WDI (GDP at equal buying power, prices, jobs), UN World Population Prospects, Our World in Data (electricity).",
  steps: [
    { kind: "thennow", entity: "POL", from: 1990, kicker: "1990 and now",
      indicators: ["gdp_ppp_per_capita", "life_expectancy", "infant_mortality", "inflation", "unemployment", "exports_share_gdp", "tertiary_enrolment",
        "net_migration_rate", "coal_share_elec", "co2_per_capita", "tfr", "vdem_liberal"],
      say: (d) => opening(d, "Poland", "gdp_ppp_per_capita", "GDP per person in Poland (at equal buying power)") },
    { kind: "lines", indicator: "gdp_ppp_per_capita", entities: [POL, UKR, UK, NZ], from: 1990, kicker: "Two neighbours",
      bands: [{ from: 2004, to: 2004, label: "Joins the EU" }],
      say: (d) => {
        const p0 = near(d, "POL", 1990), u0 = near(d, "UKR", 1990), p = d.last("POL"), u = d.last("UKR"), g = d.last("GBR");
        return p0 && u0 && p && u ? `At equal buying power a Pole produced ${times(p0.value, u0.value)} as much as a Ukrainian in ${p0.year}, and ${times(p.value, u.value)} as much in ${p.year}${g ? `; Poland is now at ${Math.round((100 * p.value) / g.value)}% of Britain's level` : ""}.` : missing("Income figures");
      } },
    { kind: "lines", indicator: "inflation", indicators: ["inflation", "unemployment"], labels: ["Inflation", "Unemployment"], sameAxis: true, entities: [POL], from: 1991, kicker: "Shock therapy",
      say: (d) => {
        const i = near(d, "POL", 1991, 0), hi = peak(d, "POL", false, 1995, 1), u = d.last("POL", 1);
        return i && u ? `Prices rose ${d.fmt(i.value, 0)} in ${i.year} as controls came off. Unemployment ${hi ? `peaked at ${d.fmt(hi.value, 1)} in ${hi.year} and ` : ""}was ${d.fmt(u.value, 1)} in ${u.year},.` : missing("Price and job figures");
      } },
    { kind: "lines", indicator: "net_migration_rate", entities: [POL, UKR, NZ], from: 1990, kicker: "Leaving and coming home",
      bands: [{ from: 2004, to: 2004, label: "Joins the EU" }, { from: 2022, to: 2022, label: "Russia invades Ukraine" }],
      say: (d) => {
        const lo = peak(d, "POL", true, 2000), hi = peak(d, "POL", false, 2015);
        return lo ? `After joining the EU Poland lost ${d.fmt(Math.abs(lo.value))} per 1,000 people a year to migration (${lo.year})${hi && hi.value > 0 ? `; by ${hi.year} it was gaining ${d.fmt(hi.value)} per 1,000, ${hi.year >= 2022 ? ", much of it from Ukraine" : ""}` : ""}.` : missing("Migration figures");
      } },
    { kind: "lines", indicator: "coal_share_elec", entities: [POL, UK, WORLD, NZ], from: 1990, kicker: "Still on coal",
      say: (d) => {
        const a = near(d, "POL", 1990), p = d.last("POL"), g = d.last("GBR");
        return a && p ? `Coal made ${d.fmt(a.value)} of Poland's electricity in ${a.year} and ${d.fmt(p.value)} in ${p.year}${g ? `; Britain went to ${d.fmt(g.value)}` : ""}.` : missing("Electricity figures");
      } },
  ],
};

// ---------------------------------------------------------------- New Zealand
const nz: Story = {
  id: "country-new-zealand", group: "countries", title: "New Zealand since 1984", colour: "#111111",
  blurb: "The reforms of 1984 to 1993 turned one of the most regulated rich economies into one of the most open. What changed, and how it compares with Australia.",
  sources: "World Bank WDI, IMF (government debt), UN World Population Prospects.",
  steps: [
    { kind: "thennow", entity: "NZL", from: 1984, kicker: "1984 and now",
      indicators: ["gdp_per_capita_constant_usd", "inflation", "unemployment", "govt_debt_gdp", "exports_share_gdp", "agriculture_share_gdp", "manufacturing_share_gdp",
        "net_migration_rate", "median_age", "pop_share_65_plus", "tfr", "life_expectancy", "gini"],
      say: (d) => opening(d, "New Zealand", "gdp_per_capita_constant_usd", "GDP per person in New Zealand (US dollars, prices held steady)") },
    { kind: "lines", indicator: "inflation", entities: [NZ, AU, UK, US], from: 1970, kicker: "Prices",
      bands: [{ from: 1984, to: 1993, label: "Reforms" }],
      say: (d) => {
        const hi = peak(d, "NZL", false, 1970), a = near(d, "NZL", 1992), l = d.last("NZL");
        return hi && a ? `Prices in New Zealand rose ${d.fmt(hi.value)} in ${hi.year}; after the Reserve Bank was given an inflation target in 1989 they rose ${d.fmt(a.value)} in ${a.year}${l ? ` (${d.fmt(l.value)} in ${l.year})` : ""}.` : missing("Inflation figures");
      } },
    { kind: "lines", indicator: "gdp_per_capita_constant_usd", entities: [NZ, AU], from: 1970, kicker: "Against Australia",
      bands: [{ from: 1984, to: 1993, label: "Reforms" }],
      say: (d) => {
        const n0 = near(d, "NZL", 1970), a0 = near(d, "AUS", 1970), n = d.last("NZL"), a = d.last("AUS");
        return n0 && a0 && n && a ? `A New Zealander produced ${Math.round((100 * n0.value) / a0.value)}% as much as an Australian in ${n0.year}, and ${Math.round((100 * n.value) / a.value)}% in ${n.year}.` : missing("Income figures");
      } },
    { kind: "lines", indicator: "govt_debt_gdp", entities: [NZ, AU, UK, US], from: 1990, kicker: "Debt",
      say: (d) => {
        const lo = peak(d, "NZL", true), l = d.last("NZL"), f = near(d, "NZL", 1990);
        return lo && l ? `Government debt went ${f ? `from ${d.fmt(f.value)} of GDP in ${f.year} ` : ""}down to ${d.fmt(lo.value)} in ${lo.year}, and was ${d.fmt(l.value)} in ${l.year}: still among the lowest of rich countries.` : missing("Government debt figures");
      } },
    { kind: "lines", indicator: "net_migration_rate", entities: [NZ, AU], from: 1960, kicker: "Coming and going",
      say: (d) => {
        const lo = peak(d, "NZL", true, 1970), hi = peak(d, "NZL", false, 1990), l = d.last("NZL");
        return lo && hi ? `New Zealand lost ${d.fmt(Math.abs(lo.value))} per 1,000 people to migration in ${lo.year} and gained ${d.fmt(hi.value)} per 1,000 in ${hi.year}${l ? `; ${l.year}: ${l.value >= 0 ? "+" : "−"}${d.fmt(Math.abs(l.value))}` : ""}.` : missing("Migration figures");
      } },
    { kind: "lines", indicator: "median_age", entities: [NZ, AU, UK, WORLD], from: 1950, to: 2060, kicker: "Older",
      say: (d) => {
        const a = near(d, "NZL", 1984), l = d.last("NZL"), x = d.end("NZL");
        return a && l ? `The middle New Zealander was ${d.fmt(a.value)} old in ${a.year} and ${d.fmt(l.value)} in ${l.year}${x && x.year > l.year ? `; ${d.fmt(x.value)} expected by ${x.year}` : ""}.` : missing("Age figures");
      } },
  ],
};

// ---------------------------------------------------------------- Japan
const JPN = e("JPN", "Japan");
const japan: Story = {
  id: "country-japan", group: "countries", title: "Japan: the long plateau", colour: "#bc002d",
  blurb: "In 1990 Japan looked set to overtake America. Then a bubble burst, prices stood still for twenty years, and the population began to shrink.",
  sources: "World Bank WDI, IMF (government debt), UN World Population Prospects.",
  steps: [
    { kind: "thennow", entity: "JPN", from: 1990, kicker: "1990 and now",
      indicators: ["gdp_per_capita_constant_usd", "gdp_growth", "inflation", "govt_debt_gdp", "unemployment", "median_age", "pop_share_65_plus", "tfr", "life_expectancy",
        "pop_total", "rd_spending_gdp", "high_tech_share_exports"],
      say: (d) => opening(d, "Japan", "govt_debt_gdp", "Japan's government debt (share of GDP)") },
    { kind: "lines", indicator: "gdp_per_capita_constant_usd", entities: [JPN, US, KOR, NZ], from: 1970, kicker: "Income",
      bands: [{ from: 1991, to: 2001, label: "Lost decade" }],
      say: (d) => {
        const j0 = near(d, "JPN", 1991), u0 = near(d, "USA", 1991), j = d.last("JPN"), u = d.last("USA"), k = d.last("KOR");
        return j0 && u0 && j && u ? `A Japanese person produced ${Math.round((100 * j0.value) / u0.value)}% as much as an American in ${j0.year} and ${Math.round((100 * j.value) / u.value)}% in ${j.year}${k ? `; South Korea is now at ${Math.round((100 * k.value) / j.value)}% of Japan` : ""}.` : missing("Income figures");
      } },
    { kind: "lines", indicator: "govt_debt_gdp", entities: [JPN, US, UK, NZ], from: 1980, kicker: "Debt",
      say: (d) => {
        const a = near(d, "JPN", 1990), l = d.last("JPN");
        return a && l ? `Japan's government debt was ${d.fmt(a.value)} of GDP in ${a.year} and ${d.fmt(l.value)} in ${l.year}, the highest of any rich country; most of it is owed to Japanese savers and the central bank.` : missing("Government debt figures");
      } },
    { kind: "lines", indicator: "pop_total", entities: [JPN], from: 1950, to: 2070, kicker: "Fewer people",
      say: (d) => {
        const top = peak(d, "JPN"), l = d.last("JPN"), x = d.end("JPN");
        return top && l ? `Japan's population peaked at ${d.fmt(top.value)} in ${top.year} and was ${d.fmt(l.value)} in ${l.year}${x && x.year > l.year ? `; the UN expects ${d.fmt(x.value)} by ${x.year}` : ""}.` : missing("Population figures");
      } },
    { kind: "bars", indicator: "pop_share_65_plus", top: 10, also: ["NZL", "AUS", "GBR", "USA"], highlight: ["JPN", "NZL"], kicker: "Where it sits",
      say: (d) => { const j = d.row("JPN"), n = d.row("NZL");
        return j ? `${d.fmt(j.value)} of Japanese are 65 or older (${d.ranking.year}), ${ordinal(j.rank)} of ${d.ranking.rows.length}${n ? `; New Zealand ${d.fmt(n.value)}` : ""}.` : missing("Age figures"); } },
  ],
};

// ---------------------------------------------------------------- Argentina
const ARG = e("ARG", "Argentina"), CHL = e("CHL", "Chile");
const argentina: Story = {
  id: "country-argentina", group: "countries", title: "Argentina: rich, then not", colour: "#4a7fb5",
  blurb: "A century ago Argentina was among the world's richest countries. Coups, defaults and runaway prices have kept it falling behind Australia and New Zealand.",
  sources: "World Bank WDI, IMF, V-Dem (through Our World in Data), the app's Big episodes.",
  steps: [
    { kind: "thennow", entity: "ARG", from: 1960, kicker: "1960 and now",
      indicators: ["gdp_per_capita_constant_usd", "life_expectancy", "infant_mortality", "inflation", "govt_debt_gdp", "exports_share_gdp", "urban_share",
        "tertiary_enrolment", "unemployment", "tfr", "vdem_liberal"],
      say: (d) => opening(d, "Argentina", "gdp_per_capita_constant_usd", "GDP per person in Argentina (US dollars, prices held steady)") },
    { kind: "lines", indicator: "gdp_per_capita_constant_usd", entities: [ARG, AU, NZ, CHL], from: 1960, kicker: "Falling behind",
      bands: [{ from: 1989, to: 1990, label: "Hyperinflation" }, { from: 2001, to: 2002, label: "Default and crash" }],
      say: (d) => {
        const a0 = near(d, "ARG", 1960), u0 = near(d, "AUS", 1960), a = d.last("ARG"), u = d.last("AUS"), c = d.last("CHL");
        return a0 && u0 && a && u ? `An Argentine produced ${Math.round((100 * a0.value) / u0.value)}% as much as an Australian in ${a0.year}, and ${Math.round((100 * a.value) / u.value)}% in ${a.year}${c ? `; Chile, once far poorer, is now at ${times(c.value, a.value)} Argentina's level` : ""}.` : missing("Income figures");
      } },
    { kind: "lines", indicator: "inflation", entities: [ARG, CHL], from: 1960, episodes: true, kicker: "Runaway prices",
      say: (d) => {
        const hi = peak(d, "ARG"), l = d.last("ARG"), years = (d.rows[0] ?? []).filter((r) => r.entity_id === "ARG" && r.status !== "P");
        const over = years.filter((r) => r.value >= 25).length;
        return hi && l ? `Prices in Argentina rose ${d.fmt(hi.value)} in ${hi.year}. In ${over} of the ${years.length} years on record they rose 25% or more; ${l.year}: ${d.fmt(l.value)}.` : missing("Inflation figures");
      } },
    { kind: "lines", indicator: "vdem_liberal", entities: [ARG, CHL, NZ], from: 1950, kicker: "Coups and elections",
      bands: [{ from: 1955, to: 1958, label: "Military rule" }, { from: 1966, to: 1973, label: "Military rule" }, { from: 1976, to: 1983, label: "Military junta" }],
      say: (d) => {
        const lo = peak(d, "ARG", true, 1950), l = d.last("ARG");
        return lo && l ? `Argentina's liberal democracy score fell to ${d.fmt(lo.value)} in ${lo.year} and was ${d.fmt(l.value)} in ${l.year}, forty years after democracy returned in 1983.` : missing("Democracy scores");
      } },
  ],
};

export const COUNTRY_STORIES: Story[] = [nz, korea, china, ireland, rwanda, poland, japan, argentina];
