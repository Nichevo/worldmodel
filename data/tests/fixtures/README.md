Test fixtures in the layouts the connectors read: the official UN WPP CSV
files and IMF DataMapper JSON. Cut from the sample inputs (see
scripts/sample/make_sample_inputs.py): every location, a few years.

world_bank_wdi/WDI_CSV.zip: seven WDI series for every economy, 2019-2023, made
with scripts/sample/make_wdi_inputs.py from the datahub.io mirror. owid_energy:
a few columns of OWID's energy CSV and codebook, 2018-2022. owid_grapher: a
hand-made chart file in OWID's download layout (made-up values).

Events: powell_thyne, ucdp_acd and emdat are small hand-made files in each
source's own layout (a few real events, figures rounded or approximate, plus a
made-up country that must not match); wikidata_*.json are hand-made query
results in the Query Service's JSON layout. The leaders file has the heads of
government of New Zealand, the UK and the US since about 1960 with their parties
and party colours (real names and dates; the people's QIDs from Q9900001 on are
placeholders). They also give the sample warehouse its handful of example events.

House prices, migration and education (scripts/sample/make_d3_inputs.py, from
copies of the real data on GitHub, cut to NZL, AUS, GBR, USA, DEU, SYR and IND):
bis/spp_*_index.csv (BIS property prices, the connector's GitHub fallback),
wittgenstein/*.csv (Wittgenstein Centre v3 tables, ages 25+), unhcr/population_*.json
(UNHCR figures in the API's page layout) and un_ims/*.xlsx (the UN's 2020 migrant
stock edition laid out like its Table 1, with World totals added).

Made-up values in real layouts, for sources with no copy on GitHub: bis/spp.csv
(the BIS API's CSV with labels; Switzerland's real index), bis/tc_households.csv,
oecd/*.csv (OECD SDMX csvfile layout, house prices shaped on the BIS index),
dallas_fed_ihpd/hp2502.xlsx, imf_gdd/*.json, undp_hdr/*.csv (Latin-1, as UNDP's
file is) and idea_turnout/*.csv (IDEA's export layout; real turnout figures for a
few NZ, UK and US elections, plus an EU election and a made-up country to skip).
