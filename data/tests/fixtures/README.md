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
results in the Query Service's JSON layout. They also give the sample
warehouse its handful of example events.
