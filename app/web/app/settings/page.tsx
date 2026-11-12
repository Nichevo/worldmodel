"use client";

import Link from "next/link";
import { KINDS, kindVar } from "@/lib/events";
import { Fragment, useEffect, useState } from "react";
import { api, TYPE_TEXT, type AIStatus, type MeasureType, type Settings, type Storage, type Upkeep } from "@/lib/api";
import { useJob } from "@/components/Upkeep";
import { DEFAULT_SETTINGS, saveSettings, useSettings } from "@/lib/settings";
import PlacePicker, { type Place } from "@/components/PlacePicker";
import IndicatorSelect from "@/components/IndicatorSelect";
import type { Indicator } from "@/lib/api";
import { baseMapStatus, type BaseMapEstimate, type BaseMapStatus } from "@/lib/basemap";

// Switches for how the app behaves, and the limits the data side keeps to.
// Saved in the user folder beside the data, so they survive updates.
export default function SettingsPage() {
  const s = useSettings();
  const [msg, setMsg] = useState<string | null>(null);
  const [storage, setStorage] = useState<Storage | null>(null);
  useEffect(() => { api.storage().then(setStorage).catch(() => {}); }, [s.disk_limit_gb, s.pictures_limit_gb]);

  const save = async (patch: Partial<Settings>) => {
    try {
      await saveSettings(patch);
      setMsg("Saved.");
    } catch (e) {
      setMsg(`Not saved: ${(e as Error).message || e}`);
    }
  };
  const gb = (b: number) => `${(b / 1024 ** 3).toFixed(b < 1024 ** 3 ? 2 : 1)} GB`;
  const used = (key: string) => storage?.limits.find((l) => l.key === key);

  return (
    <div className="grid settings">
      <div>
        <h1>Settings</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          Changes save at once. They are kept in your user folder beside the data, so updates never reset them.
          {msg && <span className="muted"> {msg}</span>}
        </p>
      </div>

      <section className="card">
        <h2>Map page</h2>
        <Field label="Clicking a country" hint="On maps, tables, charts and scatter plots.">
          <div className="seg" role="group" aria-label="Clicking a country">
            <button className={s.click_mode === "popup" ? "on" : ""} aria-pressed={s.click_mode === "popup"} onClick={() => save({ click_mode: "popup" })}>
              Opens a popup (shift-click selects)
            </button>
            <button className={s.click_mode === "select" ? "on" : ""} aria-pressed={s.click_mode === "select"} onClick={() => save({ click_mode: "select" })}>
              Selects (double-click opens a popup)
            </button>
          </div>
        </Field>
        <Toggle label="Trend line in the map tooltip" hint="A small line of the last 30 years when you hover a country."
          on={s.hover_sparkline} set={(v) => save({ hover_sparkline: v })} />
        <Toggle label="Indicator tabs in popups" hint="A tab for each indicator the panels show, to flip between them."
          on={s.popup_tabs} set={(v) => save({ popup_tabs: v })} />
        <NumberField label="Ranks panels show the top" unit="countries (0 = all)" value={s.ranks_top_n} min={0} max={300} step={1}
          save={(v) => save({ ranks_top_n: v })} />
        <Toggle label="Side panel (pinboard)" hint="A column beside the panels for cards sent from popups; saved with each layout."
          on={s.side_panel} set={(v) => save({ side_panel: v })} />
        <Toggle label="Flags beside country names" hint="In pickers, headings, tables and cards; groups without a flag get a lettered badge. Off: names only, nothing else changes."
          on={s.flags_on} set={(v) => save({ flags_on: v })} />
      </section>

      <BriefingSettings s={s} save={save} />

      <section className="card" id="quality">
        <h2>Indicator quality</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          Every indicator gets a grade at each refresh: A core, B good, C usable, D exploratory (see the{" "}
          <Link href="/indicators">Indicators</Link> page and Data status, Quality). The drop-downs list only the grades below;
          starred indicators always show, and typing a name finds every indicator.
        </p>
        <Field label="Drop-downs show" hint="Also changeable at the top of any indicator list.">
          <div className="seg" role="group" aria-label="Drop-downs show">
            {([["A", "A only"], ["B", "A and B"], ["C", "Up to C"], ["all", "Everything"], ["starred", "Starred only"]] as const).map(([v, t]) => (
              <button key={v} className={s.quality_show === v ? "on" : ""} aria-pressed={s.quality_show === v} onClick={() => save({ quality_show: v })}>{t}</button>
            ))}
          </div>
        </Field>
        <Field label="Of the type">
          <select value={s.quality_type} onChange={(e) => save({ quality_type: e.target.value as typeof s.quality_type })} aria-label="Measure type">
            <option value="">All types</option>
            {(Object.keys(TYPE_TEXT) as MeasureType[]).map((k) => <option key={k} value={k}>{TYPE_TEXT[k]}</option>)}
          </select>
        </Field>
        <Toggle label="Grade beside chart titles" hint="A small A, B, C or D after each chart's name."
          on={s.quality_on_titles} set={(v) => save({ quality_on_titles: v })} />
      </section>

      <section className="card" id="markets">
        <h2>Markets and storage</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          Exchange rates (ECB and the US Federal Reserve) and Europe&apos;s gas storage (GIE, needs GIE_API_KEY) come day by day; US stocks
          (EIA, needs EIA_API_KEY) week by week; JODI oil and gas stocks month by month. See the <Link href="/storage">Storage</Link> page and
          each country&apos;s Currency card.
        </p>
        <Toggle label="Fetch daily data" hint="Exchange rates and European gas storage at each refresh (a few MB; the first GIE fetch takes about 10 minutes)."
          on={s.markets_daily} set={(v) => save({ markets_daily: v })} />
        <Field label="Storage charts" hint="A year drawn round like a clock (January at the top), or one line per year.">
          <div className="seg" role="group" aria-label="Storage charts">
            {([["clock", "Clock"], ["lines", "Lines"]] as const).map(([v, t]) => (
              <button key={v} className={s.storage_chart === v ? "on" : ""} aria-pressed={s.storage_chart === v} onClick={() => save({ storage_chart: v })}>{t}</button>
            ))}
          </div>
        </Field>
        <NumberField label="Years this year is set against" unit="years" value={s.storage_years} min={2} max={15} step={1}
          save={(v) => save({ storage_years: v })} />
        <p className="small muted">Currency card partners: {Object.keys(s.fx_partners ?? {}).length
          ? <>chosen for {Object.keys(s.fx_partners).join(", ")}. <button className="link" onClick={() => save({ fx_partners: {} })}>Back to top trading partners everywhere</button></>
          : "each country's top trading partners (change them on its Currency card)."}</p>
      </section>

      <DiscoverSettings s={s} save={save} />

      <section className="card">
        <h2>Forecasts</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          The Forecast button on charts extends each line with a statistical forecast: the simple model that would have
          missed least over the past years, with ranges from how far it missed.
        </p>
        <NumberField label="Look ahead" unit="years" value={s.forecast_horizon} min={1} max={50} step={1}
          save={(v) => save({ forecast_horizon: v })} />
        <Field label="Ranges around a forecast" hint="The band a forecast fell inside 80% (or 95%) of the time in the back-test.">
          <div className="seg" role="group" aria-label="Ranges around a forecast">
            {([["80+95", "80% and 95%"], ["80", "80% only"], ["none", "None"]] as const).map(([v, label]) => (
              <button key={v} className={s.forecast_ranges === v ? "on" : ""} aria-pressed={s.forecast_ranges === v}
                onClick={() => save({ forecast_ranges: v })}>{label}</button>
            ))}
          </div>
        </Field>
        <Toggle label="Forecasters' own projections" hint="With Forecast on, single-country charts also draw the IMF's, OECD's and World Bank's latest forecasts."
          on={s.forecast_official} set={(v) => save({ forecast_official: v })} />
      </section>

      <AISettings s={s} save={save} />

      <section className="card">
        <h2>Storage limits</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          Warnings show at 80% and 95% on the <Link href="/data">Data status</Link> page, in the refresh report and as a banner.
          Nothing is ever deleted on its own; at 100% a refresh skips large downloads until you free space or raise the limit.
        </p>
        <NumberField label="Whole data folder" unit="GB" value={s.disk_limit_gb} min={1} max={10000} step={1}
          note={used("disk") ? `${gb(used("disk")!.used)} used now` : undefined} save={(v) => save({ disk_limit_gb: v })} />
        <NumberField label="Pictures and cached pages" unit="GB" value={s.pictures_limit_gb} min={0.1} max={1000} step={0.5}
          note={used("pictures") ? `${gb(used("pictures")!.used)} used now` : undefined} save={(v) => save({ pictures_limit_gb: v })} />
        <NumberField label="Map files" unit="GB" value={s.basemap_limit_gb} min={0.1} max={5000} step={1}
          note={used("basemap") ? `${gb(used("basemap")!.used)} used now` : undefined} save={(v) => save({ basemap_limit_gb: v })} />
        <Toggle label="Banner while a refresh problem is open"
          hint="Shows the latest failed check or download at the top of every page, with how often it has happened, until a later refresh passes. The Problems list on Data status is always there."
          on={s.problem_banner} set={(v) => save({ problem_banner: v })} />
      </section>

      <LookingAfter s={s} save={save} />

      <section className="card" id="api-access">
        <h2>API access</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          The data for your own scripts, the Python client, Excel and AI assistants (MCP), at <code>/api/public/v1</code>. Only this PC and
          your home network can reach it; nothing is opened to the internet. <Link href="/api-access">Keys, examples and the log of calls</Link>
        </p>
        <Toggle label="Public API"
          hint="Off: scripts, the Python client, the MCP server and Copy API link get a message saying it is switched off. The app's own pages are not affected. From this PC no key is needed; other PCs need a key made on the API page."
          on={s.api_public_on} set={(v) => save({ api_public_on: v })} />
        <NumberField label="Calls a day for each key" unit="calls" value={s.api_daily_limit} min={10} max={1000000} step={100}
          save={(v) => save({ api_daily_limit: v })} />
      </section>

      <MapDetail s={s} save={save} />
      <MapPictures s={s} save={save} />

      <section className="card">
        <h2>Places</h2>
        <Toggle label="Metro and rail, universities, big companies, hospitals and military bases" hint="Eight Wikidata queries every four weeks during .\refresh.bat. They fill the Transport, universities and companies card on country and city pages and six map layers. Switching off keeps what is stored."
          on={s.places_fetch} set={(v) => save({ places_fetch: v })} />
        <NumberField label="Hospitals on the map: at least" unit="beds" value={s.map_hospital_beds} min={0} max={10000} step={50}
          note="The Hospitals layer shows hospitals this size or bigger. 0 shows every hospital with a bed count. Takes effect at once."
          save={(v) => save({ map_hospital_beds: v })} />
        <Toggle label="Also show well-known hospitals with no bed count" hint="Wikidata gives beds for only some hospitals. This adds the ones with articles in three or more Wikipedias but no bed count, so the map is fuller but no longer only the big ones."
          on={s.map_hospitals_unsized} set={(v) => save({ map_hospitals_unsized: v })} />
      </section>

      <section className="card" id="long-history">
        <h2>Long history</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          The <a href="/long">Long history</a> page, the Map&apos;s &quot;World in year&quot; layer and each country&apos;s Long view card.
          Switching a source off keeps what is stored; the views then show what was last loaded.
        </p>
        <Toggle label="Borders of states and empires (Cliopatria)" hint="One 46 MB download from GitHub, checked twice a year during .\refresh.bat, stored at about 15 MB. Off: no new borders; age of empires, who ruled where, empire maps and World in year keep the last ones (or stay empty)."
          on={s.history_borders_fetch} set={(v) => save({ history_borders_fetch: v })} />
        <Toggle label="Long-run figures (population since 10,000 BC, Maddison GDP, literacy...)" hint="Nine chart files from Our World in Data every three months. Off: the long charts, reach back, then and now and the eight factors keep the last figures."
          on={s.history_series_fetch} set={(v) => save({ history_series_fetch: v })} />
        <Toggle label="Events far back (Wikidata) and NOAA's earthquakes, eruptions and tsunamis" hint="Seven Wikidata queries a month and about 50 small NOAA pages every three months. Off: the events on long charts and empire cards keep the last ones."
          on={s.history_events_fetch} set={(v) => save({ history_events_fetch: v })} />
        <NumberField label="Events shown: articles in at least" unit="Wikipedias" value={s.history_event_min_links} min={5} max={200} step={5}
          note="Higher shows only the best-known wars, battles, plagues and treaties. NOAA's hazards have no article count and always show. Takes effect at once."
          save={(v) => save({ history_event_min_links: v })} />
        <Toggle label="Events as marks on the long charts" hint="Plagues, famines, wars and big disasters as marks on People since 10,000 BC. Off: the line only."
          on={s.history_events_on_charts} set={(v) => save({ history_events_on_charts: v })} />
        <NumberField label="Wikipedia pages for empires, dynasties and voyages per day" unit="pages" value={s.wikipedia_empires_daily} min={0} max={500} step={5}
          note="A page is read when its card is first opened and kept for a month. 0 stops new reads (stored pages still show)."
          save={(v) => save({ wikipedia_empires_daily: v })} />
      </section>

      <section className="card" id="relationships">
        <h2>Relationship scan</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          After each refresh the scan tests pairs of figures for moving together, which comes first, and whether the link
          holds after allowing for income and time. Results are on the <a href="/relationships">Relationships</a> page.
          Changes here take effect at the next refresh (or run <code>worldmodel-data scan</code>).
        </p>
        <Toggle label="Look for relationships after each refresh" hint="About two minutes with the indicators switched on. Switching off keeps the last scan."
          on={s.relations_scan} set={(v) => save({ relations_scan: v })} />
        <Toggle label="Only when there are new figures" hint="Skips the scan when no figure or event it reads has changed since the last scan, and the scan settings are the same. Run worldmodel-data scan --force to scan anyway."
          on={s.relations_only_new} set={(v) => save({ relations_only_new: v })} />
        <Field label="Indicators scanned" hint="Every indicator means about 1,400 and some million pairs: hours of work, so raise the time limit and leave it overnight.">
          <div className="seg" role="group" aria-label="Indicators scanned">
            {([["on", "Those switched on (about 7,000 pairs)"], ["all", "Every indicator (overnight)"]] as const).map(([v, label]) => (
              <button key={v} className={s.relations_indicators === v ? "on" : ""} aria-pressed={s.relations_indicators === v}
                onClick={() => save({ relations_indicators: v })}>{label}</button>
            ))}
          </div>
        </Field>
        <NumberField label="Countries a pair needs" value={s.relations_min_countries} min={5} max={200} step={1}
          save={(v) => save({ relations_min_countries: v })} />
        <NumberField label="Years of data per country" value={s.relations_min_years} min={5} max={60} step={1}
          save={(v) => save({ relations_min_years: v })} />
        <NumberField label="Time limit" unit="minutes" value={s.relations_max_minutes} min={1} max={1440} step={1}
          note="The scan stops here and keeps what it has done."
          save={(v) => save({ relations_max_minutes: v })} />
        <NumberField label="Chance finds allowed" unit="share" value={s.relations_fdr} min={0.001} max={0.25} step={0.01}
          note="The false discovery rate: 0.05 means about 1 in 20 reported links may be chance. Lower is stricter."
          save={(v) => save({ relations_fdr: v })} />
      </section>

      <section className="card" id="sectors">
        <h2>Sectors</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          The <a href="/sectors">Sectors</a> page follows one industry across the globe: who mines or grows it, who
          processes it, where it is shipped and what it sells for. Trade comes from CEPII BACI, one large download.
        </p>
        <Toggle label="Download trade by product (BACI)" hint="About 2 GB, checked every four months during .\refresh.bat; only the years you keep are stored (about 1 GB in the warehouse from 2005). Switching off keeps what is stored."
          on={s.sectors_trade_fetch} set={(v) => save({ sectors_trade_fetch: v })} />
        <NumberField label="Trade kept from" unit="year" value={s.sectors_trade_from} min={1995} max={2030} step={1}
          note="BACI starts in 1995. Earlier years make the warehouse bigger; the change shows at the next refresh."
          save={(v) => save({ sectors_trade_from: v })} />
      </section>

      <section className="card" id="internet">
        <h2>Internet speeds</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          Speeds come from Ookla&apos;s open Speedtest files, one for fixed broadband and one for mobile each quarter since 2019.
          Each is 200 to 400 MB; it is read, summed by country and deleted, so only a few kilobytes are kept.
        </p>
        <Toggle label="Download internet speeds (Ookla)" hint="Read every four weeks during .\refresh.bat, newest quarters first. Switching off keeps what is stored."
          on={s.internet_speeds_fetch} set={(v) => save({ internet_speeds_fetch: v })} />
        <NumberField label="Speeds kept from" unit="year" value={s.internet_speeds_from} min={2019} max={2030} step={1}
          note="Ookla's open data starts in 2019. Older quarters are read at later refreshes."
          save={(v) => save({ internet_speeds_from: v })} />
        <NumberField label="Files read in one refresh" value={s.internet_speeds_per_refresh} min={1} max={60} step={1}
          note="All of 2019 to now is about 55 files (about 15 GB to download once). 8 a refresh is about 2.5 GB."
          save={(v) => save({ internet_speeds_per_refresh: v })} />
      </section>

      <section className="card" id="climate">
        <h2>Climate</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          The <a href="/climate">Climate</a> page and the Climate section on country pages. Most sources are small files read at each refresh.
        </p>
        <Toggle label="Download climate data" hint="Our World in Data emissions and climate charts, NOAA gases and El Niño, NASA temperatures, storm tracks (about 30 MB), disaster alerts and the World Bank projections. Switching off keeps what is stored."
          on={s.climate_fetch} set={(v) => save({ climate_fetch: v })} />
        <NumberField label="Storm tracks kept from" unit="year" value={s.climate_storms_from} min={1980} max={2030} step={1}
          note="Earlier years make the map slower. The change shows at the next refresh."
          save={(v) => save({ climate_storms_from: v })} />
        <Toggle label="Live disaster alerts on the Storms tab" hint="Reads the alerts out now from GDACS when the tab opens, at most every 15 minutes."
          on={s.climate_live_map} set={(v) => save({ climate_live_map: v })} />
      </section>

      <section className="card" id="nature">
        <h2>Nature and pollution</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          The <a href="/climate?tab=zones">Climate zones</a> and <a href="/climate?tab=nature">Nature</a> tabs, the <a href="/pollution">Pollution</a> page and the
          Climate zones, Pollution and Nature cards on country pages. Switching a source off keeps what is stored; the pages then show what was last loaded.
          Air pollution deaths, ocean plastic, wildlife and threatened species charts come with Our World in Data and the World Bank (Climate and the main refresh).
        </p>
        <Toggle label="Climate zones (Köppen-Geiger, Beck et al. 2023)" hint="One download of about 1 GB from figshare, read once and cut to about 20 MB of 0.1° grids. Off before the first read: no zones map, no country zone breakdown and no city twins."
          on={s.nature_zones_fetch} set={(v) => save({ nature_zones_fetch: v })} />
        <label className="small" style={{ display: "block", margin: "6px 0 10px" }}>Emissions path for future climate zones and city twins{" "}
          <select value={s.zones_scenario} onChange={(e) => save({ zones_scenario: e.target.value })} aria-label="Emissions path">
            <option value="ssp126">Low emissions (SSP1-2.6)</option><option value="ssp245">Middle (SSP2-4.5)</option><option value="ssp585">Very high (SSP5-8.5)</option>
          </select> <span className="muted">Each card can switch path too; this is where they start.</span></label>
        <Toggle label="Berkeley Earth temperatures, PSMSL tide gauges and ND-GAIN" hint="About 200 small country files every three months, one 1 MB zip and one small zip twice a year. Off: no Berkeley Earth temperature series beside NASA's, no tide gauge map layer, no adaptation readiness scores."
          on={s.nature_climate_extras_fetch} set={(v) => save({ nature_climate_extras_fetch: v })} />
        <Toggle label="UN SDG water and protected nature areas" hint="Seven series from the UN SDG database every three months. Off: no treated wastewater, water quality, water stress, Red List Index (UN) or key nature areas protected."
          on={s.nature_pollution_fetch} set={(v) => save({ nature_pollution_fetch: v })} />
        <Toggle label="Invasive species, IUCN Red List and EPPO pests" hint="About 200 small GBIF requests twice a year; IUCN (twice a year) and EPPO (every three months) only once their free keys are in .env. Off: no introduced species counts, no named threatened species, no watched pests by country."
          on={s.nature_species_fetch} set={(v) => save({ nature_species_fetch: v })} />
        <Toggle label="Protected areas (World Database on Protected Areas)" hint="About 900 MB twice a year, deleted once the areas of 10 km² or more (and every area in New Zealand) are taken out, about 150 MB kept. Off: no protected areas map on the Recovering view."
          on={s.nature_protected_fetch} set={(v) => save({ nature_protected_fetch: v })} />
      </section>

      <section className="card" id="transport">
        <h2>Transport, tourism and networks</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          Ports, chokepoints, airports, rivers, waterways, undersea cables and pipelines for the Transport page, the map&apos;s Transport and trade layers and the
          country cards. Air, rail, port and tourism figures from the World Bank come with the main refresh whatever these say. Switching off keeps what is stored.
        </p>
        <Toggle label="Ports, chokepoints and shipping lanes" hint="IMF PortWatch weekly (ports, chokepoints, ships a day since 2019, port calls a month), the World Port Index twice a year and the shipping lanes once a year. Off: no chokepoint charts or events, no port layers or port calls by country."
          on={s.transport_ports_fetch} set={(v) => save({ transport_ports_fetch: v })} />
        <Toggle label="Airports and airport traffic" hint="OurAirports (one 12 MB file every three months) and Eurostat passengers and freight by airport. Off: no airports layer and no busiest airports; files you save by hand still load."
          on={s.transport_air_fetch} set={(v) => save({ transport_air_fetch: v })} />
        <Toggle label="Inland waterways and river freight" hint="The US National Waterway Network and OpenStreetMap (Europe's classed waterways and about 30 big rivers, one query at a time, ten seconds apart, once a year), and Eurostat river freight. Off: no waterways layer and no river freight figures."
          on={s.transport_waterways_fetch} set={(v) => save({ transport_waterways_fetch: v })} />
        <Toggle label="Rivers and river basins (HydroSHEDS)" hint="About 700 MB downloaded once (nine regions), cut to rivers of 10 m³/s and up and whole basins, about 100 MB kept. Off before the first read: no rivers or basins layers and no basins on country cards."
          on={s.rivers_fetch} set={(v) => save({ rivers_fetch: v })} />
        <Toggle label="Undersea cables (TeleGeography)" hint="The cable map monthly, and each cable's owners and landing countries read once, 150 at a time, two seconds apart. Off: no cables layer and no cables on country cards."
          on={s.cables_fetch} set={(v) => save({ cables_fetch: v })} />
        <Toggle label="Pipelines and LNG terminals (Global Energy Monitor)" hint="Read from the files you save in var\manual\gem_infrastructure (see Data status). Off: those files are not read again."
          on={s.energy_infrastructure_fetch} set={(v) => save({ energy_infrastructure_fetch: v })} />
        <Toggle label="UNESCO World Heritage sites" hint="One XML list twice a year. Off: no heritage sites layer or counts."
          on={s.tourism_fetch} set={(v) => save({ tourism_fetch: v })} />
        <NumberField label="Air, sea and rail accidents from" unit="deaths" value={s.transport_min_deaths} min={0} max={100000} step={1}
          note="Smaller accidents stay off the charts, the Events page and the Transport page (they are still stored). Wikidata gives those of 5 deaths or more."
          save={(v) => save({ transport_min_deaths: v })} />
        <Toggle label="Planes now (map layer)" hint="While the map's Planes now layer is on, the server asks OpenSky Network for the planes in the area in view, at most once a minute (400 requests a day without an account, more with an API client in .env). Off: the layer stays empty."
          on={s.live_planes} set={(v) => save({ live_planes: v })} />
        <Toggle label="Ships now (map layer)" hint="While the map's Ships now layer is on, the server listens to aisstream.io for ships in the area in view (needs a free AISSTREAM_API_KEY in .env); it stops five minutes after the layer is turned off. Off: the layer stays empty."
          on={s.live_ships} set={(v) => save({ live_ships: v })} />
      </section>

      <section className="card" id="land">
        <h2>Land, cities and trees</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          The Land page, the land cards on sector and city pages and the map&apos;s city outline, street tree and New Zealand land change layers.
          Farm and forest land from FAOSTAT comes with the sectors refresh whatever these say. Switching off keeps what is stored.
        </p>
        <Toggle label="Land use back to 1700 (HYDE)" hint="Two small chart files from Our World in Data every six months. Off: the land use charts start in 1961 (FAOSTAT)."
          on={s.land_history_fetch} set={(v) => save({ land_history_fetch: v })} />
        <Toggle label="City outlines (GHSL urban centres)" hint="One download of about 60 MB a year. Off: no city outlines layer, no city size comparison and no built-up area on city pages."
          on={s.land_cities_fetch} set={(v) => save({ land_cities_fetch: v })} />
        <Toggle label="Tree cover and street trees" hint="Global Forest Watch's country file once a year, and Auckland Council's tree list (pages of 2,000, a second apart, twice a year). Off: no tree cover loss charts and no street trees layer."
          on={s.land_trees_fetch} set={(v) => save({ land_trees_fetch: v })} />
        <Toggle label="New Zealand land cover and forestry files" hint="Reads the LCDB and MPI forestry files you save in var\manual\nz_lcdb and var\manual\nz_forestry (see Data status). Off: those files are not read again."
          on={s.land_nz_fetch} set={(v) => save({ land_nz_fetch: v })} />
        <Toggle label="Work out land cover inside cities" hint="When you ask on the Land page or a city page, reads the WorldCover pictures inside the city's outline (a few MB each, in the background) and keeps the result. Off: no tree, built and green shares for cities."
          on={s.land_city_cover} set={(v) => save({ land_city_cover: v })} />
        <label className="small" style={{ display: "block", margin: "6px 0 10px" }}>Land cover picture of{" "}
          <select value={s.land_cover_year} onChange={(e) => save({ land_cover_year: e.target.value as Settings["land_cover_year"] })} aria-label="Land cover year">
            <option value="2021">2021</option><option value="2020">2020</option>
          </select> <span className="muted">ESA WorldCover at 10 m; the map&apos;s Land cover look and city shares use it.</span></label>
      </section>

      <section className="card" id="predictions">
        <h2>Predictions and crowd forecasts</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          The <Link href="/predictions">Predictions</Link> and <Link href="/crowd">Crowd forecasts</Link> pages, the country cards and the Briefing&apos;s crowd and watchlist cards.
          Your own log stays on this PC (var\user\predictions.json) whatever these say. Switching a site off keeps what is stored.
        </p>
        <Toggle label="Polymarket" hint="Reads the questions in the categories below and their prices at each refresh (a few pages; no account). Off: no new Polymarket questions or chances."
          on={s.crowd_polymarket} set={(v) => save({ crowd_polymarket: v })} />
        <Toggle label="Metaculus" hint="Reads questions and the community forecast. Needs a free token (METACULUS_TOKEN in .env; Settings > Keys). Off: no new Metaculus questions, comments or your own Metaculus forecasts."
          on={s.crowd_metaculus} set={(v) => save({ crowd_metaculus: v })} />
        <Toggle label="Manifold" hint="Reads questions and chances (play money; no account). Off: no new Manifold questions."
          on={s.crowd_manifold} set={(v) => save({ crowd_manifold: v })} />
        <Toggle label="Metaculus comments" hint="Reads the comments on questions you follow and the 30 most discussed. Off: the Comments box on question pages stays as it was."
          on={s.crowd_comments} set={(v) => save({ crowd_comments: v })} />
        <Toggle label="Your own Metaculus forecasts" hint="Reads your forecasts (and a bot's, with METACULUS_BOT_TOKEN) so the scorecard can score them beside the crowd. Off: they leave the scorecard after the next refresh."
          on={s.crowd_mine} set={(v) => save({ crowd_mine: v })} />
        <Field label="Categories read" hint="Questions in other categories are not read. Sport, crypto and entertainment are always left out.">
          <div>{(["politics", "economics", "geopolitics", "climate", "science"] as const).map((c) => {
            const on = s.crowd_categories.split(",").includes(c);
            return (<label key={c} style={{ display: "block" }}><input type="checkbox" checked={on} onChange={(e) => save({ crowd_categories:
              [...s.crowd_categories.split(",").filter((x) => x && x !== c), ...(e.target.checked ? [c] : [])].join(",") })} /> {c[0].toUpperCase() + c.slice(1)}</label>);
          })}</div>
        </Field>
        <Toggle label="ViEWS conflict forecasts" hint="Monthly predicted deaths in state-based conflict for every country (Uppsala and PRIO), read about once a month. Off: no Conflict forecasts tab or country line."
          on={s.views_fetch} set={(v) => save({ views_fetch: v })} />
        <NumberField label="A big move" unit="points in a week" value={s.crowd_move_points} min={1} max={50} step={1}
          note="A crowd chance moving this much counts as news on the Briefing and as a watchlist alert." save={(v) => save({ crowd_move_points: v })} />
        <NumberField label="Score crowd sites" unit="days before closing" value={s.crowd_score_days} min={0} max={365} step={1}
          note="The scorecard uses each site's chance this long before a question closed, so last-minute certainty does not count. 0 = the last chance saved." save={(v) => save({ crowd_score_days: v })} />
        <Toggle label="Predictions on charts" hint="Your number predictions show as diamonds on charts of their indicator and country. Off: the charts show none (the log keeps them)."
          on={s.predictions_on_charts} set={(v) => save({ predictions_on_charts: v })} />
        <Toggle label="Watchlist alerts on the Briefing" hint="Off: the watchlist still works on the Predictions page, but nothing shows on the Briefing."
          on={s.watchlist_on} set={(v) => save({ watchlist_on: v })} />
      </section>

      <section className="card" id="world">
        <h2>The world beyond borders, laws and holidays</h2>
        <Toggle label="CrisisWatch monthly conflict ratings" hint="International Crisis Group's page for each month, read one at a time a few seconds apart. Each refresh reads the latest two months again and fills in older ones back to August 2003. Switching off keeps what is stored."
          on={s.crisiswatch_fetch} set={(v) => save({ crisiswatch_fetch: v })} />
        <Toggle label="Public holidays" hint="Nager.Date's holiday list for about 120 countries, this year and next, read every 90 days (small requests, a moment apart). Fills the holidays calendar on country pages. Switching off keeps what is stored."
          on={s.holidays_fetch} set={(v) => save({ holidays_fetch: v })} />
        <NumberField label="Older CrisisWatch months per refresh" value={s.crisiswatch_backfill} min={0} max={300} step={1}
          save={(v) => save({ crisiswatch_backfill: v })} />
        <NumberField label="Gap between web pages" unit="seconds" value={s.scrape_gap_seconds} min={2} max={120} step={1}
          note="For every source read from web pages (CrisisWatch, UN vetoes, WTO, treaties, Corrections, Electoral Commission, scrape.bat). Doubled on runs of more than 5 pages and tripled past 20, with a longer rest every 10 pages. A run stops at the first refused or odd page; Data status says why."
          save={(v) => save({ scrape_gap_seconds: v })} />
        <TextField label="UN voting compared with" value={s.voting_compare} placeholder="USA,CHN,RUS,eu"
          note="Country codes or group ids, comma-separated. A group (eu, nato, oecd, asean) shows the average over its members of each year. Used on every country's UN voting card."
          save={(v) => save({ voting_compare: v })} />
        <h3>WORLD Policy tables from Harvard Dataverse</h3>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          WORLD&apos;s datasets (paid leave, minimum wage, working hours, schooling, constitutions and more) ask each downloader to fill in
          a short guestbook. Fill it in once here and <code>.\refresh.bat</code> downloads the data files itself, every 90 days, a few
          seconds apart. The answers go to Dataverse with each download and are kept on this PC only. Left blank, WORLD stays a source
          you download yourself.
        </p>
        <Toggle label="Download WORLD Policy tables" hint="Switching off keeps what is stored; files you save by hand still load."
          on={s.world_dataverse_fetch} set={(v) => save({ world_dataverse_fetch: v })} />
        <TextField label="Your name" value={s.world_dataverse_name} save={(v) => save({ world_dataverse_name: v })} />
        <TextField label="Email" value={s.world_dataverse_email} save={(v) => save({ world_dataverse_email: v })} />
        <TextField label="Organisation" value={s.world_dataverse_institution} placeholder="(none)" save={(v) => save({ world_dataverse_institution: v })} />
        <TextField label="Position" value={s.world_dataverse_position} placeholder="(none)" save={(v) => save({ world_dataverse_position: v })} />
        <TextField label="Purpose" value={s.world_dataverse_purpose} note="Also the answer to any extra question a dataset's guestbook asks."
          save={(v) => save({ world_dataverse_purpose: v })} />
        <TextField label="Only these datasets" value={s.world_dataverse_datasets} placeholder="(blank: every dataset with a data file)"
          note="Words from dataset titles (leave, wage, education) or DOIs, comma-separated."
          save={(v) => save({ world_dataverse_datasets: v })} />
      </section>

      <section className="card">
        <h2>Country packs</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          Extra sources for one country, fetched by <code>.\refresh.bat</code> while switched on. Switching one off keeps
          what is stored.
        </p>
        <Toggle label="New Zealand" hint="Reserve Bank interest and exchange rates, MBIE energy balances, Electoral Commission results and turnout, and justice statistics."
          on={s.pack_nz} set={(v) => save({ pack_nz: v })} />
      </section>

      <section className="card">
        <h2>Daily limits for single-page fetches</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          These sites are never read in bulk. A fetch happens only when you ask for one country (or city), one page at a time,
          and stops at these daily totals. Countries you open most go first. Wikipedia is read through its official API: a country
          page fetches its introduction and pictures when you open it, and keeps them for a month. (The Numbeo button and city pages
          arrive with the city data.)
        </p>
        <NumberField label="Numbeo pages per day, all countries together" value={s.numbeo_daily} min={0} max={200} step={1}
          save={(v) => save({ numbeo_daily: v })} />
        <NumberField label="Wikipedia country pages per day" value={s.wikipedia_countries_daily} min={0} max={500} step={1}
          save={(v) => save({ wikipedia_countries_daily: v })} />
        <NumberField label="Wikipedia city pages per day" value={s.wikipedia_cities_daily} min={0} max={500} step={1}
          save={(v) => save({ wikipedia_cities_daily: v })} />
        <Toggle label="Fetch Wikipedia pages in the background"
          hint="Fills in countries you have not opened yet, a few an hour, most-populous first, using at most half of the daily Wikipedia limit so the pages you open always have room."
          on={s.wikipedia_background} set={(v) => save({ wikipedia_background: v })} />
      </section>

      <section className="card" id="look">
        <h2>Look of charts</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          How charts across the app show their figures. New Zealand, Australia, the UK, the US, the world and the main groups always
          keep the same colour on every chart, and continents keep theirs on every map.
        </p>
        <Toggle label="Name lines at their ends"
          hint="Each line ends with its name and latest value. Off brings back the legend at the top (charts with more than 12 lines always use it)."
          on={s.chart_end_labels} set={(v) => save({ chart_end_labels: v })} />
        <Toggle label="Write values on bars"
          hint="Every bar when there are up to 24, else the latest, highest and lowest. Off leaves the numbers to the tooltip."
          on={s.chart_values} set={(v) => save({ chart_values: v })} />
        <Toggle label="Say the finding in chart titles"
          hint="A line such as “1.56 in 2023, the lowest since records began in 1960” above each chart, worked out from its figures. Off shows only the measure's name."
          on={s.chart_findings} set={(v) => save({ chart_findings: v })} />
        <Toggle label="Name event bands on the chart"
          hint="Recession and crisis bands carry a short name standing up their left edge (when a chart has 10 or fewer). Off leaves names to hovering."
          on={s.event_labels} set={(v) => save({ event_labels: v })} />
      </section>

      <section className="card" id="events">
        <h2>Events on charts</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          Dated events show as shaded bands (anything that lasts) and dotted lines (a single day) on the line charts of a country page
          and on map-page charts of up to three countries. Hover one for its name. All events are listed on each country&apos;s
          timeline and on the <Link href="/events">Events</Link> page whatever is ticked here.
        </p>
        <Toggle label="Show events on charts" on={s.events_on_charts} set={(v) => save({ events_on_charts: v })} />
        <Toggle label="Show projected years on charts (dashed lines, such as the UN's population projections)" on={s.projections_on_charts} set={(v) => save({ projections_on_charts: v })} />
        <Field label="Kinds shown" hint="Leaders' terms and elections are left off by default: with them, every chart is striped.">
          <div className="chips-row">
            {KINDS.map((k) => {
              const on = s.event_kinds.split(",").includes(k.kind);
              const next = (on ? s.event_kinds.split(",").filter((x) => x !== k.kind) : [...s.event_kinds.split(","), k.kind]).filter(Boolean).join(",");
              return (
                <button key={k.kind} className={`chip kind ${on ? "" : "off"}`} aria-pressed={on} style={{ borderColor: kindVar(k.kind) }}
                  onClick={() => save({ event_kinds: next })}>
                  <i style={{ background: kindVar(k.kind) }} />{k.label}
                </button>
              );
            })}
          </div>
        </Field>
        <NumberField label="Disasters and epidemics from" unit="deaths" value={s.disaster_min_deaths} min={0} max={1000000} step={10}
          save={(v) => save({ disaster_min_deaths: v })} />
      </section>

      <section className="card" id="parties">
        <h2>Governing party</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          A one-country line chart can be coloured by the party in government: the line and the area under it in the party&apos;s
          colour, with each leader&apos;s name where their term starts. Switch it on for a map-page chart with its
          &ldquo;Governing party&rdquo; box. Leaders, parties and colours come from Wikidata.
        </p>
        <Toggle label="Colour country page charts by governing party" on={s.party_colours} set={(v) => save({ party_colours: v })} />
        <Field label="Whose party" hint="A prime minister's party for parliamentary countries; a president's where the president governs.">
          <div className="seg">
            <button className={s.party_office === "government" ? "on" : ""} aria-pressed={s.party_office === "government"}
              onClick={() => save({ party_office: "government" })}>Head of government</button>
            <button className={s.party_office === "state" ? "on" : ""} aria-pressed={s.party_office === "state"}
              onClick={() => save({ party_office: "state" })}>Head of state</button>
          </div>
        </Field>
      </section>

      <section className="card">
        <h2>History</h2>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          A private log of what you open, kept only on this computer. See it on the <Link href="/history">History</Link> page.
        </p>
        <Toggle label="Pause history" hint="Nothing new is logged while paused." on={s.history_paused} set={(v) => save({ history_paused: v })} />
        <Field label="Keep history for" hint="Older entries are dropped as new ones come in; starred entries are always kept.">
          <select value={s.history_retention_days} onChange={(e) => save({ history_retention_days: +e.target.value })}>
            <option value={0}>Forever</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={365}>1 year</option>
            <option value={1825}>5 years</option>
          </select>
        </Field>
        <Field label="Clear history" hint="Starred entries are kept unless you tick the box.">
          <ClearHistory />
        </Field>
      </section>

      <Libraries />

      <p className="small">
        <button className="link" onClick={() => window.confirm("Put every setting back to its default?") && save(DEFAULT_SETTINGS)}>
          Reset all settings to defaults
        </button>
      </p>
    </div>
  );
}

// Local AI: where Ollama is, which model, and web search with its limits.
function AISettings({ s, save }: { s: Settings; save: (patch: Partial<Settings>) => void }) {
  const [status, setStatus] = useState<AIStatus | null>(null);
  useEffect(() => { api.aiStatus().then(setStatus).catch(() => setStatus(null)); }, [s.ollama_url, s.ai_search_engine, s.searxng_url]);
  const names = status?.models.map((m) => m.name) ?? [];
  const sees = new Set(status?.models.filter((m) => m.vision).map((m) => m.name) ?? []);
  const tag = (n: string) => (sees.has(n) ? `${n} (sees pictures)` : n);
  const parts = s.ai_context_default.split(",").filter(Boolean);
  const u = status?.search.usage;
  return (
    <section className="card" id="ai">
      <h2>Local AI</h2>
      <p className="small ink-2" style={{ marginTop: 0 }}>
        Ask AI sends a question, with what is on screen, to a model in Ollama on this PC (or another on your network). The
        app&apos;s server talks to Ollama, so asking from another PC works too. Answers are kept on the <Link href="/ai">AI notes</Link> page.
      </p>
      <Toggle label="Local AI" hint="Ask AI buttons, the AI notes page, and Ask AI in the highlight menu." on={s.ai_enabled} set={(v) => save({ ai_enabled: v })} />
      <TextField label="Ollama address" value={s.ollama_url} placeholder="http://localhost:11434"
        note={status ? (status.ollama.ok ? `Connected${status.ollama.version ? `, Ollama ${status.ollama.version}` : ""}; ${names.length} model${names.length === 1 ? "" : "s"} installed${names.length ? (sees.size ? `; ${sees.size} can see pictures (charts are sent to them as pictures as well as numbers): ${[...sees].join(", ")}` : "; none can see pictures, so charts go as numbers only") : ""}.` : status.ollama.error ?? "Not reachable.") : "Checking…"}
        save={(v) => save({ ollama_url: v })} />
      <Field label="Default model" hint={names.length ? "Largest first. Pull more with: ollama pull <name>" : "No models found yet."}>
        <select value={s.ai_model} onChange={(e) => save({ ai_model: e.target.value })} aria-label="Default model">
          <option value="">First installed{names[0] ? ` (${names[0]})` : ""}</option>
          {names.map((n) => <option key={n} value={n}>{tag(n)}</option>)}
          {s.ai_model && !names.includes(s.ai_model) && <option value={s.ai_model}>{s.ai_model} (not installed)</option>}
        </select>
      </Field>
      <Field label="Model to compare with" hint="Offered by “Compare with a second model” in the Ask AI box, which puts its answer beside the first.">
        <select value={s.ai_model_compare} onChange={(e) => save({ ai_model_compare: e.target.value })} aria-label="Second model">
          <option value="">Choose each time</option>
          {names.map((n) => <option key={n} value={n}>{tag(n)}</option>)}
        </select>
      </Field>
      <Toggle label="Side by side from the start" hint="Off: each question goes to one model, and you add the second in the box when you want it."
        on={s.ai_compare_default} set={(v) => save({ ai_compare_default: v })} />
      <NumberField label="Temperature" value={s.ai_temperature} min={0} max={2} step={0.1}
        note="0 keeps answers steady and literal; higher is more varied." save={(v) => save({ ai_temperature: v })} />
      <NumberField label="Context length" unit="tokens" value={s.ai_context_tokens} min={1024} max={1048576} step={1024}
        note="How much text the model reads at once (Ollama num_ctx). Long tables need more; more uses more graphics memory." save={(v) => save({ ai_context_tokens: v })} />
      <Field label="Ticked by default" hint="What goes with a question unless you untick it.">
        <div className="chips-row">
          {([["data", "Chart data"], ["description", "Descriptions"], ["events", "Events"], ["highlight", "Highlighted text"]] as const).map(([k, label]) => {
            const on = parts.includes(k);
            return <button key={k} className={`chip${on ? " on" : ""}`} aria-pressed={on}
              onClick={() => save({ ai_context_default: (on ? parts.filter((x) => x !== k) : [...parts, k]).join(",") })}>{label}</button>;
          })}
        </div>
      </Field>
      <Toggle label="Menu when you select text" hint="Select text on a page to Ask AI about it or Save highlight." on={s.highlight_menu} set={(v) => save({ highlight_menu: v })} />

      <h3>Web search</h3>
      <Field label="Search engine" hint="Used when you tick Search the web on a question.">
        <div className="seg" role="group" aria-label="Search engine">
          {([["brave", "Brave"], ["searxng", "SearXNG (free)"], ["off", "Off"]] as const).map(([v, label]) => (
            <button key={v} className={s.ai_search_engine === v ? "on" : ""} aria-pressed={s.ai_search_engine === v}
              onClick={() => save({ ai_search_engine: v })}>{label}</button>
          ))}
        </div>
      </Field>
      {status && !status.search.ready && status.search.why && <p className="small error">{status.search.why}</p>}
      {s.ai_search_engine === "brave" && (
        <>
          <p className="small"><b>Brave can cost money.</b> Its $5 monthly credit covers about 1,000 searches; past that it bills
            your card. Each question with Search the web ticked uses one search, whichever models answer.</p>
          <NumberField label="Searches a day" unit="(0 = no limit)" value={s.brave_daily_limit} min={0} max={1000000} step={1}
            note={u ? `${u.today} used today` : undefined} save={(v) => save({ brave_daily_limit: v })} />
          <NumberField label="Searches a month" unit="(0 = no limit)" value={s.brave_monthly_limit} min={0} max={10000000} step={10}
            note={u ? `${u.month} used this month; estimated cost past the credit $${u.estimated_cost_usd.toFixed(2)}` : undefined}
            save={(v) => save({ brave_monthly_limit: v })} />
          <NumberField label="Searches the credit covers" unit="a month" value={s.brave_free_monthly} min={0} max={10000000} step={100}
            save={(v) => save({ brave_free_monthly: v })} />
          <NumberField label="Price past the credit" unit="US$ per 1,000" value={s.brave_price_per_1000} min={0} max={1000} step={0.5}
            save={(v) => save({ brave_price_per_1000: v })} />
        </>
      )}
      {s.ai_search_engine === "searxng" && (
        <TextField label="SearXNG address" value={s.searxng_url} placeholder="http://localhost:8080"
          note="Run it with Docker (see the README); its settings.yml must allow the json format." save={(v) => save({ searxng_url: v })} />
      )}
      <Toggle label="Search the web by default" hint="Search the web starts ticked in the Ask AI box (and for questions typed in the top bar). Untick it for one question in the box."
        on={s.ai_search_default} set={(v) => save({ ai_search_default: v })} />
      <NumberField label="Web results per question" value={s.ai_search_results} min={1} max={20} step={1} save={(v) => save({ ai_search_results: v })} />
    </section>
  );
}

// A line of text that saves when you leave the box or press Enter.
const START_PAGES: [Settings["start_page"], string, string][] = [
  ["briefing_after_refresh", "Briefing after each refresh", "Once per new warehouse, then the map."],
  ["briefing", "Briefing every time", "The map is one click away (Explore > Map)."],
  ["map", "The map", "The Briefing is still in the menu (Today > Briefing) but never opens by itself."],
];
const LAYER_TEXT: [string, string][] = [["w", "CrisisWatch this month"], ["e", "Events"], ["n", "Reported in the news"], ["q", "Earthquakes"],
  ["s", "Storm tracks"], ["v", "Volcanoes"], ["p", "Plate boundaries"], ["c", "Major cities"]];

function BriefingSettings({ s, save }: { s: Settings; save: (patch: Partial<Settings>) => void }) {
  const [words, setWords] = useState(s.news_watch_words.split(",").join(", "));
  useEffect(() => setWords(s.news_watch_words.split(",").join(", ")), [s.news_watch_words]);
  const flip = (letter: string, on: boolean) =>
    save({ map_open_layers: LAYER_TEXT.map(([l]) => l).filter((l) => (l === letter ? on : s.map_open_layers.includes(l))).join("") });
  return (
    <section className="card" id="briefing">
      <h2>Briefing and the map&apos;s events</h2>
      <Field label="The app opens on" hint={START_PAGES.find(([id]) => id === s.start_page)?.[2]}>
        <div className="seg" role="group" aria-label="The app opens on">
          {START_PAGES.map(([id, label]) => (
            <button key={id} className={s.start_page === id ? "on" : ""} aria-pressed={s.start_page === id} onClick={() => save({ start_page: id })}>{label}</button>
          ))}
        </div>
      </Field>
      <NumberField label="Happening looks back" unit="days" value={s.briefing_days} min={1} max={90} step={1}
        note="The Briefing's first lane: CrisisWatch's month, news with a watch word, events and top news from this many days." save={(v) => save({ briefing_days: v })} />
      <Toggle label="Keep a weekly digest" hint="Briefing > Week: each Monday-to-Sunday week is made on the first visit after it ends and kept, so it reads the same later. Off: weeks are still shown, worked out each time, and nothing is kept (past weeks then show what the app holds now, not what it held then)."
        on={s.digest_on} set={(v) => save({ digest_on: v })} />
      <Field label="Layers the opening map turns on" hint="Only the map you open without a saved view; layouts and links keep their own layers. None ticked: a plain map.">
        <div>{LAYER_TEXT.map(([l, label]) => (
          <label key={l} style={{ marginRight: 10, whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={s.map_open_layers.includes(l)} onChange={(e) => flip(l, e.target.checked)} /> {label}
          </label>))}</div>
      </Field>
      <Field label="Default time window" hint="For events, news, earthquakes and storms on the map; each map can change it in its Layers panel.">
        <div className="seg" role="group" aria-label="Default time window">
          {(["7d", "30d", "90d", "1y"] as const).map((w) => (
            <button key={w} className={s.map_window === w ? "on" : ""} aria-pressed={s.map_window === w} onClick={() => save({ map_window: w })}>
              {{ "7d": "7 days", "30d": "30 days", "90d": "90 days", "1y": "This year" }[w]}
            </button>
          ))}
        </div>
      </Field>
      <div id="watch-words" />
      <Field label="News watch words" hint="News that names one of these and a country goes on the map (hollow until a dataset confirms it) and into the Briefing. Commas between words; short phrases work. Empty: no news on the map.">
        <textarea value={words} rows={3} style={{ width: "min(520px, 100%)" }} aria-label="News watch words"
          onChange={(e) => setWords(e.target.value)} onBlur={() => save({ news_watch_words: words })} />
      </Field>
      <NumberField label="Outlets before it shows" unit="outlets" value={s.news_watch_outlets} min={1} max={5} step={1}
        note="1 shows a story as soon as one outlet has it. More waits for others to report it too: fewer false alarms, but slower, and stories from one outlet never show."
        save={(v) => save({ news_watch_outlets: v })} />
      <p className="caption">News is fetched when the Briefing or Discover &gt; News is opened (Settings &gt; Discover: sources and how often).</p>
    </section>
  );
}

function TextField({ label, value, placeholder, note, save }: { label: string; value: string; placeholder?: string; note?: string; save: (v: string) => void }) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = () => { if (text.trim() !== value) save(text.trim()); };
  return (
    <Field label={label} hint={note}>
      <input type="text" value={text} placeholder={placeholder} onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()} aria-label={label} style={{ width: 260 }} />
    </Field>
  );
}

// The inbox and Downloads, the scheduled refresh and backups.
function LookingAfter({ s, save }: { s: Settings; save: (p: Partial<Settings>) => Promise<void> }) {
  const [u, setU] = useState<Upkeep | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const { job, start } = useJob();
  const load = () => api.upkeep().then(setU).catch(() => {});
  useEffect(() => { load(); }, [s.backup_folder]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (job && !job.running && job.kind === "backup") load(); }, [job?.running]); // eslint-disable-line react-hooks/exhaustive-deps
  const schedule = async (patch: { on?: boolean; often?: string; day?: string; time?: string }) => {
    const on = patch.on ?? s.schedule_on;
    try {
      const r = await api.setSchedule(on, patch.often ?? s.schedule_often, patch.day ?? s.schedule_day, patch.time ?? s.schedule_time);
      setNote(r.message);
      if (r.ok) await saveSettings({ schedule_on: on, schedule_often: (patch.often ?? s.schedule_often) as Settings["schedule_often"],
        schedule_day: patch.day ?? s.schedule_day, schedule_time: patch.time ?? s.schedule_time });
      load();
    } catch (e) { setNote(String((e as Error).message || e)); }
  };
  const times = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
  return (
    <section className="card" id="looking-after">
      <h2>Looking after the data</h2>
      <p className="small ink-2" style={{ marginTop: 0 }}>
        The <Link href="/todo">To do</Link> page lists what needs you; <Link href="/data">Data status</Link> has every source and can switch sources off.
      </p>
      <h3>Inbox</h3>
      <Toggle label="Also look in my Downloads folder"
        hint="Files downloaded in the last days whose source the app is sure of (by name, a file like it loaded before, or the site it came from) are copied into that source's folder and loaded. Downloads itself is never changed. Off: only the var\inbox folder is read, so you move files there yourself."
        on={s.inbox_downloads} set={(v) => save({ inbox_downloads: v })} />
      <NumberField label="Days back to look in Downloads" unit="days" value={s.inbox_downloads_days} min={1} max={365} step={1} save={(v) => save({ inbox_downloads_days: v })} />
      <TextField label="Downloads folder" value={s.inbox_downloads_folder} placeholder="Your own Downloads folder" note="Leave blank unless your browser saves somewhere else."
        save={(v) => save({ inbox_downloads_folder: v })} />
      <h3>Scheduled refresh</h3>
      <Toggle label="Refresh by itself"
        hint={u?.schedule.available === false ? "Only on Windows: a Windows scheduled task runs refresh.bat." :
          "A Windows scheduled task runs refresh.bat while you are signed in; the Briefing shows what came in. Off: nothing is fetched until you run refresh.bat or press Refresh."}
        on={s.schedule_on} set={(v) => schedule({ on: v })} />
      <Field label="When" hint={u?.schedule.exists ? `Windows has it${u.schedule.next_run ? `; next run ${u.schedule.next_run}` : ""}.` : "Not set up in Windows."}>
        <select value={s.schedule_often} onChange={(e) => schedule({ often: e.target.value })} aria-label="How often">
          <option value="weekly">Weekly</option><option value="daily">Every night</option></select>
        {s.schedule_often === "weekly" && <select value={s.schedule_day} onChange={(e) => schedule({ day: e.target.value })} aria-label="Day">
          {["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d) => <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>)}</select>}
        <select value={s.schedule_time} onChange={(e) => schedule({ time: e.target.value })} aria-label="Time">
          {times.map((t) => <option key={t} value={t}>{t}</option>)}</select>
      </Field>
      {note && <p className="small muted">{note}</p>}
      <h3>Backups</h3>
      <p className="small ink-2" style={{ marginTop: 0 }}>
        A backup holds what only you can replace: the files you saved by hand (var\manual), your settings, predictions, highlights and
        layouts (var\user) and your keys (.env). Downloads and builds are left out; a refresh makes them again.
      </p>
      <Toggle label="Back up when update.bat runs" hint="Once a day at most, before the update rebuilds anything. Off: only when you press Back up now."
        on={s.backup_on_update} set={(v) => save({ backup_on_update: v })} />
      <TextField label="Backup folder" value={s.backup_folder} placeholder={u?.backup_folder ?? "worldmodel-backups beside the worldmodel folder"}
        note={u ? `Now: ${u.backup_folder}` : undefined} save={(v) => save({ backup_folder: v })} />
      <NumberField label="Backups kept" unit="" value={s.backup_keep} min={1} max={100} step={1}
        note="Older backups the app made (worldmodel-backup-*.zip) are removed; nothing else in the folder is touched." save={(v) => save({ backup_keep: v })} />
      <NumberField label="Leave out files bigger than" unit="MB" value={s.backup_big_mb} min={0} max={100000} step={50}
        note="Big downloads (trade or map files) the site can give again; 0 keeps everything." save={(v) => save({ backup_big_mb: v })} />
      <Field label="Back up now" hint={u?.backups[0] ? `Last: ${u.backups[0].name} (${(u.backups[0].bytes / 1024 ** 2).toFixed(1)} MB); ${u.backups.length} kept.` : "No backup yet."}>
        <button disabled={!!job?.running} onClick={() => start("backup")}>{job?.running && job.kind === "backup" ? "Backing up…" : "Back up now"}</button>
      </Field>
      {job?.kind === "backup" && !job.running && job.lines.length > 0 && <p className="small muted">{job.lines.slice(-3).join(" ")}</p>}
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <div><div className="field-label">{label}</div>{hint && <div className="small muted">{hint}</div>}</div>
      <div className="field-control">{children}</div>
    </div>
  );
}

function Toggle({ label, hint, on, set }: { label: string; hint?: string; on: boolean; set: (v: boolean) => void }) {
  return (
    <Field label={label} hint={hint}>
      <label className="switch">
        <input type="checkbox" checked={on} onChange={(e) => set(e.target.checked)} aria-label={label} />
        <span>{on ? "On" : "Off"}</span>
      </label>
    </Field>
  );
}

// A number that saves when you leave the box or press Enter, held to its range.
function NumberField({ label, unit, value, min, max, step, note, save }: {
  label: string; unit?: string; value: number; min: number; max: number; step: number; note?: string; save: (v: number) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    const v = Number(text);
    if (!Number.isFinite(v)) return setText(String(value));
    const held = Math.min(max, Math.max(min, v));
    setText(String(held));
    if (held !== value) save(held);
  };
  return (
    <Field label={label} hint={note}>
      <input type="number" value={text} min={min} max={max} step={step} onChange={(e) => setText(e.target.value)}
        onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} aria-label={label} />
      {unit && <span className="muted"> {unit}</span>}
    </Field>
  );
}

function ClearHistory() {
  const [all, setAll] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const clear = async () => {
    if (!window.confirm(all ? "Delete the whole history, starred entries too?" : "Delete the history, keeping starred entries?")) return;
    const r = await api.clearHistory(!all).catch((e) => ({ deleted: -1, error: String(e.message || e) }));
    setMsg(r.deleted >= 0 ? `Deleted ${r.deleted} entries.` : "Could not clear the history.");
  };
  return (
    <>
      <label className="small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> starred too</label>{" "}
      <button onClick={clear}>Clear history</button>
      {msg && <span className="small muted"> {msg}</span>}
    </>
  );
}

type TileArea = { id: string; set: string; t: string; name: string; bbox: number[]; minzoom: number; maxzoom: number; tiles: number; bytes: number; missing: number; saved: string };
type TileStatus = { areas: TileArea[]; size: string; job: { state: string; step?: string; done?: number; total?: number; error?: string };
  starter_done: boolean; starter_size: string };
type TileCheck = { tiles: number; size: string; fits: boolean; why: string | null };
const SET_NAME: Record<string, string> = { relief: "Relief", satellite: "Satellite", night: "Night lights" };

// Relief, satellite and night lights: how they look, where they come from, and the copies saved here.
function MapPictures({ s, save }: { s: Settings; save: (patch: Partial<Settings>) => void }) {
  const [st, setSt] = useState<TileStatus | null>(null);
  const [area, setArea] = useState<{ set: string; t: string; country: string; maxzoom: number }>({ set: "relief", t: "-", country: "NZL", maxzoom: 10 });
  const [chk, setChk] = useState<TileCheck | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const refresh = () => fetch("/api/v1/tiles").then((r) => r.json()).then(setSt).catch(() => setSt(null));
  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    if (st?.job.state !== "running") return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [st?.job.state]);
  useEffect(() => setChk(null), [area]);
  const post = async (path: string, body?: unknown) => {
    setErr(null);
    const r = await fetch(`/api/v1/tiles/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const j = await r.json();
    if (!r.ok) { setErr(j.detail ?? "That did not work"); return null; }
    return j;
  };
  const body = () => ({ set: area.set, t: area.set === "night" ? (area.t === "-" ? "2016" : area.t) : "-", country: area.country, minzoom: 0, maxzoom: area.maxzoom });
  const drop = async (a: TileArea) => {
    if (!confirm(`Delete the saved ${SET_NAME[a.set] ?? a.set} for ${a.name}? The map fetches it online again when needed.`)) return;
    await fetch(`/api/v1/tiles/areas/${encodeURIComponent(a.id)}`, { method: "DELETE" });
    refresh();
  };
  const maxz = area.set === "night" ? 8 : 14;
  return (
    <section className="card" id="maps">
      <h2>Maps: relief, satellite and night lights</h2>
      <p className="small ink-2" style={{ marginTop: 0 }}>
        A picture under the country colours, picked here or in any map&apos;s Layers panel (Background). Shaded relief comes from AWS Terrain Tiles
        (land heights and sea depths), the satellite picture is Sentinel-2 cloudless by EOX, and night lights are NASA&apos;s Black Marble.
      </p>
      <Field label="Background">
        <div className="seg" role="group" aria-label="Background">
          {([["plain", "Plain"], ["relief", "Shaded relief"], ["satellite", "Satellite"], ["night", "Night lights"]] as const).map(([v, t]) => (
            <button key={v} className={s.map_look === v ? "on" : ""} aria-pressed={s.map_look === v} onClick={() => save({ map_look: v })}>{t}</button>
          ))}
        </div>
      </Field>
      <Field label="Relief style" hint="Height colours: green lowlands to brown mountains and blue seas. Grey: shading only, quiet under strong colours.">
        <div className="seg" role="group" aria-label="Relief style">
          {([["classic", "Height colours"], ["grey", "Grey"], ["satellite", "Over satellite"]] as const).map(([v, t]) => (
            <button key={v} className={s.relief_style === v ? "on" : ""} aria-pressed={s.relief_style === v} onClick={() => save({ relief_style: v })}>{t}</button>
          ))}
        </div>
      </Field>
      <NumberField label="Hill shading" value={s.relief_shading} min={0} max={1} step={0.05} note="0 to 1; stronger makes mountains stand out more." save={(v) => save({ relief_shading: v })} />
      <NumberField label="Country colours over a picture" value={s.map_colours_over} min={0} max={1} step={0.05} note="0 shows only the picture, 1 hides it. Countries without a figure are always left clear." save={(v) => save({ map_colours_over: v })} />
      <Field label="Night lights of" hint="NASA made whole-year pictures for 2012 and 2016; last night's picture is the newest but shows clouds and moonlight.">
        <select value={s.night_year} onChange={(e) => save({ night_year: e.target.value as Settings["night_year"] })}>
          <option value="2016">2016</option><option value="2012">2012</option><option value="latest">Last night</option>
        </select>
      </Field>
      <Toggle label="3D" hint="Tilts the map and raises the land (right-drag or Ctrl-drag to turn and tilt). Slower on older PCs. Off: flat maps." on={s.map_3d} set={(v) => save({ map_3d: v })} />
      <NumberField label="Raise the land by" unit="times" value={s.map_3d_exaggeration} min={1} max={5} step={0.5} save={(v) => save({ map_3d_exaggeration: v })} />
      <Field label="Where the pictures come from" hint="Saved copies first: the map uses what is saved on this PC and fetches the rest online through the app (nothing extra is saved while you browse). Always online: straight from the sites, nothing read from this PC.">
        <div className="seg" role="group" aria-label="Picture source">
          {([["local_first", "Saved copies first"], ["online", "Always online"]] as const).map(([v, t]) => (
            <button key={v} className={s.map_tiles === v ? "on" : ""} aria-pressed={s.map_tiles === v} onClick={() => save({ map_tiles: v })}>{t}</button>
          ))}
        </div>
      </Field>
      <Toggle label="Starter copies" hint={`Downloaded once in the background after the app starts: world relief to zoom 6, New Zealand's relief and satellite closer in, the whole world's satellite at overview zoom, 2016 night lights and land cover (the world at overview zoom, New Zealand closer in) (about ${st?.starter_size ?? "1 GB"}). Off: nothing is downloaded until you save an area below.`}
        on={s.map_tiles_starter} set={(v) => save({ map_tiles_starter: v })} />
      {st && !st.starter_done && <p className="small"><button onClick={() => post("starter").then(refresh)} disabled={st.job.state === "running"}>Download the starter copies now</button></p>}

      <h3 style={{ marginBottom: 4 }}>Save an area</h3>
      <div className="chips-row" style={{ gap: 10, alignItems: "end" }}>
        <label className="small">Picture <select value={area.set} onChange={(e) => setArea({ ...area, set: e.target.value, maxzoom: Math.min(area.maxzoom, e.target.value === "night" ? 8 : 14) })}>
          <option value="relief">Relief</option><option value="satellite">Satellite</option><option value="night">Night lights</option><option value="landcover">Land cover</option></select></label>
        {area.set === "night" && <label className="small">Year <select value={area.t === "-" ? "2016" : area.t} onChange={(e) => setArea({ ...area, t: e.target.value })}>
          <option value="2016">2016</option><option value="2012">2012</option></select></label>}
        <label className="small">Country (ISO code) <input value={area.country} size={5} onChange={(e) => setArea({ ...area, country: e.target.value.toUpperCase().slice(0, 3) })} /></label>
        <label className="small">Down to zoom <select value={area.maxzoom} onChange={(e) => setArea({ ...area, maxzoom: Number(e.target.value) })}>
          {Array.from({ length: maxz - 3 }, (_, i) => i + 4).map((z) => <option key={z} value={z}>{z}{z === 8 ? " (towns)" : z === 11 ? " (suburbs)" : z === 14 ? " (streets)" : ""}</option>)}</select></label>
        <button onClick={() => post("check", body()).then((j) => j && setChk(j))}>Check size</button>
        <button disabled={!chk?.fits || st?.job.state === "running"} onClick={() => post("save", body()).then(refresh)}>Save</button>
      </div>
      {chk && <p className="small">{chk.tiles.toLocaleString()} tiles, about <b>{chk.size}</b>.{chk.why ? <span className="warn-text"> {chk.why}.</span> : " Fits within the map files limit."}</p>}
      {st?.job.state === "running" && <p className="small"><b>Saving:</b> {st.job.step}{st.job.total ? ` (${(st.job.done ?? 0).toLocaleString()} of ${st.job.total.toLocaleString()})` : ""}. You can leave this page.</p>}
      {st?.job.state === "failed" && <p className="small warn-text"><b>Not saved:</b> {st.job.error}</p>}
      {err && <p className="small warn-text">{err}</p>}
      {!!st?.areas.length && (
        <table className="summary-table" style={{ marginTop: 8 }}>
          <thead><tr><th>Picture</th><th>Area</th><th>Zoom</th><th className="num">Size</th><th>Saved</th><th /></tr></thead>
          <tbody>
            {st.areas.map((a) => (
              <tr key={a.id}>
                <td>{SET_NAME[a.set] ?? a.set}{a.set === "night" ? ` ${a.t}` : ""}</td>
                <td>{a.name}</td>
                <td>{a.minzoom}-{a.maxzoom}</td>
                <td className="num">{a.bytes >= 1e9 ? `${(a.bytes / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(a.bytes / 1e6))} MB`}</td>
                <td className="small">{a.saved.slice(0, 10)}{a.missing ? ` (${a.missing} tiles missing)` : ""}</td>
                <td><button className="link" onClick={() => drop(a)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="caption">Saved pictures are kept in the data folder under basemap\tiles and count toward the map files limit ({st?.size ?? "nothing"} saved now).</p>

      <h3 style={{ marginBottom: 4 }}>Map shapes and space</h3>
      <Toggle label="Map shapes page" hint="True size (drag a country over another), the equal-area map and cartograms, worked out on this PC from the borders the app has. Off: the page is hidden from the menu." on={s.map_true_size} set={(v) => save({ map_true_size: v })} />
      <Toggle label="Solar system downloads" hint="When the Solar system page first opens, and every 90 days: about 25,000 asteroids from JPL's Small-Body Database and the paths of about 20 spacecraft from JPL Horizons, one request every two seconds (about 15 MB kept). Off: the planets and fact cards still show; no asteroids or mission paths." on={s.space_fetch} set={(v) => save({ space_fetch: v })} />
      <Toggle label="Asteroid values" hint="Asterank's guessed dollar values for about 1,000 asteroids, shown as a separate layer. They rest on rough guesses about what each asteroid is made of. Off: no values are fetched or shown." on={s.space_values} set={(v) => save({ space_values: v })} />
    </section>
  );
}

// Map detail under the colours, and the local map files (made here from the Protomaps
// planet build: the world to town level, chosen countries to street level).
function MapDetail({ s, save }: { s: Settings; save: (patch: Partial<Settings>) => void }) {
  const [st, setSt] = useState<BaseMapStatus | null>(null);
  const [est, setEst] = useState<BaseMapEstimate | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const refresh = () => baseMapStatus(true).then(setSt).catch((e) => setErr(String(e.message || e)));
  useEffect(() => { refresh(); api.entities().then((es) => setNames(Object.fromEntries(es.map((e) => [e.entity_id, e.short_name])))).catch(() => {}); }, []);
  useEffect(() => { // while files are being made, check how it is going
    if (st?.job.state !== "running") return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [st?.job.state]);
  useEffect(() => { setEst(null); }, [s.basemap_regions, s.basemap_world_zoom, s.basemap_region_zoom]);
  const regions: Place[] = s.basemap_regions.split(",").filter(Boolean)
    .map((r) => ({ id: r.toUpperCase(), name: names[r.toUpperCase()] ?? r.toUpperCase(), group: false }));
  const size = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.max(1, Math.round(b / 1e6))} MB`);
  const check = async () => {
    setBusy("Checking the size (this reads only the build's index, a minute or so)…"); setErr(null);
    try { setEst(await fetch("/api/v1/basemap/estimate", { method: "POST" }).then(async (r) => { if (!r.ok) throw new Error((await r.json()).detail); return r.json(); })); }
    catch (e) { setErr((e as Error).message); }
    setBusy(null);
  };
  const make = async () => {
    setErr(null);
    await fetch("/api/v1/basemap/make", { method: "POST" });
    refresh();
  };
  const drop = async (name: string) => {
    if (!confirm(`Delete the map file ${name}? You can make it again later.`)) return;
    await fetch(`/api/v1/basemap/files/${encodeURIComponent(name)}`, { method: "DELETE" });
    refresh();
  };
  const job = st?.job;
  const have = st?.files ?? [];
  return (
    <section className="card">
      <h2>Map detail</h2>
      <p className="small ink-2" style={{ marginTop: 0 }}>
        Water, roads, rail, buildings and place names under the country colours. They show faintly at world view and
        more as you zoom in, while the colours fade.
      </p>
      <Field label="World maps open centred on" hint="You can also drag a map round the globe as far as you like; it wraps.">
        <div className="seg" role="group" aria-label="Map centre">
          {([["pacific", "The Pacific (New Zealand near the middle)"], ["atlantic", "The Atlantic (Europe and Africa)"]] as const).map(([v, t]) => (
            <button key={v} className={s.map_centre === v ? "on" : ""} aria-pressed={s.map_centre === v} onClick={() => save({ map_centre: v })}>{t}</button>
          ))}
        </div>
      </Field>
      <Field label="Where the detail comes from">
        <div className="seg" role="group" aria-label="Map detail">
          {([["online", "Online (OpenFreeMap)"], ["local", "Map files on this PC"], ["plain", "None (country shapes only)"]] as const).map(([v, t]) => (
            <button key={v} className={s.base_map === v ? "on" : ""} aria-pressed={s.base_map === v} onClick={() => save({ base_map: v })}>{t}</button>
          ))}
        </div>
      </Field>
      <p className="small muted">
        Online needs the internet and stores nothing. Map files work offline and on every PC that opens the app; they are
        made once from OpenStreetMap data (Protomaps build) and remade with Refresh map files whenever you like.
        {s.base_map === "local" && !have.length && " No map files yet: the maps stay plain until you make them below."}
      </p>

      <h3 style={{ marginBottom: 4 }}>Map files</h3>
      <Field label="Countries in full detail (every street)" hint="Everywhere else goes down to the world level below.">
        <div style={{ minWidth: 260 }}>
          <PlacePicker value={regions} placeholder="None" onChange={(ps) => save({ basemap_regions: ps.filter((p) => !p.group).map((p) => p.id.toLowerCase()).join(",") })} />
        </div>
      </Field>
      <Field label="World detail" hint="How far the world file goes. Each step roughly doubles its size; sizes are rough, so use Check size. Past 12, raise the Map files limit under Storage first.">
        <select value={s.basemap_world_zoom} onChange={(e) => save({ basemap_world_zoom: Number(e.target.value) })}>
          {[[6, "6: cities and motorways"], [7, "7: towns and main roads"], [8, "8: towns, main roads and rail (suggested)"],
            [9, "9: small towns and most roads"], [10, "10: villages and local roads (about 4 GB)"],
            [11, "11: suburbs and most streets in towns (about 8 GB)"], [12, "12: suburbs and streets (about 15 GB)"],
            [13, "13: nearly every street (about 30 GB)"], [14, "14: every street (about 60 GB)"],
            [15, "15: every street and building, the whole planet (about 120 GB)"]].map(([z, t]) => <option key={z} value={z}>{t}</option>)}
        </select>
      </Field>
      <Field label="Full-detail countries go to">
        <select value={s.basemap_region_zoom} onChange={(e) => save({ basemap_region_zoom: Number(e.target.value) })}>
          {[[12, "12: suburbs and streets"], [14, "14: every street"], [15, "15: every street and building (suggested)"]].map(([z, t]) =>
            <option key={z} value={z}>{t}</option>)}
        </select>
      </Field>
      <p className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <button onClick={check} disabled={!!busy || job?.state === "running"}>Check size</button>
        <button onClick={make} disabled={!!busy || job?.state === "running" || (!!est && !est.fits)}>
          {have.length ? "Refresh map files" : "Make map files"}
        </button>
        {busy && <span className="muted small">{busy}</span>}
      </p>
      {est && (
        <div className="small">
          <b>{est.size}</b> in all, from the {est.build.slice(0, 4)}-{est.build.slice(4, 6)}-{est.build.slice(6, 8)} build:{" "}
          {est.items.map((i) => `${i.region === "world" ? "world" : names[i.region] ?? i.region} ${i.bytes ? size(i.bytes) : "size unknown"}`).join(", ")}.
          {!est.fits && <span className="warn-text"> {est.why}.</span>}
          {est.fits && " This fits within the map files limit (Storage limits below)."}
        </div>
      )}
      {job?.state === "running" && <p className="small"><b>Working:</b> {job.step}. You can leave this page; it carries on.</p>}
      {job?.state === "failed" && <p className="small warn-text"><b>The map files were not made:</b> {job.error}</p>}
      {job?.state === "done" && <p className="small">Map files ready. Maps use them when “Map files on this PC” is chosen above.</p>}
      {err && <p className="small warn-text">{err}</p>}
      {have.length > 0 && (
        <table className="summary-table" style={{ marginTop: 8 }}>
          <thead><tr><th>File</th><th className="num">Size</th><th>Detail to</th><th>Made</th><th /></tr></thead>
          <tbody>
            {have.map((f) => (
              <tr key={f.name}>
                <td>{f.region === "world" ? "World" : names[f.region] ?? f.region}</td>
                <td className="num">{size(f.bytes)}</td>
                <td>{f.maxzoom ?? "–"}</td>
                <td className="small">{f.made ? f.made.slice(0, 10) : "–"}{f.build ? ` (build ${f.build.slice(0, 8)})` : ""}</td>
                <td><button className="link" onClick={() => drop(f.name)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="caption">
        The first time, the app also fetches the small go-pmtiles tool (from GitHub) and the fonts for place names. Making
        the files reads only the needed parts of the 120 GB planet build, so it takes minutes, not hours, on a normal
        connection. Files are kept in the data folder under basemap and count toward its size limit.
      </p>
    </section>
  );
}

// Discover: which checks run, how many finds are kept, key countries, ratings, the AI line,
// your own "better when" per figure, and the news sources.
const CHECK_TEXT: [string, string, string][] = [
  ["record", "Records", "highest or lowest on record, or for decades"],
  ["mover", "Big movers", "a year's change far beyond the country's usual swings"],
  ["turning", "Turning points", "a long trend that levelled off or reversed"],
  ["overtake", "Overtakes", "a key country passing a neighbour in a ranking, or big jumps in rank"],
  ["outlier", "Outliers", "highest or lowest in the OECD, EU, G20, ASEAN or APEC by a wide margin"],
  ["disagree", "Sources disagree", "two sources for one figure moving apart"],
  ["forecast", "Forecast changes", "a forecaster's big revision between releases"],
  ["together", "Moving together", "the strongest pairs from the relationship scan (needs the scan on)"],
  ["after", "Before and after", "figures that change after events, from the scan (needs the scan on)"],
  ["revised", "New data", "past figures for key countries revised in a new release"],
  ["opposite", "Opposite trends", "a key country's figure rising steadily for ten years while a neighbour's or another key country's falls"],
];
const NEWS_TEXT: [string, string, string][] = [
  ["wikipedia", "Wikipedia Current events", "one small page a day, the backbone"],
  ["gdelt", "GDELT news counts", "spikes in news about your key countries; slow (5 seconds a request)"],
  ["feeds", "News feeds", "headlines with links from the feeds ticked below"],
  ["reliefweb", "ReliefWeb (UN)", "disasters and crises; only with an approved app name below"],
];
const FEED_TEXT: [string, string][] = [["rnz", "RNZ (NZ)"], ["rnz_world", "RNZ world"], ["stuff", "Stuff (NZ)"], ["abc", "ABC Australia"], ["bbc", "BBC World"], ["guardian", "The Guardian"]];

function DiscoverSettings({ s, save }: { s: Settings; save: (patch: Partial<Settings>) => void }) {
  const [inds, setInds] = useState<Indicator[]>([]);
  const [pick, setPick] = useState("");
  useEffect(() => { api.indicators().then(setInds).catch(() => {}); }, []);
  const list = (v: string) => (v || "").split(",").filter(Boolean);
  const flip = (key: "discover_checks" | "news_sources" | "news_feeds", id: string, on: boolean) => {
    const cur = list(s[key]);
    save({ [key]: (on ? [...cur, id] : cur.filter((x) => x !== id)).join(",") } as Partial<Settings>);
  };
  const better = s.discover_better ?? {};
  const name = (id: string) => inds.find((i) => i.indicator_id === id)?.name ?? id;
  const checks = list(s.discover_checks);
  return (
    <section className="card" id="discover">
      <h2>Discover</h2>
      <p className="small ink-2" style={{ marginTop: 0 }}>
        After each refresh the app looks through the figures switched on for interesting finds (the <Link href="/discover">Discover</Link> page,
        and a card at the top of each country page). Changes here apply from the next refresh, or press &quot;Look again now&quot; on the page.
      </p>
      <Toggle label="Look for finds after each refresh" hint="Off: the Discover page keeps the last finds, and the country cards stay as they were. Takes under a minute."
        on={s.discover_on} set={(v) => save({ discover_on: v })} />
      <Field label="Checks" hint="Each check you untick stops that kind of find appearing at all.">
        <div>{CHECK_TEXT.map(([id, label, hint]) => (
          <label key={id} style={{ display: "block" }} title={hint}><input type="checkbox" checked={checks.includes(id)} onChange={(e) => flip("discover_checks", id, e.target.checked)} />
            {" "}{label} <span className="small muted">({hint})</span></label>))}</div>
      </Field>
      <NumberField label="Finds kept" unit="per refresh" value={s.discover_keep} min={50} max={5000} step={50}
        note="The best ones are kept. More finds means more weak ones further down." save={(v) => save({ discover_keep: v })} />
      <TextField label="Key countries" value={s.discover_key_countries} placeholder="NZL,AUS,GBR,USA"
        note="Lifted in the feed, and the only countries checked for overtakes, revisions, forecast changes and news spikes. Others still get records, movers and outliers."
        save={(v) => save({ discover_key_countries: v.toUpperCase() })} />
      <NumberField label="Lift for key countries" unit="times" value={s.discover_key_boost} min={1} max={5} step={0.1}
        note="1 = no lift: key countries are ranked like any other." save={(v) => save({ discover_key_boost: v })} />
      <Toggle label="Group the same find across countries" hint="One card when several countries hit the same record, jump or turn in the same year, with up to four drawn against the world. Off: one card per country, which can fill the feed with repeats. Takes effect on the next look (Discover: Look again now)."
        on={s.discover_merge} set={(v) => save({ discover_merge: v })} />
      <Toggle label="Ratings tune the feed" hint="Off: Interesting and Not interesting still keep and hide finds, but no longer move similar ones up or down."
        on={s.discover_tune} set={(v) => save({ discover_tune: v })} />
      <Toggle label="'Why might this be?' button" hint="Asks your local AI for likely reasons; its answer is a guess, shown as such. Needs Local AI on; off, the button is not shown."
        on={s.discover_ai} set={(v) => save({ discover_ai: v })} />
      <Field label="Better when (your own)" hint="Sets a figure's tone: rising is good news when higher is better. Without your choice the app guesses from the name, and contested ones are neutral.">
        <div>
          {Object.entries(better).map(([id, b]) => (
            <div key={id} className="small">{name(id)}:{" "}
              <select value={b} onChange={(e) => save({ discover_better: { ...better, [id]: e.target.value as "higher" | "lower" | "neither" } })} aria-label={`Better when for ${name(id)}`}>
                <option value="higher">higher is better</option><option value="lower">lower is better</option><option value="neither">neither (neutral)</option>
              </select>{" "}
              <button className="link" onClick={() => { const rest = { ...better }; delete rest[id]; save({ discover_better: rest }); }}>Back to the app&apos;s guess</button>
            </div>
          ))}
          {inds.length > 0 && <div className="small" style={{ marginTop: 4 }}>
            <IndicatorSelect indicators={inds} value={pick} onChange={(id) => { setPick(""); if (id && !better[id]) save({ discover_better: { ...better, [id]: "higher" } }); }} label="Add a figure" />
          </div>}
        </div>
      </Field>
      <h3>News</h3>
      <Toggle label="Fetch major news" hint="For Discover's News tab, when it is opened. Off: the tab shows only news already kept, and nothing is fetched."
        on={s.news_on} set={(v) => save({ news_on: v })} />
      <Field label="News sources" hint="All free and read politely: a few requests each time.">
        <div>{NEWS_TEXT.map(([id, label, hint]) => (
          <label key={id} style={{ display: "block" }}><input type="checkbox" checked={list(s.news_sources).includes(id)} onChange={(e) => flip("news_sources", id, e.target.checked)} />
            {" "}{label} <span className="small muted">({hint})</span></label>))}</div>
      </Field>
      <Field label="News feeds" hint="Only read with News feeds ticked above.">
        <div>{FEED_TEXT.map(([id, label]) => (
          <label key={id} style={{ marginRight: 10 }}><input type="checkbox" checked={list(s.news_feeds).includes(id)} onChange={(e) => flip("news_feeds", id, e.target.checked)} /> {label}</label>))}</div>
      </Field>
      <TextField label="ReliefWeb app name" value={s.news_reliefweb_app} placeholder="(blank: ReliefWeb off)"
        note="ReliefWeb only answers app names it has approved; ask for one free at apidoc.reliefweb.int. Blank: no ReliefWeb items, even with it ticked."
        save={(v) => save({ news_reliefweb_app: v })} />
      <NumberField label="Fetch news again after" unit="hours" value={s.news_every_hours} min={1} max={720} step={1} save={(v) => save({ news_every_hours: v })} />
      <NumberField label="Keep news for" unit="days" value={s.news_keep_days} min={7} max={36500} step={1}
        note="Older items are dropped at the next fetch, unless you marked them Interesting." save={(v) => save({ news_keep_days: v })} />
    </section>
  );
}

// What the app is built with, one line each (from data/pyproject.toml, app/api/pyproject.toml,
// contract/pyproject.toml and app/web/package.json).
const LIBRARIES: [string, [string, string][]][] = [
  ["Programs it runs on", [
    ["Python 3.12", "Runs the data side (fetching and building) and the API the pages talk to."],
    ["Node.js 22", "Runs the web pages you are looking at."],
    ["Miniconda (conda)", "Keeps Python and Node.js in their own folder (the worldmodel environment) so nothing else on the PC is touched."],
    ["Ollama (optional)", "Runs the local AI models behind Ask AI; nothing is sent to an online AI."],
  ]],
  ["Data side (fetching, building the database)", [
    ["DuckDB", "The database: every figure is kept in Parquet files and one DuckDB file, which answers the app's questions in a moment."],
    ["dbt (dbt-core, dbt-duckdb)", "Builds the database from the downloaded files in checked steps, with tests that stop a bad build."],
    ["httpx", "Downloads files and reads web services, politely and with clear errors."],
    ["certifi, truststore", "The list of trusted certificates, so secure (https) downloads work behind company networks and on Windows."],
    ["Typer", "The worldmodel-data commands that refresh.bat, load.bat and the other scripts call."],
    ["python-dotenv", "Reads your keys from the .env file."],
    ["PyYAML", "Reads the catalogues: sources, indicators, events and groups written as YAML."],
    ["pydantic", "Checks the shape of the catalogues and settings."],
    ["openpyxl, xlrd", "Read Excel files (new .xlsx and old .xls) that many sources publish."],
    ["pypdf", "Reads PDF files, such as the CrisisWatch archive."],
    ["rdata", "Reads R data files (.rda/.rds) some research datasets come in."],
    ["NumPy", "Fast number crunching: forecasts, climate grids, picture pixels."],
    ["Pillow", "Reads pictures: climate zone maps and land cover tiles."],
    ["pyshp", "Reads shapefiles, such as the protected areas map."],
    ["Shapely", "Works with shapes: city outlines, areas and what falls inside what."],
    ["Playwright", "verify.bat: opens sites with a person check in your own browser so you can pass it."],
  ]],
  ["API (between the database and the pages)", [
    ["FastAPI", "Answers the pages' requests (localhost:8000/api) and writes the API docs page."],
    ["Uvicorn", "The small web server FastAPI runs in."],
    ["websockets", "Live feeds: ships now (AISstream)."],
  ]],
  ["Web pages", [
    ["Next.js", "The framework the pages are built with (on port 3030)."],
    ["React", "Draws the pages and updates them as you click."],
    ["MapLibre GL", "Draws the maps: countries, layers, satellite and relief, 3D."],
    ["PMTiles", "Reads the map tiles kept on this PC in one file, for maps that work offline."],
    ["Apache ECharts", "Draws the charts."],
    ["flag-icons", "The country flags (pictures, not emoji)."],
    ["TypeScript", "Checks the page code for mistakes before it runs."],
  ]],
  ["Tests", [["pytest", "Runs the checks on the data, contract and API code."]]],
];

function Libraries() {
  return (
    <section className="card" id="libraries">
      <h2>Libraries this app uses</h2>
      <p className="small ink-2" style={{ marginTop: 0 }}>All free and open source. setup.bat installs them and update.bat keeps them current.</p>
      {LIBRARIES.map(([group, libs]) => (
        <div key={group}>
          <h3>{group}</h3>
          <dl className="lib-list">{libs.map(([n, what]) => <Fragment key={n}><dt>{n}</dt><dd>{what}</dd></Fragment>)}</dl>
        </div>
      ))}
    </section>
  );
}
