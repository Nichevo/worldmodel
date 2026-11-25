"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import CardAsk from "@/components/CardAsk";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import WorldMap from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import {
  type Causes, causesOption, type Compare, compareOption, diseaseApi, type Notifiable, notifiableOption, sparkPoints, fmt, heatOption, KEY, KEY_NAMES, LEVEL_TONE, type Long, longOption, type Measure, type Measures,
  type Now, type Outbreak, type Seasons, seasonOption, trendWord, weekLabel,
} from "@/lib/disease";
import { entityColors } from "@/lib/look";
import { logHistory } from "@/lib/history";

// Flu, COVID, RSV, measles and other infections: how much there is now against the usual for the
// time of year, this season against past ones, the key countries side by side, a century of yearly
// cases, and outbreak news.
type Tab = "now" | "seasons" | "compare" | "long" | "causes" | "outbreaks";
const TABS: [Tab, string][] = [["now", "Now"], ["seasons", "Seasons"], ["compare", "Compare"], ["long", "Long view"], ["causes", "Causes of death"],
  ["outbreaks", "Outbreaks"]];
const INTRO: Record<Tab, string> = {
  now: "The latest week in each country against what is usual for that week of the year (the average of the same weeks in 2015-2019, or of earlier years leaving out 2020 and 2021 where 2015-2019 is missing).",
  seasons: "This season against earlier ones, week by week. Southern countries' seasons run January to December; northern ones July to June, so a winter is not split in two. The shaded band is the normal range of 2015-2019.",
  compare: "New Zealand, Australia, the United Kingdom and the United States on one scale over the same years.",
  long: "Yearly cases reported to WHO, per million people, back as far as the records go. Pandemic years are shaded. Below, every notifiable disease in New Zealand since 2006.",
  causes: "What people die of: deaths per 100,000 people from each broad group of causes, age-standardised so countries with older people can be compared, from death certificates reported to the WHO Mortality Database.",
  outbreaks: "WHO Disease Outbreak News: each report of an unusual outbreak, newest first.",
};

function DiseaseView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "now");
  const [measure, setMeasure] = useState(params.get("measure") ?? "flu_pct_positive");
  const [country, setCountry] = useState(params.get("country") ?? "NZL");
  const [meta, setMeta] = useState<Measures | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const go = (t: Tab, m = measure, c = country) => {
    setTab(t); setMeasure(m); setCountry(c);
    router.replace(`/disease?tab=${t}&measure=${m}&country=${c}`, { scroll: false });
  };
  useEffect(() => { logHistory({ kind: "page", title: "Disease", url: "/disease", detail: "page" }); }, []);
  useEffect(() => { diseaseApi.measures().then(setMeta).catch((e) => setErr(String(e.message || e))); }, []);
  const m = meta?.measures.find((x) => x.id === measure) ?? null;
  const weekly = tab === "now" || tab === "seasons" || tab === "compare";
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Disease</h1>
        <AskButton title={`Disease: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => {
          const n = await diseaseApi.now(measure);
          return [{ key: "description", kind: "description", label: "What this page shows", text: INTRO[tab] },
            { key: "data", kind: "data", label: `${n.measure?.label ?? measure}, latest week`,
              text: n.rows.map((r) => `${r.name}: ${fmt(r.value, n.measure)} (usual ${fmt(r.usual, n.measure)}, ${n.levels?.[r.level] ?? r.level}) week of ${r.week}`).join("\n") }];
        }} />
        <span className="spacer" /><Link href="/settings#disease" className="small muted">Settings</Link></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""}
        onClick={() => go(t)}>{label}</button>)}</div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
      {err && <p className="error">{err}</p>}
      {weekly && meta && <MeasurePick meta={meta} value={measure} onChange={(x) => go(tab, x)} />}
      {meta && !meta.measures.some((x) => x.places) && (
        <p className="card">Nothing loaded yet. Run <code>.\refresh.bat</code> (Settings &gt; Disease on). WHO FluNet, New Zealand wastewater, UKHSA, the US CDC,
          ECDC, Our World in Data, WHO yearly counts, OpenDengue and WHO outbreak news all come in on their own; weekly deaths from the Human Mortality
          Database need a free login, so save its STMF file into <code>var\manual\hmd_stmf</code>.</p>
      )}
      {tab === "now" && <NowTab measure={measure} m={m} onCountry={(c) => go("seasons", measure, c)} />}
      {tab === "seasons" && <SeasonsTab measure={measure} country={country} onCountry={(c) => go("seasons", measure, c)} />}
      {tab === "compare" && <CompareTab measure={measure} />}
      {tab === "long" && <><LongTab /><NotifiableCard /></>}
      {tab === "causes" && <CausesTab country={country} onCountry={(c) => go("causes", measure, c)} />}
      {tab === "outbreaks" && <OutbreaksTab />}
    </div>
  );
}

function MeasurePick({ meta, value, onChange }: { meta: Measures; value: string; onChange: (id: string) => void }) {
  const names = new Map(meta.diseases.map((d) => [d.key, d.name]));
  const groups = new Map<string, Measure[]>();
  for (const x of meta.measures) {
    if (!x.places && x.id !== value) continue;
    groups.set(x.disease, [...(groups.get(x.disease) ?? []), x]);
  }
  return (
    <div className="chips-row small">
      <label>Measure <select value={value} onChange={(e) => onChange(e.target.value)}>
        {[...groups].map(([d, ms]) => (
          <optgroup key={d} label={names.get(d) ?? d}>
            {ms.map((x) => <option key={x.id} value={x.id}>{x.label}{x.places ? ` (${x.places} places)` : " (none loaded)"}</option>)}
          </optgroup>
        ))}
      </select></label>
      {(() => { const x = meta.measures.find((y) => y.id === value); return x ? <span className="muted">{x.unit}. {x.sources}</span> : null; })()}
    </div>
  );
}

function LevelPill({ level, words }: { level: Now["rows"][number]["level"]; words?: Record<string, string> }) {
  return <span className="pill small" style={{ color: `var(${LEVEL_TONE[level]})`, borderColor: `var(${LEVEL_TONE[level]})` }}>{words?.[level] ?? level.replace("_", " ")}</span>;
}

function NowTab({ measure, m, onCountry }: { measure: string; m: Measure | null; onCountry: (c: string) => void }) {
  const [d, setD] = useState<Now | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    let live = true;
    setD(null);
    diseaseApi.now(measure).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [measure]);
  if (err) return <p className="error">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  if (!d.rows.length) return <p className="muted">No weeks loaded for this measure yet.</p>;
  const countries = d.rows.filter((r) => /^[A-Z]{3}$/.test(r.entity));
  const values = countries.map((r) => ({ entity_id: r.entity, value: r.ratio !== null ? r.ratio * 100 : r.value, status: "E" }));
  const byRatio = countries.some((r) => r.ratio !== null);
  const rows = d.rows.filter((r) => !filter || r.name.toLowerCase().includes(filter.toLowerCase()));
  return (
    <>
      {countries.length > 1 && (
        <div className="card">
          <h3>{byRatio ? "Latest week as % of the usual for the time of year" : `Latest week: ${d.measure.label}`}</h3>
          <div className="map-box" style={{ height: 420 }}>
            <WorldMap fill values={values.filter((v) => byRatio ? countries.find((c) => c.entity === v.entity_id)?.ratio !== null : true)}
              unit={byRatio ? "% of usual" : d.measure.unit} decimals={0} diverging={false} onPick={onCountry} />
          </div>
          <p className="caption">Click a country to see its seasons. Places whose latest week is more than 8 weeks behind the newest are left off.</p>
        </div>
      )}
      <div className="card">
        <div className="card-head"><h3>{d.measure.label}, latest week in each place</h3>
          <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter places" aria-label="Filter places" />
          <CardAsk onAsk={() => openAsk({ title: `${d.measure.label} now`, parts: [{ key: "data", kind: "data", label: "Latest week",
            text: d.rows.map((r) => `${r.name}: ${fmt(r.value, m ?? d.measure)}, usual ${fmt(r.usual, m ?? d.measure)}, ${r.trend ?? ""}`).join("\n") }] })} /></div>
        <table className="small">
          <thead><tr><th>Place</th><th>Week of</th><th style={{ textAlign: "right" }}>Value</th><th style={{ textAlign: "right" }}>Usual</th>
            <th style={{ textAlign: "right" }}>Against usual</th><th>Level</th><th>Trend</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.entity} style={{ fontWeight: KEY.includes(r.entity) ? 600 : undefined }}>
              <td><button className="link" onClick={() => onCountry(r.entity)}><Flag id={r.entity} />{r.name}</button></td>
              <td className="muted">{weekLabel(r.week)}</td>
              <td style={{ textAlign: "right" }}>{fmt(r.value, d.measure)}</td>
              <td style={{ textAlign: "right" }} className="muted">{fmt(r.usual, d.measure)}</td>
              <td style={{ textAlign: "right" }}>{r.ratio !== null ? `${Math.round(r.ratio * 100)}%` : "–"}</td>
              <td><LevelPill level={r.level} words={d.levels} /></td>
              <td className="muted">{trendWord(r.trend)}</td>
            </tr>
          ))}</tbody>
        </table>
        <p className="caption">Level: below 67% of usual is low, 67-150% usual, 150-300% high, over 300% well above usual. A place needs at least three
          earlier years to have a usual.</p>
      </div>
    </>
  );
}

function SeasonsTab({ measure, country, onCountry }: { measure: string; country: string; onCountry: (c: string) => void }) {
  const [v, setV] = useState<Seasons | null>(null);
  const [heat, setHeat] = useState<Seasons | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  useEffect(() => {
    let live = true;
    setV(null); setHeat(null); setErr(null);
    diseaseApi.seasons(country, measure).then((x) => live && setV(x)).catch((e) => live && setErr(String(e.message || e)));
    diseaseApi.heat(country, measure).then((x) => live && setHeat(x)).catch(() => live && setHeat(null));
    return () => { live = false; };
  }, [country, measure]);
  const color = entityColors([country])[0] ?? "var(--accent)";
  const h = v?.headline;
  return (
    <>
      <div className="chips-row small">
        {KEY.map((k) => <button key={k} className={`chip${k === country ? " on" : ""}`} aria-pressed={k === country} onClick={() => onCountry(k)}><Flag id={k} />{KEY_NAMES[k]}</button>)}
        <CountryChoice value={country} onChange={onCountry} label="Another country" />
      </div>
      {err && <p className="error">{err}</p>}
      {!v && !err && <p className="muted">Loading…</p>}
      {v && !v.seasons.length && <p className="muted">{v.note ?? "No weeks loaded for this country and measure."}</p>}
      {v && v.seasons.length > 0 && (
        <>
          {h && (
            <div className="card">
              <h2 style={{ margin: 0 }}>{h.rank === 1 ? `The ${h.season} season is the highest since ${h.since ?? "records began"}` :
                `The ${h.season} season peaked at ${fmt(h.peak, v.measure)}, #${h.rank} of ${h.of} seasons`}</h2>
              <p className="ink-2" style={{ margin: "4px 0 0" }}>
                Peak {fmt(h.peak, v.measure)} in the week of {weekLabel(h.peak_week)}. Latest week ({weekLabel(h.latest_week)}) {fmt(h.latest, v.measure)}
                {h.usual !== null ? `, against a usual ${fmt(h.usual, v.measure)} for the time of year` : ""}.
              </p>
            </div>
          )}
          <div className="card">
            <div className="card-head"><h3>{v.measure.label}, each season week by week</h3>
              <label className="small"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> All past seasons</label>
              <CardAsk onAsk={() => openAsk({ title: `${v.measure.label} seasons, ${country}`, entity: country, parts: [{ key: "data", kind: "data", label: "Season peaks",
                text: v.seasons.map((s) => `${s.label}: peak ${fmt(s.peak, v.measure)}`).join("\n") }] })} /></div>
            <EChart option={() => seasonOption(v, color, all)} height={380} label={`${v.measure.label} by season`} />
            <p className="caption">{v.season_note ?? ""} {v.sources?.length ? `Source: ${v.sources.join(", ")}.` : ""}</p>
          </div>
          {heat && heat.seasons.length > 1 && (
            <div className="card">
              <h3>Every season at a glance</h3>
              <EChart option={() => heatOption(heat)} height={Math.max(220, 26 * heat.seasons.length + 80)} label="Seasons heat strip" />
              <p className="caption">Darker means more. Hover a week to see the main flu strain that week, where WHO FluNet has strain counts.</p>
            </div>
          )}
        </>
      )}
    </>
  );
}

function CompareTab({ measure }: { measure: string }) {
  const [years, setYears] = useState(5);
  const [ids, setIds] = useState<string[]>(KEY);
  const [c, setC] = useState<Compare | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [more, setMore] = useState("");
  useEffect(() => {
    let live = true;
    setC(null);
    diseaseApi.compare(measure, ids, years).then((x) => live && setC(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [measure, ids.join(","), years]); // eslint-disable-line react-hooks/exhaustive-deps
  const missing = c ? ids.filter((i) => !c.series.some((s) => s.entity === i)) : [];
  return (
    <>
      <div className="chips-row small">
        <span className="seg">{[2, 5, 10, 20].map((y) => <button key={y} className={years === y ? "on" : ""} onClick={() => setYears(y)}>{y} years</button>)}</span>
        {ids.map((i) => <span key={i} className="chip"><Flag id={i} />{KEY_NAMES[i] ?? i}
          {ids.length > 1 && <button aria-label={`Remove ${i}`} onClick={() => setIds(ids.filter((x) => x !== i))}>×</button>}</span>)}
        <CountryChoice value={more} onChange={(x) => { setMore(""); if (x && !ids.includes(x)) setIds([...ids, x]); }} label="Add a country" />
      </div>
      {err && <p className="error">{err}</p>}
      {!c && !err && <p className="muted">Loading…</p>}
      {c && (
        <div className="card">
          <div className="card-head"><h3>{c.measure?.label ?? measure}</h3>
            <CardAsk onAsk={() => openAsk({ title: `${c.measure?.label ?? measure}: key countries`, parts: [{ key: "data", kind: "data", label: "Weekly values",
              text: c.series.map((s) => `${s.name}: ${s.points.slice(-12).map((p) => `${p[0]} ${fmt(p[1], c.measure)}`).join("; ")}`).join("\n") }] })} /></div>
          {c.series.length ? <EChart option={() => compareOption(c, ids)} height={400} label="Countries compared" /> : <p className="muted">No weeks loaded for these countries.</p>}
          {missing.length > 0 && <p className="caption">No {c.measure?.label.toLowerCase() ?? "data"} for {missing.map((i) => KEY_NAMES[i] ?? i).join(", ")}.
            Countries measure differently (lab tests, hospital admissions, GP visits), so some measures exist for only one or two.</p>}
        </div>
      )}
    </>
  );
}

function LongTab() {
  const [indicator, setIndicator] = useState("measles_cases");
  const [ids, setIds] = useState<string[]>(KEY);
  const [log, setLog] = useState(true);
  const [l, setL] = useState<Long | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [more, setMore] = useState("");
  useEffect(() => {
    let live = true;
    setL(null);
    diseaseApi.long(indicator, ids).then((x) => live && setL(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [indicator, ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const choices = useMemo(() => l?.choices ?? [], [l]);
  return (
    <>
      <div className="chips-row small">
        <label>Disease <select value={indicator} onChange={(e) => setIndicator(e.target.value)}>
          {(choices.length ? choices : [{ id: indicator, label: indicator }]).map((y) => <option key={y.id} value={y.id}>{y.label}</option>)}
        </select></label>
        <label><input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} /> Log scale</label>
        {ids.map((i) => <span key={i} className="chip"><Flag id={i} />{KEY_NAMES[i] ?? i}
          {ids.length > 1 && <button aria-label={`Remove ${i}`} onClick={() => setIds(ids.filter((x) => x !== i))}>×</button>}</span>)}
        <CountryChoice value={more} onChange={(x) => { setMore(""); if (x && !ids.includes(x)) setIds([...ids, x]); }} label="Add a country" />
      </div>
      {err && <p className="error">{err}</p>}
      {!l && !err && <p className="muted">Loading…</p>}
      {l && (
        <div className="card">
          <div className="card-head"><h3>{l.indicator.label}{l.unit ? `, ${l.unit}` : ""}</h3>
            <CardAsk onAsk={() => openAsk({ title: `${l.indicator.label} over the years`, parts: [{ key: "data", kind: "data", label: "Yearly",
              text: l.series.map((s) => `${s.name}: ${s.points.map((p) => `${p[0]} ${Math.round(p[1] * 10) / 10}`).join("; ")}`).join("\n") }] })} /></div>
          {l.series.length ? <EChart option={() => longOption(l, ids, log)} height={400} label="Yearly cases" /> : <p className="muted">No yearly figures loaded.</p>}
          <p className="caption">{l.indicator.sources}. Counts are cases reported, so a jump can also mean better reporting.</p>
        </div>
      )}
    </>
  );
}

function NotifiableCard() {
  const [d, setD] = useState<Notifiable | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [all, setAll] = useState(false);
  useEffect(() => { diseaseApi.notifiable().then(setD).catch(() => setD(null)); }, []);
  if (!d || !d.diseases.length) return null;
  const sel = d.diseases.find((x) => x.key === pick) ?? d.diseases[0];
  const list = d.diseases.filter((x) => !filter || x.name.toLowerCase().includes(filter.toLowerCase()));
  const shown = all || filter ? list : list.slice(0, 20);
  const nz = entityColors(["NZL"])[0] ?? "var(--accent)";
  return (
    <div className="card">
      <div className="card-head"><h3>New Zealand&apos;s notifiable diseases, {d.year}</h3>
        <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter diseases" aria-label="Filter diseases" />
        <CardAsk onAsk={() => openAsk({ title: `New Zealand notifiable diseases ${d.year}`, entity: "NZL", parts: [{ key: "data", kind: "data", label: "Cases by disease",
          text: d.diseases.map((x) => `${x.name}: ${x.latest} cases in ${x.year} (usual ${x.usual !== null ? Math.round(x.usual) : "–"})`).join("\n") }] })} /></div>
      <div className="cards-2">
        <div style={{ overflowX: "auto" }}>
          <table className="small">
            <thead><tr><th>Disease</th><th style={{ textAlign: "right" }}>Cases</th><th style={{ textAlign: "right" }}>Per 100,000</th>
              <th style={{ textAlign: "right" }}>Against 5 years before</th><th /></tr></thead>
            <tbody>{shown.map((x) => (
              <tr key={x.key} style={{ fontWeight: x.key === sel.key ? 700 : undefined }}>
                <td><button className="link" onClick={() => setPick(x.key)}>{x.name}</button></td>
                <td style={{ textAlign: "right" }}>{Math.round(x.latest).toLocaleString()}</td>
                <td style={{ textAlign: "right" }} className="muted">{x.latest_rate !== null ? x.latest_rate.toFixed(1) : "–"}</td>
                <td style={{ textAlign: "right", color: x.ratio !== null && x.ratio >= 1.5 ? "var(--bad)" : x.ratio !== null && x.ratio <= 0.67 ? "var(--good)" : undefined }}>
                  {x.ratio !== null ? `${Math.round(x.ratio * 100)}%` : "–"}</td>
                <td><svg width="80" height="18" aria-hidden><path d={sparkPoints(x.cases.map((p) => [String(p[0]), p[1]]), 80, 18)} fill="none" stroke={nz} strokeWidth="1.2" /></svg></td>
              </tr>
            ))}</tbody>
          </table>
          {!filter && list.length > 20 && <button className="link small" onClick={() => setAll(!all)}>{all ? "Show the top 20" : `Show all ${list.length}`}</button>}
        </div>
        <div>
          <h4 style={{ margin: "0 0 4px" }}>{sel.name}: cases a year</h4>
          <EChart option={() => notifiableOption(sel.name, sel.cases, nz)} height={300} label={`${sel.name} cases in New Zealand`} />
        </div>
      </div>
      <p className="caption">Cases notified to public health services in the year, from PHF Science&apos;s Notifiable Diseases Intelligence Dashboard
        (EpiSurv). &quot;Against 5 years before&quot; compares with the average of the five years before, leaving out 2020 and 2021.
        PHF Science leaves out rates worked out from very few cases.</p>
    </div>
  );
}

function CausesTab({ country, onCountry }: { country: string; onCountry: (c: string) => void }) {
  const [ids, setIds] = useState<string[]>(KEY.includes(country) ? KEY : [...KEY, country]);
  const [c, setC] = useState<Causes | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cause, setCause] = useState("");
  const [more, setMore] = useState("");
  useEffect(() => {
    let live = true;
    diseaseApi.causes(ids).then((x) => live && setC(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  if (err) return <p className="error">{err}</p>;
  if (!c) return <p className="muted">Loading…</p>;
  if (!c.causes.length) return <p className="muted">No causes of death loaded yet; they come with <code>.\refresh.bat</code> (Our World in Data charts).</p>;
  const pickCause = cause || c.causes[0].id;
  const one = c.series.find((s) => s.entity === country);
  const latest = one ? c.causes.map((k) => ({ k, p: one.causes[k.id]?.[one.causes[k.id].length - 1] })).filter((x) => x.p) : [];
  return (
    <>
      <div className="chips-row small">
        {ids.map((k) => <button key={k} className={`chip${k === country ? " on" : ""}`} aria-pressed={k === country} onClick={() => onCountry(k)}><Flag id={k} />{KEY_NAMES[k] ?? c.series.find((s) => s.entity === k)?.name ?? k}</button>)}
        <CountryChoice value={more} onChange={(x) => { setMore(""); if (x && !ids.includes(x)) setIds([...ids, x].slice(-8)); onCountry(x); }} label="Another country" />
      </div>
      <div className="card">
        <div className="card-head"><h3>{one?.name ?? country}: deaths per 100,000 by cause</h3>
          <CardAsk onAsk={() => openAsk({ title: `Causes of death: ${one?.name ?? country}`, entity: country, parts: [{ key: "data", kind: "data", label: "Latest year",
            text: latest.map((x) => `${x.k.name}: ${x.p![1].toFixed(1)} per 100,000 (${x.p![0]})`).join("\n") }] })} /></div>
        {one && Object.keys(one.causes).length
          ? <EChart option={() => causesOption(c, "country", country, ids)} height={400} label="Deaths by cause" />
          : <p className="muted">The WHO Mortality Database has no figures for this country.</p>}
        {latest.length > 0 && <p className="caption">Latest year {Math.max(...latest.map((x) => x.p![0]))}. {c.source}.</p>}
      </div>
      <div className="card">
        <div className="card-head"><h3>One cause across countries</h3>
          <select value={pickCause} onChange={(e) => setCause(e.target.value)} aria-label="Cause">{c.causes.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}</select></div>
        <EChart option={() => causesOption(c, "cause", pickCause, ids)} height={360} label="One cause across countries" />
        <p className="caption">Countries report causes from death certificates a year or more late, and New Zealand&apos;s figures in the WHO database stop
          in 2018. Changes to how causes are coded (ICD revisions) can make small steps in a line.</p>
      </div>
    </>
  );
}

function OutbreaksTab() {
  const [items, setItems] = useState<Outbreak[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [keyOnly, setKeyOnly] = useState(false);
  const [disease, setDisease] = useState("");
  useEffect(() => {
    let live = true;
    diseaseApi.outbreaks(keyOnly ? KEY : undefined, 300).then((x) => live && setItems(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [keyOnly]);
  if (err) return <p className="error">{err}</p>;
  if (!items) return <p className="muted">Loading…</p>;
  const kinds = [...new Set(items.map((i) => i.disease))].sort();
  const shown = items.filter((i) => !disease || i.disease === disease);
  return (
    <div className="card">
      <div className="chips-row small">
        <label><input type="checkbox" checked={keyOnly} onChange={(e) => setKeyOnly(e.target.checked)} /> Only New Zealand, Australia, UK and US</label>
        <label>Disease <select value={disease} onChange={(e) => setDisease(e.target.value)}>
          <option value="">All</option>{kinds.map((k) => <option key={k} value={k}>{k.replace(/_/g, " ")}</option>)}
        </select></label>
      </div>
      {shown.length ? (
        <table className="small"><tbody>{shown.map((o, i) => (
          <tr key={`${o.entity}-${o.day}-${i}`}>
            <td style={{ whiteSpace: "nowrap" }}>{o.day}</td>
            <td style={{ whiteSpace: "nowrap" }}><Link href={`/entity/${o.entity}#disease`}><Flag id={o.entity} />{o.name}</Link></td>
            <td>{o.url ? <a href={o.url} target="_blank" rel="noreferrer">{o.title}</a> : o.title}</td>
          </tr>
        ))}</tbody></table>
      ) : <p className="muted">No outbreak reports loaded yet.</p>}
      <p className="caption">Outbreak reports are kept as events but carry no death counts, so they stay off country charts&apos; event bands and don&apos;t crowd them.</p>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><DiseaseView /></Suspense>;
}
