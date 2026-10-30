"use client";

import Link from "next/link";
import { KINDS, kindVar } from "@/lib/events";
import { useEffect, useState } from "react";
import { api, type Settings, type Storage } from "@/lib/api";
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
        <Toggle label="Side panel (pinboard)" hint="A column beside the panels for cards sent from popups; saved with each layout."
          on={s.side_panel} set={(v) => save({ side_panel: v })} />
      </section>

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
