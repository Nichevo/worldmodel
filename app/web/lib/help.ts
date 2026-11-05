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
  voting: {
    title: "UN voting",
    what: "How often this country voted the same way as others in the UN General Assembly each year, where its votes place it on one scale (the ideal point), and its Security Council seats and vetoes.",
    how: "Agreement is the share of the year's recorded votes on which both countries voted the same way (yes, no or abstain). A group's line (EU members, say) is the average of the agreement with each of its members that year. The ideal point comes from all of a country's votes: higher means closer to the United States and the Western order. Vetoes are the permanent members' negative votes on Security Council drafts.",
    units: "% of votes alike; ideal point on a scale of about -3 to 3",
    sources: [{ label: "Voeten, Strezhnev and Bailey, UN General Assembly Voting Data", indicator: "unga_agreement" }, { label: "UN Dag Hammarskjöld Library, veto list" }],
  },
  between: {
    title: "Between countries",
    what: "The country's dealings with others and with world bodies: sanctions on it, IMF programmes, WTO trade disputes, treaties joined, cases at international courts, summits hosted and Security Council resolutions about it.",
    how: "Each line is an event from its own source. Sanctions are cases in the Global Sanctions Data Base (a file you download yourself); IMF programmes come from the IMF's MONA database, sized at the amount agreed; WTO disputes from the WTO's list of cases; treaties from the UN Treaty Collection for a fixed list of major treaties; court cases, summits and resolutions from Wikidata.",
    sources: [{ label: "Global Sanctions Data Base", indicator: "sanctions_active" }, { label: "IMF MONA" }, { label: "WTO dispute settlement" }, { label: "UN Treaty Collection", indicator: "treaties_joined" }, { label: "Wikidata" }],
  },
  crisiswatch: {
    title: "CrisisWatch",
    what: "International Crisis Group's monthly rating of the country's conflict situation since 2003, with what happened that month.",
    how: "Each month Crisis Group marks a situation as deteriorated, improved or unchanged, and flags a conflict risk alert or resolution opportunity for the month ahead. The strip shows every month stored: red worse, blue better, grey unchanged, blank not rated. Refresh reads one month's page at a time, a few seconds apart, and fills in older months a few each time (Settings: CrisisWatch).",
    units: "Ratings, one per month",
    sources: [{ label: "International Crisis Group, CrisisWatch" }],
  },
  laws: {
    title: "Laws and rules",
    what: "The country's rules as they stand in the latest year stored, with the year each one took its current form, and every change found over the years.",
    how: "Women, Business and the Law gives the laws in force on 1 October each year since 1970 (paid leave, retirement ages, women's rights at work, in marriage and over property). Same-sex marriage is a hand-checked list. Tables you load yourself (WORLD Policy, GunPolicy.org) add their own rules. A change is the first year a value differs from the year before.",
    units: "Yes or no; days of leave; years of age",
    sources: [{ label: "World Bank, Women, Business and the Law", indicator: "wbl_index" }, { label: "Hand-checked list", indicator: "law_same_sex_marriage" }],
  },
  relationships: {
    title: "Relationships",
    what: "Pairs of figures that move together, where one tends to move first, or where the link holds after allowing for income and time. Nothing here proves cause and effect: each pair shows how strong its evidence is, and a note on what else could explain it.",
    how: "After each refresh the scan takes every pair of the indicators switched on and compares their yearly changes (not levels: two figures that both grow look related even when they are not), country by country, with each country's own average change taken out. Move together: the changes go together across countries and years. One tends to come first: one figure's changes one to three years earlier help predict the other's, beyond what its own past says (a Granger test pooled over countries, with country and year effects taken out), and for the strongest pairs the same test is run in each country on its own. Holds after allowing for income and time: the same-year link survives taking out growth of GDP per person, the year (world-wide swings such as 2009) and fixed differences between countries. Standard errors allow for each country's years being alike, and with thousands of pairs some will look related by chance, so each test is corrected for that (false discovery rate, Settings: Relationship scan).",
    units: "Correlation from -1 to 1; size: how much the second figure changes for one unit of change in the first, same year",
  },
  events_link: {
    title: "Before and after events",
    what: "How a figure changed in countries after an event (a recession, coup, election, law change and so on) compared with countries in the same income group that had no such event in those years.",
    how: "For each event, the change from the year before it to each year after, less the average change over the same years in countries of the same income group with no event of that kind from 3 years before to 5 years after. The line before year 0 shows whether the countries were already different beforehand. Links that hold by definition (a recession lowering GDP) are hidden unless you ask for them.",
    units: "Percent change for levels; points for rates and shares",
  },
  holidays: {
    title: "Public holidays",
    what: "This year's public holidays, month by month. Holidays kept only in some states or regions are marked.",
    how: "From Nager.Date's free holiday list, read every 90 days for this year and next (Settings: Public holidays). Countries it does not cover show nothing.",
    sources: [{ label: "Nager.Date", indicator: "public_holidays" }],
  },
  crime: {
    title: "Crime and prisons",
    what: "Recorded crime by broad type and the number of people in prison, per 100,000 people.",
    how: "UNODC collects what each country's police and prisons report. Offence types are grouped into broad kinds (violent, sexual, property, fraud and corruption, drugs) by adding the top-level types UNODC lists. Countries define and record crimes differently, so compare a country with itself over time rather than levels across countries.",
    units: "Per 100,000 people",
    sources: [{ label: "UNODC crime and criminal justice statistics", indicator: "homicide_rate" }],
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
  places: {
    title: "Transport, universities and companies",
    what: "Metro, light rail and commuter rail systems with their length, stations and trips a year; universities with their students; and big companies with their revenue, staff and industry.",
    how: "Read from Wikidata once every four weeks. A place is matched to the nearest city within 40 km (preferring a much bigger city almost as close, so suburbs count toward the main city). Company revenue is turned into US dollars with the World Bank's exchange rate for the revenue's year (BIS where the World Bank has none). Wikidata is edited by volunteers, so figures can be missing or a few years old; the year of each figure is shown.",
    units: "Kilometres, trips a year, students, US dollars",
    sources: [{ label: "Wikidata (CC0)" }, { label: "World Bank and BIS exchange rates", indicator: "exchange_rate_usd" }],
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
