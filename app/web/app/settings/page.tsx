"use client";

import Link from "next/link";
import { KINDS, kindVar } from "@/lib/events";
import { useEffect, useState } from "react";
import { api, TYPE_TEXT, type AIStatus, type MeasureType, type Settings, type Storage } from "@/lib/api";
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
      </section>

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

      <MapDetail s={s} save={save} />

      <section className="card">
        <h2>Places</h2>
        <Toggle label="Metro and rail, universities and big companies" hint="Five Wikidata queries every four weeks during .\refresh.bat. They fill the Transport, universities and companies card on country and city pages and three map layers. Switching off keeps what is stored."
          on={s.places_fetch} set={(v) => save({ places_fetch: v })} />
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
