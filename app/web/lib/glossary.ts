// Glossary: short notes on the terms the charts use, linked from each chart's "?" note
// when its name, unit or description uses one. Written by hand; `match` finds a term in
// an indicator's text (whole words, any case).

export type Term = { id: string; term: string; group: string; text: string; match: RegExp; see?: string[] };

export const GLOSSARY: Term[] = [
  // money and prices
  { id: "nominal", term: "Nominal and real", group: "Money and prices", match: /\b(nominal|real|constant (prices|dollars|us\$)|current (prices|us\$|dollars))\b/i,
    text: "Nominal (or current-price) figures are in the money of each year, so they rise with inflation. Real (constant-price) figures take inflation out, valuing every year at one base year's prices, so a rise is a rise in the amount of goods and services. Growth rates are almost always real.", see: ["inflation", "deflator"] },
  { id: "ppp", term: "PPP (purchasing power parity)", group: "Money and prices", match: /\b(ppp|purchasing power)\b/i,
    text: "Converts money between countries at the rate that buys the same basket of goods in each, not at the market exchange rate. A haircut costs less in India than in Norway, so market rates understate how much poorer countries' incomes buy. Use PPP to compare living standards; use market rates to compare what countries can buy abroad (imports, debt in dollars).", see: ["per-person"] },
  { id: "inflation", term: "Inflation", group: "Money and prices", match: /\b(inflation|consumer prices?|cpi)\b/i,
    text: "How fast prices rise, usually consumer prices over twelve months. 2% a year is most central banks' target. Above 20% a year counts as an inflation crisis in Reinhart and Rogoff's data; above 50% a month is hyperinflation." },
  { id: "deflator", term: "GDP deflator", group: "Money and prices", match: /\bdeflator\b/i,
    text: "The price change of everything an economy produces (not only what households buy), worked out as nominal GDP divided by real GDP. It moves with export prices, so it swings more than consumer prices in commodity exporters." },
  { id: "exchange-rate", term: "Exchange rate", group: "Money and prices", match: /\b(exchange rate|lcu per us\$|per us dollar|twi|trade-weighted)\b/i,
    text: "What one currency is worth in another. Shown as local currency per US dollar, so a rising line means the local currency is weaker. A trade-weighted index (TWI) averages the rate against many trading partners, weighted by trade." },
  // economy
  { id: "gdp", term: "GDP", group: "Economy", match: /\bgdp\b|gross domestic product/i,
    text: "Gross domestic product: the value of all final goods and services produced in a country in a year. It counts production inside the borders, whoever owns it. GNI adds income earned abroad and takes out income sent abroad, which matters for countries with much foreign ownership (Ireland, Luxembourg).", see: ["gni", "per-person", "nominal", "ppp"] },
  { id: "gni", term: "GNI", group: "Economy", match: /\bgni\b|gross national income/i,
    text: "Gross national income: GDP plus income residents earn from abroad, less income paid to foreigners. Closer to what a country's people actually receive." },
  { id: "per-person", term: "Per person (per capita)", group: "Economy", match: /\b(per (person|capita|head|inhabitant)|per 1,?000 people|per 100,?000|per million)\b/i,
    text: "A total divided by the number of people, so big and small countries compare. Per person figures can hide inequality: an average income says nothing about how it is shared.", see: ["gini"] },
  { id: "share-of-gdp", term: "Share of GDP", group: "Economy", match: /(% of gdp|share of gdp|of gdp\b)/i,
    text: "A flow or stock divided by a year's GDP, to scale it to the size of the economy. Debt of 100% of GDP means debt equal to one year's output; it does not mean the debt must be paid in a year." },
  { id: "current-account", term: "Current account", group: "Economy", match: /current account/i,
    text: "Exports less imports of goods and services, plus income and transfers from abroad less those paid out. A deficit is borrowed from (or sold to) the rest of the world; New Zealand has run one most years." },
  { id: "recession", term: "Recession", group: "Economy", match: /\brecession\b/i,
    text: "A fall in economic output. A common rule of thumb is two quarters in a row of falling real GDP; the app marks a recession year as one when real GDP fell." },
  // debt and crises
  { id: "default", term: "Default", group: "Debt and crises", match: /\bdefault/i,
    text: "Failing to pay debt on time and in full: missed payments, or a restructuring that leaves lenders with less. A government can default on debt held at home (domestic) or abroad (external, usually in foreign currency).", see: ["banking-crisis"] },
  { id: "banking-crisis", term: "Banking crisis", group: "Debt and crises", match: /banking crisis|systemic crisis/i,
    text: "Bank runs, failures or forced mergers, or government rescues of important banks. A systemic crisis is one big enough to threaten the whole banking system (Laeven and Valencia's definition)." },
  { id: "currency-crisis", term: "Currency crisis", group: "Debt and crises", match: /currency crisis|currency crash/i,
    text: "A fall of 15% or more in a year against the US dollar (or the pound, or another anchor), in Reinhart and Rogoff's definition." },
  // people
  { id: "tfr", term: "Fertility rate (TFR)", group: "People", match: /\b(fertility|tfr|births per woman)\b/i,
    text: "Total fertility rate: the number of children a woman would have if she lived through today's birth rate at each age. About 2.1 replaces each generation in rich countries (a little more where more children die young)." },
  { id: "life-expectancy", term: "Life expectancy", group: "People", match: /life expectancy/i,
    text: "How long a baby born this year would live if each year's death rates stayed as they are now. Low figures in the past were driven mostly by deaths of children, not by everyone dying young." },
  { id: "dependency", term: "Dependency ratio", group: "People", match: /dependency/i,
    text: "People of non-working age (under 15 and 65 and over) per 100 of working age. The old-age ratio counts only those 65 and over." },
  { id: "median-age", term: "Median age", group: "People", match: /median age/i, text: "The age that splits the population in half: half are younger, half older." },
  { id: "net-migration", term: "Net migration", group: "People", match: /net migration/i,
    text: "People arriving to live less people leaving to live elsewhere. A small net figure can hide large flows both ways, as in New Zealand." },
  // inequality and society
  { id: "gini", term: "Gini index", group: "Inequality and society", match: /\bgini\b/i,
    text: "Inequality on a scale of 0 (everyone has the same) to 100 (one person has everything). From household surveys; about 25 to 30 in the Nordic countries, about 40 in the US, over 60 in South Africa. Survey Ginis miss the very top incomes, which is why the World Inequality Database's top shares run higher.", see: ["top-share", "palma"] },
  { id: "top-share", term: "Top 1% and top 10% shares", group: "Inequality and society", match: /\b(top|richest) (1|10)\s?%|\bp99p100\b|top 1\b/i,
    text: "The share of all income (or wealth) going to the richest 1% or 10%. Before tax means before taxes and most transfers. If everyone had the same, the top 1% would have 1%." },
  { id: "palma", term: "Palma ratio", group: "Inequality and society", match: /\bpalma\b/i,
    text: "The richest 10%'s share of income divided by the poorest 40%'s. Most of the change in inequality happens at the two ends, which the Palma ratio looks at directly." },
  { id: "survey-wave", term: "Survey waves", group: "Inequality and society", match: /values survey|wvs|\bwave\b/i,
    text: "The World Values Survey asks about 1,200 people in each country, in rounds (waves) about every five years since 1981, and not every country is in every wave. Small changes between waves can be sampling noise." },
  // energy and climate
  { id: "primary-energy", term: "Primary energy", group: "Energy and climate", match: /primary energy/i,
    text: "Energy before it is converted: coal, oil and gas burned, and electricity from renewables and nuclear counted as if it replaced fuel (the substitution method). Electricity counts less than the fuel for a power station, because about 60% of that fuel's energy is lost as heat." },
  { id: "twh", term: "TWh, GW and kWh", group: "Energy and climate", match: /\b(twh|gwh|kwh|mw|gw)\b/i,
    text: "A watt-hour is energy, a watt is power (energy per moment). 1 TWh is a billion kWh, about what 140,000 New Zealand homes use in a year. A 1 GW power station running all year makes 8.76 TWh." },
  { id: "co2e", term: "CO2 equivalent", group: "Energy and climate", match: /co2e|co2 equivalent|greenhouse gas/i,
    text: "Greenhouse gases counted as the amount of CO2 that would warm as much over 100 years. Methane counts about 28 times CO2 by this measure, but warms much more over its first 20 years, which matters for New Zealand's farm emissions." },
  { id: "anomaly", term: "Temperature anomaly", group: "Energy and climate", match: /anomal/i,
    text: "How far a temperature is from the average of a base period (often 1951-1980 or 1991-2020). Anomalies compare places better than raw temperatures, because a warm year in Alaska and in Singapore mean different things in degrees." },
  // trade
  { id: "hs-code", term: "HS codes", group: "Trade", match: /\bhs\b|harmonized system/i,
    text: "The Harmonized System: the numbering customs offices use for goods, 2 digits for a chapter (87, vehicles), 4 for a heading, 6 for a product. The Sectors pages use the 1992 edition so trade lines up from 1995." },
  { id: "hhi", term: "Concentration (top-3 share and HHI)", group: "Trade", match: /\bhhi\b|herfindahl|concentrat/i,
    text: "How much of supply comes from a few countries. The Herfindahl-Hirschman index sums the squared percentage shares: under 1,500 counts as unconcentrated, over 2,500 as highly concentrated (10,000 is one supplier)." },
  // reading the charts
  { id: "projection", term: "Projections (dashed lines)", group: "Reading the charts", match: /projection|forecast|projected/i,
    text: "Dashed lines and faded bars are the source's own projections (UN, IMF, Pew), never data. Forecast ranges the app draws itself show where 80% and 95% of outcomes would fall if the past pattern held, which it often does not.", see: ["log-scale"] },
  { id: "log-scale", term: "Log scale", group: "Reading the charts", match: /\blog(arithmic)? scale\b/i,
    text: "Each step up the axis multiplies (10, 100, 1,000) rather than adds. Equal slopes mean equal growth rates, so a country growing 3% a year shows a straight line however big it is." },
  { id: "aggregate", term: "Group averages (World, OECD, blocs)", group: "Reading the charts", match: /\b(aggregate|weighted average|group average)\b/i,
    text: "Groups are worked out by the app from their members as they were in each year, weighted by population or GDP as suits the figure. A group line can jump when members join or when big members' figures are missing; its coverage shows how many members reported." },
  { id: "index", term: "Index (2015 = 100)", group: "Reading the charts", match: /=\s?100|\b(price|volume|production|cost of living) index\b/i,
    text: "A figure scaled so one year (or the top of a range) is 100. Only changes and ratios mean anything: an index of 120 is 20% above the base year, not 120 of anything." },
  { id: "grade", term: "Quality grades", group: "Reading the charts", match: /\bquality grade\b/i,
    text: "A to D on the Indicators page: A for official statistics from a standard source with long coverage, down to D for experimental figures or estimates the app makes. Settings > Quality decides which grades the drop-downs show." },
  { id: "correlation", term: "Moving together is not cause and effect", group: "Reading the charts", match: /\b(correlat|relationship scan|moves with)\b/i,
    text: "Two lines that rise together may both follow a third thing (income, time), or happen together by chance when many pairs are tested. The relationship scan controls for chance with a false discovery rate, and tests which one comes first, but cannot prove a cause." },
];

const ORDER = ["Reading the charts", "Economy", "Money and prices", "Debt and crises", "People", "Inequality and society",
  "Energy and climate", "Trade"];

export function glossaryGroups(): { group: string; terms: Term[] }[] {
  return ORDER.map((g) => ({ group: g, terms: GLOSSARY.filter((t) => t.group === g) })).filter((g) => g.terms.length);
}

/** Terms used in a chart's text (title, unit, description), at most `max`. */
export function termsIn(text: string, max = 3): Term[] {
  return GLOSSARY.filter((t) => t.match.test(text)).slice(0, max);
}
