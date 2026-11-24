// The second set of stories (twelve). Like the first, every sentence is worked out from the
// figures when the page opens, and each ends on where New Zealand sits.

import { ordinal, pct, times, type Named, type RankData, type Story } from "@/lib/story";

const NZ = { id: "NZL", name: "New Zealand" };
const AU = { id: "AUS", name: "Australia" };
const UK = { id: "GBR", name: "United Kingdom" };
const US = { id: "USA", name: "United States" };
const KEY = [NZ, AU, UK, US];
const KEY_IDS = ["NZL", "AUS", "GBR", "USA"];
const WORLD = { id: "world", name: "World" };
const e = (id: string, name: string): Named => ({ id, name });

// "New Zealand: 12.3 in 2023, 45th of 180" for the last step of most stories.
function whereNz(d: RankData, what: string, after = ""): string {
  const r = d.row("NZL");
  if (!r) return "New Zealand has no figure yet.";
  const ten = r.ten_years_before !== null ? `, from ${d.fmt(r.ten_years_before)} ten years before` : "";
  return `New Zealand: ${d.fmt(r.value)} ${what} in ${d.ranking.year}, ${ordinal(r.rank)} of ${d.ranking.rows.length} countries${ten}.${after ? ` ${after}` : ""}`;
}
// The row with the biggest ten-year rise (or fall) among a ranking.
function biggest(d: RankData, dir: 1 | -1) {
  return [...d.ranking.rows].filter((r) => r.ten_years_before !== null)
    .sort((a, b) => dir * ((b.value - b.ten_years_before!) - (a.value - a.ten_years_before!)))[0];
}

// ---------------------------------------------------------------- money and homes
const housing: Story = {
  id: "housing", group: "money", title: "Out of reach: houses against incomes", colour: "#b3541e",
  blurb: "House prices in New Zealand have run far ahead of what people earn. How that compares with the rest of the rich world, and with the US states.",
  sources: "OECD house prices, BIS household credit, US Census ACS (state home values and incomes).",
  steps: [
    { kind: "lines", indicator: "oecd_house_price_real", entities: KEY, from: 1970, kicker: "Prices after inflation",
      say: (d) => {
        const a = d.at("NZL", 1990), b = d.last("NZL"), u = d.at("GBR", 1990), v = d.last("GBR");
        return a && b ? `Taking out inflation, New Zealand house prices were ${times(b.value, a)} their 1990 level by ${b.year}${u && v ? `; in the UK, ${times(v.value, u)}` : ""}.`
          : "Real house prices since 1970 (index, 2015 = 100).";
      } },
    { kind: "bars", indicator: "oecd_price_to_income_vs_avg", top: 12, also: KEY_IDS, highlight: ["NZL"], kicker: "Against incomes",
      say: (d) => { const r = d.row("NZL"), t = d.ranking.rows[0];
        return r ? `Prices against incomes, compared with each country's own long-run average (100 = normal): New Zealand ${d.fmt(r.value)} in ${d.ranking.year}, ${ordinal(r.rank)} of ${d.ranking.rows.length}; ${t.name} is highest at ${d.fmt(t.value)}.`
          : `${t?.name ?? "–"} has the most stretched prices against incomes (${d.fmt(t?.value)}).`; } },
    { kind: "lines", indicator: "bis_household_credit_gdp", entities: KEY, from: 1980, kicker: "Borrowed to buy",
      say: (d) => { const a = d.last("NZL"), b = d.at("NZL", 1990);
        return a ? `Household debt in New Zealand came to ${d.fmt(a.value)} of GDP in ${a.year}${b !== null ? `, from ${d.fmt(b)} in 1990` : ""}. Most of it is mortgages.` : "Household debt as a share of GDP."; } },
    { kind: "states", indicator: "usreg_median_home_value", over: "usreg_median_household_income", show: "bars", label: "Median home value over median household income", kicker: "The US states",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1);
        return t && b ? `A typical home costs ${d.fmt(t.value)} a typical household's yearly income in ${t.name}, and ${d.fmt(b.value)} in ${b.name} (${d.year}).` : "US state figures are not loaded yet."; } },
  ],
};

const debt: Story = {
  id: "debt", group: "money", title: "Two hundred years of debt", colour: "#7a5c00",
  blurb: "Wars and crises pile up government debt; growth and inflation wear it down. Britain has been above 200% of GDP twice.",
  sources: "IMF historical public debt (Public Finances in Modern History), IMF World Economic Outlook, IMF Global Debt Database, the app's Episodes.",
  steps: [
    { kind: "lines", indicator: "govt_debt_gdp_long", entities: KEY, from: 1800, kicker: "Since 1800",
      bands: [{ from: 1803, to: 1815, label: "Napoleonic Wars" }, { from: 1914, to: 1918, label: "First World War" }, { from: 1939, to: 1945, label: "Second World War" }],
      episodes: true,
      say: (d) => {
        const uk = d.rows[0].filter((r) => r.entity_id === "GBR");
        const top = [...uk].sort((a, b) => b.value - a.value)[0];
        const l = d.last("GBR");
        return top ? `Britain's debt peaked at ${d.fmt(top.value)} of GDP in ${top.period}${l ? `; it was ${d.fmt(l.value)} in ${l.year}` : ""}. The wars are shaded, and so are the big crises since 1929.`
          : "Government debt since 1800.";
      } },
    { kind: "count", indicator: "govt_debt_gdp", label: "with government debt above 100% of GDP", test: (v) => v > 100, kicker: "Over 100%",
      say: (d) => { const y1 = d.lastEstimate ?? d.years.at(-1)!; const a = d.at(2007), b = d.at(y1);
        return `${a?.count ?? "–"} countries had government debt above 100% of GDP in 2007; ${b?.count ?? "–"} did in ${y1}${d.years.at(-1)! > y1 ? ". Faded bars are the IMF's projections" : ""}.`; } },
    { kind: "bars", indicator: "imf_household_debt_gdp", top: 12, also: KEY_IDS, highlight: ["NZL"], kicker: "Household debt",
      say: (d) => whereNz(d, "of GDP owed by households", "Households in the rich English-speaking countries owe more than most.") },
    { kind: "lines", indicator: "govt_debt_gdp", entities: KEY, from: 2000, kicker: "Where New Zealand sits",
      say: (d) => { const n = d.last("NZL"), u = d.last("USA"), e2 = d.end("NZL");
        return n ? `New Zealand's government owed ${d.fmt(n.value)} of GDP in ${n.year}, against ${d.fmt(u?.value)} for the US${e2 && e2.year > n.year ? `; the IMF expects ${d.fmt(e2.value)} by ${e2.year}` : ""}.` : "Government debt since 2000."; } },
  ],
};

const top1: Story = {
  id: "top-1-percent", group: "money", title: "The top 1 percent", colour: "#a0306e",
  blurb: "The richest 1% took a far bigger share of income a century ago than in 1980. In the US most of that ground has come back.",
  sources: "World Inequality Database (through Our World in Data), World Bank.",
  steps: [
    { kind: "lines", indicator: "wid_income_top1", entities: [...KEY, e("FRA", "France")], from: 1900, kicker: "A century",
      say: (d) => { const lo = (id: string) => [...d.rows[0].filter((r) => r.entity_id === id && +r.period >= 1960 && +r.period <= 1990)].sort((a, b) => a.value - b.value)[0];
        const u = lo("USA"), ul = d.last("USA"), n = d.last("NZL");
        return u && ul ? `The richest 1% of Americans got ${d.fmt(u.value)} of income before tax in ${u.period}, and ${d.fmt(ul.value)} in ${ul.year}${n ? `; in New Zealand, ${d.fmt(n.value)}` : ""}.` : "The richest 1%'s share of income since 1900."; } },
    { kind: "bars", indicator: "wid_wealth_top10", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Wealth",
      say: (d) => whereNz(d, "of wealth held by the richest 10%", "Wealth is always far less equal than income.") },
    { kind: "map", indicator: "gini", kicker: "Income gaps",
      say: (d) => { const t = d.ranking.rows[0], b = d.ranking.rows.at(-1);
        return t && b ? `On the Gini index (0 is equal, 100 is one person taking everything), ${t.name} is most unequal at ${d.fmt(t.value)} and ${b.name} least at ${d.fmt(b.value)}.` : "Gini index."; } },
    { kind: "bars", indicator: "income_share_bottom20", top: 0, also: [...KEY_IDS, "DNK", "NOR", "JPN", "DEU", "FRA", "ZAF", "BRA"], highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "of income going to the poorest fifth") },
  ],
};

// ---------------------------------------------------------------- people
const greying: Story = {
  id: "greying", group: "people", title: "The greying world", colour: "#6b4c9a",
  blurb: "The typical person on Earth is about ten years older than in 1970. Who is ageing fastest, and how many workers each older person will have.",
  sources: "UN World Population Prospects (estimates to the latest year, projections after).",
  steps: [
    { kind: "map", indicator: "median_age", year: 1950, kicker: "1950",
      say: (d) => `In ${d.ranking.year} half the world's people were under ${d.fmt(d.row("world")?.value)}; only ${d.count((v) => v >= 35)} of ${d.ranking.rows.length} countries had a median age of 35 or more.` },
    { kind: "map", indicator: "median_age", year: 2050, kicker: "2050",
      say: (d) => `By ${d.ranking.year}, on the UN's middle path, the world's median age reaches ${d.fmt(d.row("world")?.value)} and ${d.count((v) => v >= 45)} countries pass 45.` },
    { kind: "count", indicator: "median_age", label: "with a median age of 40 or more", test: (v) => v >= 40, kicker: "Past 40",
      say: (d) => { const y1 = d.lastEstimate ?? d.years.at(-1)!; const a = d.at(1990), b = d.at(y1), c = d.at(2075);
        return `Countries with a median age of 40 or more: ${a?.count ?? "–"} in 1990, ${b?.count ?? "–"} in ${y1}${c ? `, and ${c.count} of ${c.total} expected by 2075` : ""}.`; } },
    { kind: "lines", indicator: "old_age_dependency_ratio", entities: [...KEY, e("JPN", "Japan"), e("CHN", "China")], from: 1950, kicker: "Fewer workers each",
      say: (d) => { const j = d.last("JPN"), n = d.last("NZL"), ne = d.end("NZL");
        return j && n ? `Japan has ${d.fmt(j.value)} people aged 65 and over for every 100 of working age (${j.year}); New Zealand ${d.fmt(n.value)}${ne && ne.year > n.year ? `, heading for ${d.fmt(ne.value)} by ${ne.year}` : ""}.` : "Older people per 100 of working age."; } },
    { kind: "bars", indicator: "pop_share_65_plus", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "of people aged 65 and over") },
  ],
};

const migrants: Story = {
  id: "migrants", group: "people", title: "Nations of migrants", colour: "#1f7a8c",
  blurb: "More than a quarter of New Zealanders and Australians were born overseas, a far higher share than in the UK or the US.",
  sources: "UN migrant stock (through the World Bank), UN World Population Prospects, UNHCR.",
  steps: [
    { kind: "bars", indicator: "migrant_stock_share", top: 12, also: KEY_IDS, highlight: ["NZL"], kicker: "Born abroad",
      say: (d) => { const n = d.row("NZL"), a = d.row("AUS"), u = d.row("GBR"), s = d.row("USA");
        return n ? `${d.fmt(n.value)} of New Zealand's people were born in another country (${d.ranking.year}), and ${d.fmt(a?.value)} of Australia's, against ${d.fmt(u?.value)} in the UK and ${d.fmt(s?.value)} in the US. The Gulf states top the list.` : "Share of people born abroad."; } },
    { kind: "lines", indicator: "net_migration_rate", entities: KEY, from: 1990, kicker: "Arrivals less departures",
      say: (d) => { const n = d.last("NZL"); const best = d.rows[0].filter((r) => r.entity_id === "NZL" && r.status === "E").sort((a, b) => b.value - a.value)[0];
        return n ? `New Zealand gained ${d.fmt(n.value)} people per 1,000 from migration in ${n.year}${best ? `; the most in a year since 1990 was ${d.fmt(best.value)} in ${best.period}` : ""}.` : "Net migration per 1,000 people."; } },
    { kind: "map", indicator: "refugees_hosted", kicker: "Who takes refugees in",
      say: (d) => { const t = d.ranking.rows.slice(0, 3);
        return t.length ? `The most refugees live in ${t.map((r) => `${r.name} (${d.fmt(r.value)})`).join(", ")} in ${d.ranking.year}: mostly countries next to wars, not rich ones far away.` : "Refugees hosted."; } },
    { kind: "bars", indicator: "refugees_from", top: 10, also: ["NZL"], highlight: [], kicker: "Where they come from",
      say: (d) => { const t = d.ranking.rows[0]; return t ? `${t.name} is the largest source of refugees, with ${d.fmt(t.value)} living abroad under UNHCR's care (${d.ranking.year}).` : "Refugees by country of origin."; } },
  ],
};

const longLives: Story = {
  id: "richer-longer", group: "people", title: "Richer and longer-lived", colour: "#1a7f5a",
  blurb: "Richer countries live longer, but the US spends the most on health and lives shorter than its peers.",
  sources: "World Bank (income, health spending, child deaths), UN World Population Prospects (life expectancy).",
  steps: [
    { kind: "bubbles", x: "gdp_ppp_per_capita", y: "life_expectancy", from: 1990, logX: true, highlight: [...KEY_IDS, "JPN", "CHN", "IND", "NGA"], kicker: "Money and years",
      say: (d) => { const u = d.at("USA", d.last), j = d.at("JPN", d.last), n = d.at("NZL", d.last);
        return u && j ? `In ${d.last}, Americans had ${d.fmtX(u.x)} a head (in dollars of equal buying power) and lived ${d.fmtY(u.y)} years; the Japanese had less money and lived ${d.fmtY(j.y)} years${n ? `, New Zealanders ${d.fmtY(n.y)}` : ""}.` : "Income against life expectancy."; } },
    { kind: "lines", indicator: "life_expectancy", entities: [...KEY, e("JPN", "Japan")], from: 1960, to: 2030, kicker: "Falling behind",
      say: (d) => { const u = d.last("USA"), n = d.last("NZL"), u80 = d.at("USA", 1980), n80 = d.at("NZL", 1980);
        return u && n ? `In 1980 Americans and New Zealanders lived about as long (${d.fmt(u80)} and ${d.fmt(n80)} years); by ${u.year} the gap was ${(n.value - u.value).toFixed(1)} years in New Zealand's favour.` : "Life expectancy since 1960."; } },
    { kind: "bars", indicator: "health_spending_gdp", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "What it costs",
      say: (d) => { const u = d.row("USA"); return whereNz(d, "of GDP spent on health", u ? `The US spends ${d.fmt(u.value)}.` : ""); } },
    { kind: "bars", indicator: "under5_mortality", top: 0, also: [...KEY_IDS, "JPN", "FIN", "CAN", "FRA", "DEU", "CHN", "IND", "NGA"], highlight: ["NZL"], order: "asc", kicker: "Where New Zealand sits",
      say: (d) => { const r = d.row("NZL"); return r ? `${d.fmt(r.value)} children in every 1,000 born in New Zealand die before turning five (${d.ranking.year}), against ${d.fmt(d.row("JPN")?.value)} in Japan and ${d.fmt(d.row("USA")?.value)} in the US.` : "New Zealand has no figure yet."; } },
  ],
};

// ---------------------------------------------------------------- war, power and politics
const war: Story = {
  id: "return-of-war", group: "power", title: "The return of war", colour: "#8b1e1e",
  blurb: "Deaths in fighting fell for decades after the Cold War, then rose again with Syria, Ethiopia, Ukraine and Gaza.",
  sources: "UCDP (Uppsala Conflict Data Program) and ACLED, Oryx, DeepStateMap.",
  steps: [
    { kind: "lines", indicator: "fighting_deaths", entities: [WORLD], from: 1989, kicker: "Since the Cold War", about: "deaths in fighting (UCDP and ACLED)",
      say: (d) => { const w = d.rows[0].filter((r) => r.entity_id === "world" && r.status === "E");
        const lo = [...w].filter((r) => +r.period >= 1995 && +r.period <= 2012).sort((a, b) => a.value - b.value)[0];
        const hi = [...w].sort((a, b) => b.value - a.value)[0];
        return lo && hi ? `Deaths in fighting fell to ${d.fmt(lo.value)} in ${lo.period} and rose to ${d.fmt(hi.value)} in ${hi.period}, the most in the record.` : "Deaths in fighting worldwide."; } },
    { kind: "count", indicator: "fighting_deaths", label: "with 1,000 or more deaths in fighting", test: (v) => v >= 1000, kicker: "Countries at war",
      say: (d) => { const y1 = d.years.at(-1)!; const a = d.at(2005), b = d.at(y1);
        return `Countries with 1,000 or more deaths in fighting in a year: ${a?.count ?? "–"} in 2005, ${b?.count ?? "–"} in ${y1}.`; } },
    { kind: "map", indicator: "fighting_deaths", kicker: "Where",
      say: (d) => { const t = d.ranking.rows.slice(0, 3); return t.length ? `Most deaths in fighting in ${d.ranking.year}: ${t.map((r) => `${r.name} (${d.fmt(r.value)})`).join(", ")}.` : "Deaths in fighting."; } },
    { kind: "war", kicker: "Ukraine",
      say: ({ w }) => { const a = w.areas.at(-1); const t = w.latest.find((l) => l.category === "tanks");
        const lost = t?.RUS_seen; return `${a ? `Russia held ${Math.round(a[1]).toLocaleString("en")} km² of Ukraine on ${a[0]}` : w.name}${lost != null ? `, and had lost at least ${Number(lost).toLocaleString("en")} tanks seen in photos or video` : ""}.`; } },
  ],
};

const rearm: Story = {
  id: "rearming", group: "power", title: "Who's rearming", colour: "#3d4a3d",
  blurb: "Military budgets are rising again across Europe and Asia. Where the money goes, who buys the weapons, and where New Zealand sits.",
  sources: "SIPRI (through the World Bank), Global Firepower (its own score).",
  steps: [
    { kind: "bars", indicator: "military_spending_gdp", by: "change", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Biggest rises",
      say: (d) => { const b = biggest(d, 1); return b ? `${b.name} raised military spending the most: from ${d.fmt(b.ten_years_before)} of GDP to ${d.fmt(b.value)} in the ten years to ${d.ranking.year}.` : "Ten-year change in military spending."; } },
    { kind: "lines", indicator: "military_spending_usd", entities: [US, e("CHN", "China"), e("RUS", "Russia"), UK, AU], from: 1990, kicker: "The big budgets",
      say: (d) => { const u = d.last("USA"), c = d.last("CHN");
        return u && c ? `The US spent ${d.fmt(u.value)} on its military in ${u.year}, ${times(u.value, c.value)} China's ${d.fmt(c.value)} (at market exchange rates).` : "Military spending in US dollars."; } },
    { kind: "bars", indicator: "arms_imports", top: 10, also: ["AUS", "NZL"], highlight: ["NZL", "AUS"], kicker: "Buyers",
      say: (d) => { const t = d.ranking.rows[0], a = d.row("AUS"); return t ? `${t.name} imported the most weapons in ${d.ranking.year}${a ? `; Australia ranked ${ordinal(a.rank)}` : ""}. Values are SIPRI's trend-indicator values, a measure of military worth rather than price.` : "Arms imports."; } },
    { kind: "bars", indicator: "gfp_power_index", top: 10, order: "asc", also: KEY_IDS, highlight: ["NZL"], kicker: "One outfit's ranking",
      say: (d) => { const r = d.row("NZL"); return `Global Firepower's own score (lower is stronger; its formula is not published): ${d.ranking.rows[0]?.name ?? "–"} comes first${r ? `, New Zealand ${ordinal(d.ranking.rows.length - r.rank + 1)} of ${d.ranking.rows.length}` : ""}.`; } },
    { kind: "bars", indicator: "military_spending_gdp", top: 0, also: [...KEY_IDS, "CHN", "RUS", "POL", "ISR", "JPN", "DEU", "UKR", "IRL"], highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "of GDP spent on the military") },
  ],
};

const democracy: Story = {
  id: "democracy", group: "power", title: "Democracy's ebb tide", colour: "#4a6fa5",
  blurb: "Democracy spread fast after 1990. For more than a decade now, more countries have slipped back than moved forward.",
  sources: "V-Dem and Regimes of the World, EIU Democracy Index (through Our World in Data).",
  steps: [
    { kind: "count", indicator: "regime_row", label: "counted as liberal democracies", test: (v) => v >= 3, kicker: "Liberal democracies",
      say: (d) => { const y1 = d.years.at(-1)!; const k = d.counts.indexOf(Math.max(...d.counts)); const a = d.at(1990), b = d.at(y1);
        return `Liberal democracies (Regimes of the World): ${a?.count ?? "–"} in 1990, a peak of ${d.counts[k]} in ${d.years[k]}, and ${b?.count ?? "–"} in ${y1}.`; } },
    { kind: "map", indicator: "democracy_eiu", kicker: "Today",
      say: (d) => `On the EIU's 0 to 10 index, ${d.count((v) => v >= 8)} of ${d.ranking.rows.length} countries count as full democracies (8 or more) in ${d.ranking.year}, and ${d.count((v) => v < 4)} as authoritarian (under 4).` },
    { kind: "bars", indicator: "vdem_liberal", by: "change", order: "asc", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Biggest falls",
      say: (d) => { const b = biggest(d, -1); return b ? `${b.name} fell furthest on V-Dem's liberal democracy index in ten years: from ${d.fmt(b.ten_years_before)} to ${d.fmt(b.value)} (${d.ranking.year}).` : "Ten-year change."; } },
    { kind: "lines", indicator: "vdem_liberal", entities: [NZ, US, e("HUN", "Hungary"), e("IND", "India"), e("TUR", "Turkey")], from: 1990, kicker: "Where New Zealand sits",
      say: (d) => { const n = d.last("NZL"), h = d.last("HUN"), h0 = d.at("HUN", 2009);
        return n ? `New Zealand scores ${d.fmt(n.value)} of 1 (${n.year})${h && h0 !== null ? `; Hungary went from ${d.fmt(h0)} in 2009 to ${d.fmt(h.value)}` : ""}.` : "V-Dem liberal democracy index."; } },
  ],
};

// ---------------------------------------------------------------- energy
const energy: Story = {
  id: "energy-beyond-power", group: "energy", title: "Electricity is the easy part", colour: "#d68910",
  blurb: "New Zealand's power is mostly renewable, but cars, trucks, planes and industry still run largely on oil and gas.",
  sources: "Our World in Data energy, World Bank (SE4ALL, IEA), MBIE energy balances, UN energy statistics.",
  steps: [
    { kind: "lines", indicator: "renewables_share_elec", indicators: ["renewables_share_elec", "renewable_share_final_energy"], labels: ["Electricity", "All energy used"], sameAxis: true,
      entities: [NZ], from: 1990, kicker: "Two different shares",
      say: (d) => { const a = d.last("NZL", 0), b = d.last("NZL", 1);
        return a && b ? `Renewables made ${d.fmt(a.value, 0)} of New Zealand's electricity (${a.year}) but only ${d.fmt(b.value, 1)} of all the energy it used (${b.year}).` : "Renewable shares of electricity and of all energy."; } },
    { kind: "view", view: "energyflow", entity: "NZL", kicker: "Where it goes",
      say: "From source to use: the thick oil band runs almost all to transport, and the gap between energy supplied and energy used is mostly heat lost." },
    { kind: "bars", indicator: "energy_imports_net_share", top: 0, also: [...KEY_IDS, "JPN", "DEU", "FRA", "NOR", "CHN", "IND", "SGP"], highlight: ["NZL"], kicker: "Bought abroad",
      say: (d) => whereNz(d, "of its energy imported (net)", "Below zero means a country sells more energy than it buys.") },
    { kind: "bars", indicator: "energy_use_per_capita", top: 10, also: KEY_IDS, highlight: ["NZL"], kicker: "Where New Zealand sits",
      say: (d) => whereNz(d, "kg (in oil equivalent) of energy used per person") },
  ],
};

// ---------------------------------------------------------------- places
const americas: Story = {
  id: "fifty-americas", group: "places", title: "Fifty Americas", colour: "#2c4f9e",
  blurb: "Mississippi and Massachusetts are as far apart in income and life expectancy as two different countries. And Americans are moving south.",
  sources: "US Census (ACS, population estimates), County Health Rankings, MIT Election Lab; World Bank and UN for whole countries.",
  steps: [
    { kind: "states", indicator: "usreg_median_household_income", kicker: "Income",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1); return t && b ? `A typical household in ${t.name} took in US$${d.fmt(t.value)} in ${d.year}; in ${b.name}, US$${d.fmt(b.value)}.` : "Median household income."; } },
    { kind: "states", indicator: "usreg_domestic_migration", per: "people", show: "bars", label: "People moving in from other states, less those leaving", kicker: "On the move",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1); return t && b ? `Moves between states in ${d.year}: ${t.name} gained ${t.value.toFixed(1)} people for every 1,000 living there, and ${b.name} lost ${Math.abs(b.value).toFixed(1)}.` : "Moves between states."; } },
    { kind: "states", indicator: "usreg_life_expectancy", show: "bars", refs: { indicator: "life_expectancy", entities: ["NZL", "AUS", "GBR", "JPN", "USA"] }, kicker: "How long people live",
      say: (d) => { const t = d.rows[0], b = d.rows.at(-1), n = d.refs.find((r) => r.id === "NZL");
        return t && b ? `People live ${d.fmt(t.value)} years on average in ${t.name} and ${d.fmt(b.value)} in ${b.name}${n ? `; New Zealand as a whole: ${d.fmt(n.value)}` : ""}.` : "Life expectancy by state."; } },
    { kind: "states", indicator: "usreg_pres_dem_share", minus: "usreg_pres_rep_share", label: "Democrat lead over Republican in the presidential vote", kicker: "The vote",
      say: (d) => { const dem = d.rows.filter((r) => r.value > 0).length; return `In ${d.year}, ${dem} of ${d.rows.length} places gave the Democrat more votes and ${d.rows.length - dem} the Republican.`; } },
  ],
};

// ---------------------------------------------------------------- forecasts
const forecasts: Story = {
  id: "forecasts", group: "forecasts", title: "How good are forecasts?", colour: "#555555",
  blurb: "The IMF's forecasts of New Zealand's growth, set against what then happened, and how betting markets and named pundits have done.",
  sources: "IMF World Economic Outlook (every edition since 1990), Polymarket, Metaculus and Manifold, Prediction Archive (pages you save).",
  steps: [
    { kind: "track", indicator: "gdp_growth", entity: "NZL", show: "paths", kicker: "New Zealand's growth",
      say: (t) => { const s = t.stats.find((x) => x.horizon === 1 && x.mae != null);
        return s ? `Each thin line is what one IMF release expected for New Zealand's growth. A year ahead, the ${s.season} forecasts missed by ${s.mae!.toFixed(1)} points on average${s.bias != null ? ` and ran ${s.bias > 0 ? "too high" : "too low"} by ${Math.abs(s.bias).toFixed(1)}` : ""}.` : "IMF forecasts against what happened."; } },
    { kind: "track", indicator: "gdp_growth", entity: "NZL", show: "countries", highlight: KEY_IDS, kicker: "Every country",
      say: (t) => { const c = (t.countries ?? []).filter((x) => x.mae != null && x.n >= 8); const n = c.find((x) => x.entity_id === "NZL");
        const k = n ? [...c].sort((a, b) => a.mae! - b.mae!).indexOf(n) + 1 : 0;
        return n ? `Next-year growth forecasts for New Zealand typically miss by ${n.mae!.toFixed(1)} points, ${ordinal(k)} closest of ${c.length} countries. Big swings (oil, war, tourism) make some countries far harder.` : "Typical miss by country."; } },
    { kind: "scores", who: "crowd", kicker: "The crowd",
      say: (d) => { const s = [...d.rows].sort((a, b) => a.brier! - b.brier!); const b = s[0];
        return b ? `On questions that have settled, ${b.name} scores best (Brier ${b.brier!.toFixed(3)}, from ${b.n} questions). A score under 0.25 beats guessing 50% every time.` : "Crowd forecasts scored."; } },
    { kind: "scores", who: "pundits", kicker: "Named pundits",
      say: (d) => { const hits = d.rows.map((r) => r.hit!).sort((a, b) => a - b); const mid = hits[Math.floor(hits.length / 2)];
        return `Of ${d.rows.length} forecasters with ten or more graded calls, the middle one got ${pct(mid * 100, 100)} right; the best ${d.rows[0].name}, at ${pct(d.rows[0].hit! * 100, 100)}.`; } },
  ],
};

export const MORE_STORIES: Story[] = [housing, debt, top1, greying, migrants, longLives, war, rearm, democracy, energy, americas, forecasts];
