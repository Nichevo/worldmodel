# Data licences and attributions

Worldmodel is a personal, non-commercial tool. Sources with non-commercial
terms are marked so they can be swapped if that ever changes
(`commercial_use` in `contract/worldmodel_contract/catalogues/sources.yaml`).

| What | Source | Licence |
| --- | --- | --- |
| Population data, and the sample warehouse's population data | United Nations, DESA, Population Division (2024). World Population Prospects 2024. The sample uses the UN's own `wpp2024` R package (github.com/PPgp/wpp2024). | CC BY 3.0 IGO |
| Economic data | International Monetary Fund, World Economic Outlook database. The sample uses the April 2015 release as mirrored by datahub.io (github.com/datasets/imf-weo). | IMF terms of use (free with attribution) |
| Past economic forecasts | International Monetary Fund, World Economic Outlook historical forecasts database (WEOhistorical). | IMF terms of use (free with attribution) |
| World development indicators, income groups and military spending | World Bank, World Development Indicators (military series from SIPRI through WDI). The sample uses the datahub.io mirror (github.com/datasets/world-development-indicators). | CC BY 4.0 |
| Energy data | Our World in Data, Energy dataset (github.com/owid/energy-data), based on Ember Yearly Electricity Data, the Energy Institute Statistical Review of World Energy and the U.S. EIA | CC BY 4.0 (OWID, Ember); EI and EIA free with attribution |
| Deaths in armed conflicts | Uppsala Conflict Data Program (UCDP), processed by Our World in Data | UCDP free with attribution; OWID CC BY 4.0 |
| Factbook text and numbers | Central Intelligence Agency, The World Factbook, editions 1990 to 2025, as collected by the CIA World Factbooks Archive 1990-2025 (github.com/MilkMp/CIA-World-Factbooks-Archive-1990-2025). The sample warehouse holds a cut of it. | Public domain (US government work); the archive's code is MIT |
| Country facts box, elections, leaders, sporting events and named disasters | Wikidata (wikidata.org) | CC0 |
| Coups | Powell, Jonathan M. and Clayton L. Thyne (2011), "Global instances of coups from 1950 to 2010: A new dataset", Journal of Peace Research 48(2): 249-259; updated data from uky.edu/~clthyn2/coup_data | Free to use with the citation |
| Armed conflicts | UCDP/PRIO Armed Conflict Dataset (ucdp.uu.se); Gleditsch et al. (2002), Journal of Peace Research 39(5); Davies, Pettersson and Öberg (2024), Journal of Peace Research | Free to use with the citation |
| Disasters (loaded by hand, not in the repository) | EM-DAT, CRED / UCLouvain, Brussels, Belgium, www.emdat.be | Free for non-commercial use after sign-in; not for redistribution |
| Notable episodes | Typed by hand from the sources linked on each row of `notable_episodes.csv` | n/a |
| Country introductions and pictures (fetched on your computer, not in the repository) | Wikipedia (en.wikipedia.org) text; pictures from Wikimedia Commons, each credited with its author and licence on the page where it is shown | Text CC BY-SA 4.0; pictures under their own licences, mostly CC BY-SA or public domain |
| Country list and UN M49 regions in the crosswalk | UN M49, packaged by github.com/lukes/ISO-3166-Countries-with-Regional-Codes | CC BY-SA 4.0 (the packaging) |
| Country outlines on the map (`app/web/public/geo/countries.json`) | Natural Earth, 1:50m admin 0 countries | Public domain |
| Bloc membership dates | Entered by hand from the sites linked on each row of `memberships.csv` | n/a |
