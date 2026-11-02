// The "?" notes on the country page's cards: what each one shows in plain words,
// how it is worked out, its units and its sources. Single-indicator charts use the
// indicator's own description instead (see components/Help.tsx).

export type HelpNote = {
  title: string;
  what: string;
  how?: string;
  units?: string;
  sources?: { label: string; indicator?: string }[];
};

export const HELP = {
  about: {
    title: "About",
    what: "The opening of the country's Wikipedia article, with its photo, flag and location map.",
    how: "Read through Wikipedia's official API when you open the page, within the daily limit in Settings, and kept for a month.",
    sources: [{ label: "Wikipedia (CC BY-SA)" }],
  },
  sources_differ: {
    title: "Where sources disagree",
    what: "Indicators where two sources give clearly different figures for this country in the same year.",
    how: "Each indicator's latest year with figures from both sources; flagged when they are more than 5% apart, or for percentages more than 1 point and 10% apart.",
  },
  factbook: {
    title: "CIA World Factbook",
    what: "The country's Factbook entry as text, from any edition between 1990 and the final one in 2025.",
    how: "The CIA stopped the Factbook in February 2026, so this is a frozen archive; newer facts come from the other sources.",
    sources: [{ label: "CIA World Factbook (public domain), editions 1990–2025" }],
  },
  timeline: {
    title: "Timeline",
    what: "Dated events for this country, newest first: elections, leaders, coups, conflicts, sporting events, disasters, notable episodes and your own milestones.",
    how: "Recessions, booms, inflation spikes and debt surges are worked out from the data by fixed rules (for example a recession is a year of falling GDP). The rest come from the sources listed under each event.",
    sources: [{ label: "Wikidata" }, { label: "UCDP" }, { label: "Powell and Thyne coups" }, { label: "EM-DAT" }, { label: "Worldmodel rules" }],
  },
  energy_elec: {
    title: "Electricity generation by source",
    what: "How much electricity the country generates each year from each fuel: coal, gas, oil, nuclear, hydro, wind, solar and others.",
    how: "Generation at power stations, before losses in the grid. Share shows each fuel as a part of the total.",
    units: "Terawatt-hours (TWh) a year, or % of the total",
    sources: [{ label: "Ember, through Our World in Data", indicator: "coal_electricity" }],
  },
  energy_primary: {
    title: "Primary energy by source",
    what: "All the energy a country uses before it is converted: coal, oil and gas burned in power stations, cars, homes and factories, plus nuclear, hydro, wind and solar. It is larger than electricity alone because most energy is used directly as fuel.",
    how: "Nuclear and renewable electricity are counted as the fossil fuel it would take to make the same electricity (the substitution method), so they compare fairly with fuels that are burned.",
    units: "Terawatt-hours (TWh) a year, or % of the total",
    sources: [{ label: "Energy Institute Statistical Review, through Our World in Data", indicator: "coal_consumption" }],
  },
  housing: {
    title: "House prices and incomes",
    what: "House prices against incomes, both as an index (base year = 100), so the gap between the lines shows whether homes have become harder to afford. Below it, the price-to-income ratio against its own long-run average, and household debt.",
    how: "Nominal prices are set against nominal income per person, and real (after inflation) prices against real income. Each line comes from the first source with figures for the country.",
    units: "Index, base year = 100; debt as % of disposable income or % of GDP",
    sources: [{ label: "OECD", indicator: "oecd_house_price_nominal" }, { label: "Dallas Fed", indicator: "dfed_house_price_nominal" },
      { label: "BIS", indicator: "bis_house_price_nominal" }, { label: "IMF Global Debt Database", indicator: "imf_household_debt_gdp" }],
  },
  migration: {
    title: "Migration in and out",
    what: "People born abroad living here against people born here living abroad, or refugees hosted here against refugees who fled from here, with the ten largest countries on each side.",
    how: "Migrant stock counts everyone living outside the country they were born in, however long ago they moved. Refugees count people under UNHCR's mandate at the end of each year.",
    units: "People",
    sources: [{ label: "UN International Migrant Stock 2024", indicator: "migrant_stock" }, { label: "UNHCR", indicator: "refugees_hosted" }],
  },
  education: {
    title: "Education",
    what: "How much schooling adults have: average years of schooling for women and men since 1950, with a projection to 2100, and the share of adults by their highest level of education.",
    how: "Adults are people aged 25 and over. The projection is the Wittgenstein Centre's middle scenario.",
    units: "Years of schooling; % of adults",
    sources: [{ label: "Wittgenstein Centre (CC BY 4.0)" }, { label: "UNDP Human Development Report" }],
  },
  energyflow: {
    title: "Where energy comes from and goes",
    what: "One year of the country's energy balance as a flow: the fuels it produced or imported and kept (left), what was turned into electricity (middle), and the sectors that used the energy (right), with the losses on the way.",
    how: "Primary supply is production plus imports, less exports, stock building and fuel for international ships and planes. Conversion losses are the fuel going into power stations less the electricity coming out; geothermal counts at the heat drawn from the ground, so most of it shows as a loss. 'Losses and own use' covers refining, the energy industry's own use and losses in the grid and gas network.",
    units: "Petajoules (PJ), gross calorific value. 1 PJ is about 278 GWh.",
    sources: [{ label: "MBIE energy balance tables (New Zealand pack)", indicator: "nz_energy_primary_supply" }],
  },
  voters: {
    title: "Who votes",
    what: "Turnout by age group, and by sex or by group where the country reports it, at national elections.",
    how: "United States: the Census Bureau's survey after each November election, as a share of everyone of that age living in the US (citizens or not); people over-report voting a little. New Zealand: the Electoral Commission's count of who voted, as a share of people enrolled. The two are measured differently, so compare the age pattern rather than the levels.",
    units: "% of residents of voting age (US); % of enrolled voters (NZ)",
    sources: [{ label: "US Census Bureau, CPS table A-1", indicator: "us_voted" }, { label: "NZ Electoral Commission", indicator: "nz_turnout" }],
  },
  pyramid: {
    title: "Population by age and sex",
    what: "How many men (left) and women (right) there are in each five-year age group. A wide base means many children; a wide top means an older population.",
    how: "Estimates to the latest census-based year, then the UN's medium projection.",
    units: "People, or % of the population",
    sources: [{ label: "UN World Population Prospects 2024", indicator: "pop_by_age_sex" }],
  },
  debt: {
    title: "Debt per person",
    what: "What the government, households and companies owe, divided by everyone living in the country, so countries of any size compare. The stack adds up to total debt per person.",
    how: "Each sector's debt as a share of GDP, times GDP per person in US dollars (the same as debt divided by population). Government debt is general government where the IMF has it, else central government (World Bank). Local currency uses GDP per person in local currency instead.",
    units: "US dollars per person, local currency per person, or % of GDP",
    sources: [{ label: "IMF Global Debt Database", indicator: "imf_household_debt_gdp" }, { label: "World Bank WDI", indicator: "central_govt_debt_gdp" },
      { label: "IMF World Economic Outlook", indicator: "govt_debt_gdp" }, { label: "GDP per person", indicator: "gdp_per_capita_usd" }],
  },
  cities: {
    title: "Major cities",
    what: "The country's biggest cities, with how many people live there now and the UN's projection for 2035.",
    how: "The city list is GeoNames (every place of 15,000 people or more). Where the UN's World Urbanization Prospects has the city, its figure for the whole built-up area (city and suburbs) is used, which is usually larger than the city itself; other sources' cities are matched to GeoNames by name and location.",
    units: "People",
    sources: [{ label: "UN World Urbanization Prospects 2018", indicator: "city_population" }, { label: "GeoNames (CC BY)", indicator: "city_population" }],
  },
  prices: {
    title: "Prices and pay",
    what: "How dear the country is and what people earn: price level against the US, cost of living, average and median pay, the minimum wage, and the gap between women's and men's pay.",
    how: "Each row is the latest figure. Price level: World Bank (PPP conversion factor over the exchange rate, US = 1). Cost of living and median pay: WhereNext, anchored on World Bank price levels. Earnings and minimum wage: ILOSTAT. Numbeo's everyday prices are fetched only when you press the button (daily limit in Settings).",
    units: "Mixed; see each row",
    sources: [{ label: "WhereNext (CC BY)", indicator: "wn_cost_index" }, { label: "ILOSTAT", indicator: "ilo_earnings_ppp" }, { label: "World Bank", indicator: "price_level_ratio" }],
  },
  members: {
    title: "Members",
    what: "The countries in this group today, and when each joined or left.",
    how: "Group figures use the members of each year, so a 1990 value uses the members of 1990.",
  },
} satisfies Record<string, HelpNote>;
