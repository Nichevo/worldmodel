"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AskButton from "@/components/AskButton";
import CardAsk from "@/components/CardAsk";
import Flag from "@/components/Flag";
import { AttentionCard, CalendarList, NowcastCard, OddsChart, OddsRow } from "@/components/outlook/OutlookParts";
import { openAsk } from "@/lib/ai";
import { logHistory } from "@/lib/history";
import { type AttentionTop, type Calendar, type OddsAll, type OddsReply, oddsTone, outlookApi } from "@/lib/outlook";

type Tab = "recession" | "nowcasts" | "calendar" | "attention";
const TABS: [Tab, string][] = [["recession", "Recession odds"], ["nowcasts", "Nowcasts"], ["calendar", "Release calendar"], ["attention", "Wikipedia attention"]];
const KEY = ["NZL", "AUS", "GBR", "USA"];
const NAMES: Record<string, string> = { NZL: "New Zealand", AUS: "Australia", GBR: "United Kingdom", USA: "United States" };
const INTRO: Record<Tab, string> = {
  recession: "The chance that a recession (two quarters running of falling GDP) starts within the next year, from a model fitted across all countries on the OECD leading indicator, central bank rate changes and recent growth. The US also shows the New York Fed's yield-curve model.",
  nowcasts: "This quarter's growth, estimated before the official figure comes out, from last quarter's growth and the months of the OECD leading indicator already out. Each card shows how far the method was off in past quarters.",
  calendar: "Figures and rate decisions coming up for New Zealand, Australia, the UK and the US, in New Zealand time. Where the app has a nowcast for a GDP release, it shows beside it.",
  attention: "How many people read each country's English Wikipedia article. A sudden jump usually means something is happening there, often before the data shows it.",
};

function OutlookView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "recession");
  const go = (t: Tab) => { setTab(t); router.replace(`/outlook?tab=${t}`, { scroll: false }); };
  useEffect(() => { logHistory({ kind: "page", title: "Outlook", url: "/outlook", detail: "page" }); }, []);
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Outlook</h1>
        <AskButton title={`Outlook: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => {
          const o = await outlookApi.odds(KEY);
          return [{ key: "description", kind: "description", label: "What this page shows", text: INTRO[tab] },
            { key: "data", kind: "data", label: "Recession odds", text: o.countries.map((c) => `${c.name}: ${c.odds ?? "no reading"}% (${c.month ?? ""})`).join("\n") }];
        }} />
        <span className="spacer" /><Link href="/settings#outlook" className="small muted">Settings</Link></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
      {tab === "recession" && <RecessionTab start={params.get("country") ?? "NZL"} />}
      {tab === "nowcasts" && <div className="cards-2">{KEY.map((e) => <NowcastCard key={e} entity={e} name={NAMES[e]} />)}</div>}
      {tab === "calendar" && <CalendarTab />}
      {tab === "attention" && <AttentionTab />}
    </div>
  );
}

function RecessionTab({ start }: { start: string }) {
  const [pick, setPick] = useState(start);
  const [d, setD] = useState<OddsReply | null>(null);
  const [all, setAll] = useState<OddsAll | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ents = KEY.includes(pick) ? KEY : [...KEY, pick];
  useEffect(() => {
    let live = true;
    outlookApi.odds(ents).then((x) => live && setD(x)).catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [ents.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { outlookApi.oddsAll().then(setAll).catch(() => setAll(null)); }, []);
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Working it out…</p>;
  if (d.countries.every((c) => c.odds === null)) return <p className="muted">No readings yet: the model needs the OECD leading indicators and quarterly GDP, which come with <code>.\refresh.bat</code>.</p>;
  const o = d.countries.find((c) => c.entity === pick) ?? d.countries[0];
  const full = d.models.full ?? Object.values(d.models)[0];
  return (
    <>
      <OddsRow data={{ ...d, countries: d.countries.filter((c) => KEY.includes(c.entity)) }} pick={pick} onPick={setPick} />
      <OddsChart o={o} note={d.note} />
      {all && all.countries.length > 0 && (
        <div className="card">
          <div className="card-head"><h3>Every country with a reading, highest odds first</h3>
            <CardAsk onAsk={() => openAsk({ title: "Recession odds by country", parts: [
              { key: "data", kind: "data", label: "Odds", text: all.countries.map((c) => `${c.name}: ${c.odds}% (${c.month})`).join("\n") }] })} /></div>
          <div className="odds-table">
            {all.countries.map((c) => (
              <button key={c.entity} className={`odds-line${pick === c.entity ? " on" : ""}`} onClick={() => setPick(c.entity)}>
                <span><Flag id={c.entity} />{c.name}</span>
                <span className="odds-bar"><i style={{ width: `${c.odds}%`, background: oddsTone(c.odds) }} /></span>
                <b>{c.odds.toFixed(0)}%</b>
                <span className="small muted">{c.in_recession ? "in recession" : c.month}</span>
              </button>
            ))}
          </div>
          {full && <p className="caption">Fitted on {full.months.toLocaleString()} country-months; in {full.base_rate}% of them a recession started within the next year. How well it ranks the past (AUC, 0.5 is chance, 1 perfect): {full.auc ?? "–"}. Click a country for its chart.</p>}
        </div>
      )}
    </>
  );
}

function CalendarTab() {
  const [countries, setCountries] = useState<string[]>(KEY);
  const [ahead, setAhead] = useState(42);
  const [d, setD] = useState<Calendar | null>(null);
  useEffect(() => {
    let live = true;
    setD(null);
    outlookApi.calendar(countries, ahead).then((x) => live && setD(x)).catch(() => live && setD({ items: [], notes: ["The calendar could not be loaded."], today: "" }));
    return () => { live = false; };
  }, [countries.join(","), ahead]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (e: string) => setCountries(countries.includes(e) ? countries.filter((x) => x !== e) : [...countries, e]);
  return (
    <div className="card">
      <div className="card-head"><h3>Coming up</h3>
        <CardAsk onAsk={() => openAsk({ title: "Data releases coming up", parts: [
          { key: "data", kind: "data", label: "Releases", text: (d?.items ?? []).filter((r) => !r.past).map((r) => `${r.nz_time} NZ | ${r.country} | ${r.title} | ${r.period}`).join("\n") }] })} /></div>
      <div className="long-tools">
        <div className="chips-row small">{KEY.map((e) => (
          <button key={e} className={`chip${countries.includes(e) ? " on" : ""}`} aria-pressed={countries.includes(e)} onClick={() => toggle(e)}><Flag id={e} />{NAMES[e]}</button>))}</div>
        <label className="small">Show <select value={ahead} onChange={(e) => setAhead(+e.target.value)}>
          <option value={14}>the next two weeks</option><option value={42}>the next six weeks</option><option value={120}>the next four months</option></select></label>
      </div>
      {!d ? <p className="muted">Loading…</p> : <CalendarList data={d} />}
      <p className="caption">Times are New Zealand time. Dates come from the publishers&apos; own schedules (BLS, BEA, the Fed, the RBNZ, the Bank of England, the RBA) and, for the UK and Australia&apos;s data releases, their live calendars. Stats NZ has no calendar the app can read, so its dates are estimated from its usual timing.
        {d?.notes.length ? ` ${d.notes.join(" ")}` : ""}</p>
    </div>
  );
}

function AttentionTab() {
  const [d, setD] = useState<AttentionTop | null>(null);
  const [pick, setPick] = useState("NZL");
  useEffect(() => { outlookApi.attentionTop().then(setD).catch(() => setD(null)); }, []);
  if (!d) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="card">
        <div className="card-head"><h3>{d.day ? `Countries among Wikipedia's most-read articles on ${d.day}` : "Most-read countries"}</h3>
          <CardAsk onAsk={() => openAsk({ title: "Countries people are reading about", parts: [
            { key: "data", kind: "data", label: "Most read", text: d.countries.map((c) => `#${c.rank} ${c.name}: ${c.views} views`).join("\n") }] })} /></div>
        {d.note && <p className="muted small">{d.note}</p>}
        {d.countries.length === 0 && !d.note && <p className="muted small">No country article made the day&apos;s top 1,000.</p>}
        <ol className="attention-top">
          {d.countries.map((c) => (
            <li key={c.entity}><Link href={`/entity/${c.entity}#attention`}><Flag id={c.entity} />{c.name}</Link>
              <span className="small muted"> #{c.rank} of all articles, {c.views.toLocaleString()} views</span></li>))}
        </ol>
        <p className="caption">Wikipedia&apos;s 1,000 most-read English articles that day, from Wikimedia; countries picked out by their article title.</p>
      </div>
      <div className="card">
        <div className="card-head"><h3>Your key countries this week</h3></div>
        <div className="chips-row small">{d.key.map((k) => (
          <button key={k.entity} className={`chip${pick === k.entity ? " on" : ""}`} aria-pressed={pick === k.entity} onClick={() => setPick(k.entity)}>
            <Flag id={k.entity} />{k.name}{k.ratio ? ` · ${k.ratio.toFixed(1)}× usual` : ""}</button>))}</div>
        <p className="caption">The last seven days&apos; average against the usual level. Pick one for its 90 days below.</p>
      </div>
      <AttentionCard entity={pick} name={NAMES[pick] ?? pick} />
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><OutlookView /></Suspense>;
}
