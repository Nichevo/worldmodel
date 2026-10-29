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
# 2. a throwaway data folder, the normal pipeline, then copy the build
export WORLDMODEL_HOME=$PWD/sample_home
worldmodel-data fetch un_wpp --from sample_inputs/un_wpp
worldmodel-data fetch imf_weo --from sample_inputs/imf_weo
worldmodel-data build
worldmodel-data publish app/sample/worldmodel-sample.duckdb
```
