# Sample warehouse

`app/sample/worldmodel-sample.duckdb` lets the app run with no pipeline. It is
built by the real pipeline from real data; see `make_sample_inputs.py` for
where the inputs come from and how they differ from a full refresh (an old IMF
WEO release, age groups every fifth year, a few WPP columns missing).

To rebuild it:

```sh
pip install rdata pandas
# 1. the inputs: WPP 2024 .rda files from github.com/PPgp/wpp2024 (data/),
#    and data/values.csv from github.com/datasets/imf-weo
python scripts/sample/make_sample_inputs.py RDA_DIR values.csv sample_inputs
#    World Bank: the main series and a quarter of the rest from the mirror at
#    github.com/datasets/world-development-indicators, from 1990, as WDI_CSV.zip
python scripts/sample/make_wdi_inputs.py MIRROR_DIR sample_inputs/world_bank_wdi/WDI_CSV.zip --series CODES --first-year 1990
#    OWID energy: owid-energy-data.csv and its codebook from github.com/owid/energy-data,
#    cut to the main columns (ENERGY_MAIN in connectors/owid.py, the amounts
#    behind their shares, and each fuel's <fuel>_electricity and <fuel>_consumption
#    for the energy mix charts) and years from 1990, in sample_inputs/owid_energy/
#    CIA Factbook: factbook.db from the archive's release (see connectors/cia_factbook.py),
#    cut to the last edition plus every edition of the fields the numeric series read
python scripts/sample/make_factbook_sample.py factbook.db sample_inputs/cia_factbook/factbook.db
# 2. a throwaway data folder, the normal pipeline, then copy the build
export WORLDMODEL_HOME=$PWD/sample_home
for s in un_wpp imf_weo world_bank_wdi owid_energy cia_factbook; do worldmodel-data fetch $s --from sample_inputs/$s; done
#    a few example events (coups, conflicts, disasters, elections, sporting events): the test fixtures
for s in powell_thyne ucdp_acd emdat wikidata; do worldmodel-data fetch $s --from data/tests/fixtures/$s; done
worldmodel-data build
worldmodel-data publish app/sample/worldmodel-sample.duckdb
# 3. keep Factbook text for the last edition, and every edition for a few countries only
python scripts/sample/trim_sample_texts.py app/sample/worldmodel-sample.duckdb
```

The test fixture `data/tests/fixtures/cia_factbook/factbook.db` is cut the same
way by `make_factbook_fixture.py` (three editions of a few countries).
