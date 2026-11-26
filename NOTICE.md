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
| Weather forecast maps (downloaded while a weather layer is on, not in the repository) | NOAA National Centers for Environmental Prediction, Global Forecast System (GFS), from NOMADS | Public domain (US government work) |
| Rain radar on the map (read in the browser) | RainViewer (rainviewer.com) public weather maps API | Free with attribution |
| Clouds from satellite (read while the layer is on) | NASA Global Imagery Browse Services (GIBS): JMA Himawari AHI and NOAA GOES ABI band 13 infrared | NASA open data, free with attribution |
| A place's forecast | Open-Meteo (open-meteo.com), or MET Norway Locationforecast (api.met.no) | CC BY 4.0 (both) |
| Country outlines on the map (`app/web/public/geo/countries.json`) | Natural Earth, 1:50m admin 0 countries | Public domain |
| Bloc membership dates | Entered by hand from the sites linked on each row of `memberships.csv` | n/a |
| Hospitals from OpenStreetMap | © OpenStreetMap contributors, packaged by healthsites.io on the Humanitarian Data Exchange | ODbL 1.0 |
| Hospitals from Overture | Overture Maps Foundation, places theme | CDLA Permissive 2.0 (some places ODbL) |
| Official hospital lists | Brazil Ministry of Health, CNES; Maina J. et al. (2019), "A spatial database of health facilities managed by the public health sector in sub-Saharan Africa", Scientific Data 6:134 | Brazil open government data; CC BY 4.0 |
| Hospital counts | WHO Global Health Observatory (total density of hospitals per 100,000 people); national statistics as named in `contract/worldmodel_contract/health.py` | CC BY-NC-SA 3.0 IGO (WHO) |
| Aircraft type names and map shapes, and which country (and military block) each transponder address belongs to (`app/api/worldmodel_api/aircraft_types.py`) | Virtual Radar Server standing data (github.com/vradarserver/standing-data), model-type and code-blocks | CC0 1.0 |
| Aircraft registrations and types (downloaded on your computer, not in the repository) | The aircraft database tar1090 uses (github.com/wiedehopf/tar1090-db), from Mictronics' aircraft database (mictronics.de) | Free to use, with attribution |
| Airline names by callsign (`app/api/worldmodel_api/airlines.py`) | OpenFlights airline list (openflights.org/data) | ODbL 1.0 |
| Airline logos (fetched on your computer, not in the repository) | github.com/Jxck-S/airline-logos; the logos belong to the airlines and are shown only to identify them | Trademarks of their owners |
