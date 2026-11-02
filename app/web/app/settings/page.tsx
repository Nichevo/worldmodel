"use client";

import Link from "next/link";
import { KINDS, kindVar } from "@/lib/events";
import { useEffect, useState } from "react";
import { api, type AIStatus, type Settings, type Storage } from "@/lib/api";
import { DEFAULT_SETTINGS, saveSettings, useSettings } from "@/lib/settings";

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
        <Toggle label="Banner while a refresh problem is open"
          hint="Shows the latest failed check or download at the top of every page, with how often it has happened, until a later refresh passes. The Problems list on Data status is always there."
          on={s.problem_banner} set={(v) => save({ problem_banner: v })} />
      </section>

      <section className="card">
        <h2>Places</h2>
        <Toggle label="Metro and rail, universities and big companies" hint="Five Wikidata queries every four weeks during .\refresh.bat. They fill the Transport, universities and companies card on country and city pages and three map layers. Switching off keeps what is stored."
          on={s.places_fetch} set={(v) => save({ places_fetch: v })} />
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
      <Field label="Second model, side by side" hint="Each question also goes to this model, its answer beside the first. None to ask one model.">
        <select value={s.ai_model_compare} onChange={(e) => save({ ai_model_compare: e.target.value })} aria-label="Second model">
          <option value="">None</option>
          {names.map((n) => <option key={n} value={n}>{tag(n)}</option>)}
        </select>
      </Field>
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
