"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import PredictDialog from "@/components/PredictDialog";
import { toast } from "@/lib/ai";
import { logHistory } from "@/lib/history";
import {
  type BaseRate, calibrationOption, callText, CATEGORY_TEXT, outcomeText, pct, pred, type Prediction, type Preset, type ScoreRow,
  type Watch, WHO_TEXT,
} from "@/lib/predictions";
import { useSettings } from "@/lib/settings";

// Predictions: your log of calls (yours, experts', the app's, the crowd's), checked and scored
// when they come due; the scorecard; how often things have happened before; and the watchlist.

type Tab = "log" | "scorecard" | "base" | "watchlist";
const TABS: [Tab, string][] = [["log", "Log"], ["scorecard", "Scorecard"], ["base", "Base rates"], ["watchlist", "Watchlist"]];
const INTRO: Record<Tab, string> = {
  log: "Every prediction you add: your own, an expert's, the app's forecasts and crowd sites'. When one comes due the app fills in the outcome where it can see it (an indicator's figure, a crowd question's resolution); otherwise you mark it.",
  scorecard: "Who has been right: hit rate, Brier score (0 is perfect, 0.25 is a coin toss) and typical miss for you, each expert, the app and each crowd site, and how well calibrated each is.",
  base: "Before guessing, how often has it happened before? Coups, recessions, wars, new leaders and crises per country-year, or your own rule on any indicator.",
  watchlist: "Lines to watch: an indicator crossing a level, a crowd question moving fast, an IMF forecast being revised. Alerts show on the Briefing.",
};

function PredictionsView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "log");
  const go = (t: Tab) => { setTab(t); router.replace(`/predictions?tab=${t}`, { scroll: false }); };
  useEffect(() => { logHistory({ kind: "page", title: "Predictions", url: "/predictions", detail: "page" }); }, []);
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Predictions</h1>
        <AskButton title={`Predictions: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => {
          const l = await pred.list();
          return [{ key: "description", kind: "description", label: "What this tab shows", text: INTRO[tab] },
            { key: "data", kind: "data", label: "Your predictions", text: l.items.slice(0, 60).map((p) =>
              `${p.question} | ${p.who} | ${callText(p)} | due ${p.due} | ${p.state}${p.outcome ? ` | outcome ${outcomeText(p)}` : ""}`).join("\n") }];
        }} />
        <span className="spacer" /><Link href="/crowd" className="small">Crowd forecasts</Link></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
      {tab === "log" && <LogTab />}
      {tab === "scorecard" && <ScoreTab />}
      {tab === "base" && <BaseTab />}
      {tab === "watchlist" && <WatchTab />}
    </div>
  );
}

// ----------------------------------------------------------------------------- log
function LogTab() {
  const [items, setItems] = useState<Prediction[] | null>(null);
  const [whoList, setWhoList] = useState<string[]>([]);
  const [who, setWho] = useState("");
  const [state, setState] = useState("");
  const [category, setCategory] = useState("");
  const [editing, setEditing] = useState<Partial<Prediction> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => pred.list({ who: who || undefined, state: state || undefined, category: category || undefined })
    .then((l) => { setItems(l.items); setWhoList(l.who); }).catch((e) => setError(String(e.message || e))), [who, state, category]);
  useEffect(() => { load(); }, [load]);
  const mark = (p: Prediction, actual: boolean | number | string | null) => pred.outcome(p.id, actual).then(load).catch((e) => toast(String(e.message || e)));
  const remove = (p: Prediction) => { if (window.confirm(`Delete "${p.question}"?`)) pred.remove(p.id).then(load); };
  if (error) return <p className="error">{error}</p>;
  return (
    <>
      <div className="chips-row small">
        <button onClick={() => setEditing({})}>Add a prediction</button>
        <select value={who} onChange={(e) => setWho(e.target.value)} aria-label="Whose"><option value="">Everyone</option>
          {whoList.map((w) => <option key={w} value={w}>{w}</option>)}</select>
        <select value={state} onChange={(e) => setState(e.target.value)} aria-label="State"><option value="">Any state</option>
          <option value="open">Open</option><option value="due">Due, waiting for the outcome</option><option value="settled">Settled</option></select>
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category"><option value="">Any category</option>
          {Object.entries(CATEGORY_TEXT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <span className="spacer" /><a href="/api/v1/predictions/export.csv" className="small">Download as CSV</a>
      </div>
      {!items ? <p className="muted">Loading…</p> : !items.length ? (
        <div className="card"><p>No predictions yet. Add one here, press <b>Predict</b> under any chart, <b>Add as a prediction</b> on a forecast,
          or follow a <Link href="/crowd">crowd question</Link> and add its chance.</p></div>
      ) : (
        <div className="card" style={{ overflowX: "auto" }}>
          <table className="summary-table">
            <thead><tr><th>Question</th><th>Who</th><th>Call</th><th>Made</th><th>Due</th><th>Outcome</th><th>Score</th><th /></tr></thead>
            <tbody>{items.map((p) => (
              <tr key={p.id} className={p.state === "due" ? "due" : undefined}>
                <td>{p.entity ? <Flag id={p.entity} /> : null} {p.link ? <a href={p.link} target="_blank" rel="noreferrer">{p.question}</a> : p.question}
                  {p.crowd_key && <> <Link className="small" href={`/crowd/question?key=${p.crowd_key}`}>question</Link></>}
                  {p.why && <div className="small muted">{p.why}</div>}</td>
                <td className="small">{p.who}{p.who_kind !== "you" && <div className="muted">{WHO_TEXT[p.who_kind]}</div>}</td>
                <td>{callText(p)}</td><td className="small">{p.made}</td>
                <td className="small">{p.due}{p.state === "due" && <div className="error">due</div>}</td>
                <td>{p.outcome ? <>{outcomeText(p)}<div className="small muted">{p.outcome.by === "auto" ? "filled in by the app" : "marked by you"}</div></> :
                  p.state === "due" ? <Outcome p={p} mark={mark} /> : <span className="muted">–</span>}</td>
                <td className="small">{p.score?.hit == null ? "" : p.score.hit ? "Right" : "Wrong"}
                  {p.score?.brier != null && <div className="muted">Brier {p.score.brier.toFixed(3)}</div>}
                  {p.score?.miss != null && <div className="muted">Missed by {Number(p.score.miss.toFixed(3))}{p.kind === "date" ? " days" : ""}</div>}</td>
                <td className="small"><span className="chips-row"><button className="link" onClick={() => setEditing(p)}>Edit</button>
                  {p.outcome && <button className="link" onClick={() => mark(p, null)}>Clear outcome</button>}
                  <button className="link" onClick={() => remove(p)}>Delete</button></span></td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      {editing && <PredictDialog initial={editing} title={editing.id ? "Edit the prediction" : "Add a prediction"} onClose={() => setEditing(null)} onSaved={load} />}
    </>
  );
}

function Outcome({ p, mark }: { p: Prediction; mark: (p: Prediction, a: boolean | number | string) => void }) {
  const [v, setV] = useState("");
  if (p.kind === "binary") return <span className="chips-row small"><button onClick={() => mark(p, true)}>Yes</button><button onClick={() => mark(p, false)}>No</button></span>;
  return (
    <span className="chips-row small">
      <input type={p.kind === "date" ? "date" : "number"} step="any" value={v} onChange={(e) => setV(e.target.value)} aria-label="What happened" style={{ width: 120 }} />
      <button disabled={!v} onClick={() => mark(p, p.kind === "date" ? v : Number(v))}>Save</button>
    </span>
  );
}

// ----------------------------------------------------------------------------- scorecard
function ScoreTab() {
  const [rows, setRows] = useState<ScoreRow[] | null>(null);
  const [days, setDays] = useState(7);
  const [category, setCategory] = useState("");
  const [entity, setEntity] = useState("");
  useEffect(() => { pred.scorecard({ category: category || undefined, entity: entity || undefined })
    .then((r) => { setRows(r.rows); setDays(r.score_days); }).catch(() => setRows([])); }, [category, entity]);
  const option = useCallback(() => calibrationOption((rows ?? []).filter((r) => r.calibration.length)), [rows]);
  if (!rows) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="chips-row small">
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category"><option value="">Every category</option>
          {Object.entries(CATEGORY_TEXT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <CountryChoice value={entity} onChange={setEntity} />
        {entity && <button onClick={() => setEntity("")}>All countries</button>}
      </div>
      {!rows.length ? <div className="card"><p>Nothing settled yet. Scores appear as your predictions come due and crowd questions resolve.</p></div> : (
        <>
          <div className="card" style={{ overflowX: "auto" }}>
            <table className="summary-table">
              <thead><tr><th>Forecaster</th><th>Calls</th><th>Settled</th><th>Right</th><th>Brier score</th><th>Typical miss (numbers)</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={`${r.kind}:${r.name}`}><td>{r.name} <span className="muted small">{WHO_TEXT[r.kind]}</span></td><td>{r.n}</td><td>{r.settled}</td>
                  <td>{r.hit_rate == null ? "–" : `${pct(r.hit_rate)} (${r.hits} of ${r.scored_hits})`}</td>
                  <td>{r.brier == null ? "–" : `${r.brier.toFixed(3)} (${r.brier_n})`}</td>
                  <td>{r.rel_miss == null ? "–" : `${pct(r.rel_miss)} of the outcome`}</td></tr>))}</tbody>
            </table>
            <p className="caption">Crowd sites are scored on their chance {days} days before each yes/no question closed (Settings &gt; Predictions), the last chance
              saved on or before then; so a site counts only on questions the app saw at least that long. Lower Brier is better; always saying 50% scores 0.25.</p>
          </div>
          <div className="card"><h3>Calibration</h3>
            <EChart option={option} height={340} label="Calibration" />
            <p className="caption">Each dot is the calls given about the same chance (in tenths): across, the chance given; up, how often it happened. On the dotted line is
              perfectly calibrated; below it, too sure of yes; above it, too sure of no. Dot size grows with the number of calls.</p></div>
        </>
      )}
      <p className="small ink-2">Published track records to compare with: <a href="https://www.metaculus.com/questions/track-record/" target="_blank" rel="noreferrer">Metaculus</a>,{" "}
        <a href="https://manifold.markets/calibration" target="_blank" rel="noreferrer">Manifold</a>,{" "}
        <a href="https://www.imf.org/en/Publications/WEO" target="_blank" rel="noreferrer">the IMF&apos;s own forecast evaluations</a>.</p>
    </>
  );
}

// ----------------------------------------------------------------------------- base rates
function BaseTab() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [kinds, setKinds] = useState<{ kind: string; label: string }[]>([]);
  const [q, setQ] = useState<Record<string, string | number | undefined>>({ preset: "coup", start: 1960 });
  const [r, setR] = useState<BaseRate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [own, setOwn] = useState<"preset" | "event" | "rule">("preset");
  useEffect(() => { pred.presets().then((p) => { setPresets(p.presets); setKinds(p.event_kinds); }).catch(() => undefined); }, []);
  useEffect(() => { setError(null); pred.baseRate(q).then(setR).catch((e) => { setR(null); setError(String(e.message || e)); }); }, [q]);
  const set = (k: string, v: string | number | undefined) => setQ((x) => ({ ...x, [k]: v === "" ? undefined : v }));
  const mode = (m: "preset" | "event" | "rule") => {
    setOwn(m);
    setQ(m === "preset" ? { preset: "coup", start: 1960 } : m === "event" ? { event: "coup", start: 1960, within: 1 }
      : { indicator: "inflation", if_op: "above", if_value: 5, then_op: "below", then_value: 3, within: 2, start: 1960 });
  };
  return (
    <>
      <div className="seg small">{(["preset", "event", "rule"] as const).map((m) => <button key={m} className={own === m ? "on" : ""} onClick={() => mode(m)}>
        {m === "preset" ? "Ready-made" : m === "event" ? "An event" : "A rule on an indicator"}</button>)}</div>
      <div className="card ratio-form">
        {own === "preset" && <label style={{ gridColumn: "1 / -1" }}>How often…<select value={String(q.preset)} onChange={(e) => set("preset", e.target.value)}>
          {presets.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}</select></label>}
        {own === "event" && <>
          <label>Event<select value={String(q.event)} onChange={(e) => set("event", e.target.value)}>
            {kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}</select></label>
          <label>Chance within (years)<input type="number" min={1} max={50} value={q.within ?? 1} onChange={(e) => set("within", Number(e.target.value))} /></label>
        </>}
        {own === "rule" && <>
          <label>Indicator<input value={String(q.indicator ?? "")} onChange={(e) => set("indicator", e.target.value)} /></label>
          <label>Once it is<span className="row"><select value={String(q.if_op)} onChange={(e) => set("if_op", e.target.value)}><option>above</option><option>below</option></select>
            <input type="number" step="any" value={q.if_value ?? ""} onChange={(e) => set("if_value", e.target.value === "" ? undefined : Number(e.target.value))} style={{ width: 90 }} /></span></label>
          <label>How often is it<span className="row"><select value={String(q.then_op)} onChange={(e) => set("then_op", e.target.value)}><option>above</option><option>below</option></select>
            <input type="number" step="any" value={q.then_value ?? ""} onChange={(e) => set("then_value", e.target.value === "" ? undefined : Number(e.target.value))} style={{ width: 90 }} /></span></label>
          <label>Within (years)<input type="number" min={1} max={50} value={q.within ?? 2} onChange={(e) => set("within", Number(e.target.value))} /></label>
        </>}
        <label>Since<input type="number" min={1800} max={2030} value={q.start ?? 1960} onChange={(e) => set("start", Number(e.target.value))} /></label>
        <label>Country (optional)<CountryChoice value={String(q.entity ?? "")} onChange={(c) => set("entity", c)} /></label>
        {q.entity && <div><button onClick={() => set("entity", undefined)}>All countries</button></div>}
      </div>
      {error && <p className="error">{error}</p>}
      {r && <BaseResult r={r} />}
    </>
  );
}

function BaseResult({ r }: { r: BaseRate }) {
  return (
    <div className="card">
      <div className="card-head"><h3>{r.title || (r.kind === "event" ? `${r.event} per country-year` : `${r.indicator}: ${r.if_op} ${r.if_value}, then ${r.then_op} ${r.then_value}`)}</h3>
        <AskButton title={`Base rate: ${r.title}`} parts={() => [{ key: "data", kind: "data", label: "Base rate", text: JSON.stringify({ ...r, examples: r.examples?.slice(0, 10) }) }]} /></div>
      {r.kind === "event" ? (
        <>
          <p className="big-number">{pct(r.rate, 2)} <span className="small muted">of country-years since {r.start}: {r.cases} cases in {r.country_years?.toLocaleString()} country-years
            ({r.countries} countries)</span></p>
          {(r.within ?? 1) > 1 && <p>About <b>{pct(r.chance_within, 1)}</b> within {r.within} years, if each year were like the average one.</p>}
          {r.by_decade && r.by_decade.length > 0 && <p className="small">By decade: {r.by_decade.map((d) => `${d.decade}s ${pct(d.rate, 2)}`).join(", ")}</p>}
          {r.top && r.top.length > 0 && <p className="small">Most often: {r.top.slice(0, 8).map((t) => `${t.entity_id} ${t.cases}`).join(", ")}</p>}
        </>
      ) : (
        <p className="big-number">{r.rate == null ? "No cases" : pct(r.rate)} <span className="small muted">{r.happened} of {r.cases} times since {r.start}
          (a spell counts from the first year it met the condition; spells too recent to have had {r.within} years are left out)</span></p>
      )}
      {r.examples && r.examples.length > 0 && (
        <details><summary className="small">Examples</summary>
          <ul className="small">{r.examples.map((e, i) => <li key={i}>{e.year} {e.entity_id}: {e.title ?? `${Number(e.value?.toFixed(2))}${e.then_year ? `, then ${Number(e.then_value?.toFixed(2))} in ${e.then_year}` : ", did not follow"}`}</li>)}</ul></details>
      )}
      <p className="caption">Counted from the events and figures the app holds; events depend on each source&apos;s coverage, so treat rare kinds as rough.</p>
    </div>
  );
}

// ----------------------------------------------------------------------------- watchlist
function WatchTab() {
  const s = useSettings();
  const [items, setItems] = useState<Watch[] | null>(null);
  const [w, setW] = useState<Partial<Watch>>({ kind: "indicator", op: "above" });
  const [error, setError] = useState<string | null>(null);
  const load = () => pred.watchlist().then((x) => setItems(x.items)).catch(() => setItems([]));
  useEffect(() => { load(); }, []);
  const add = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    pred.addWatch(w).then(() => { load(); setW({ kind: w.kind, op: "above" }); }).catch((err) => setError(String(err.message || err)));
  };
  return (
    <>
      {!s.watchlist_on && <p className="muted">Watchlist alerts are off in Settings &gt; Predictions: the list still works here but nothing shows on the Briefing.</p>}
      <form className="card ratio-form" onSubmit={add}>
        <label>Watch<select value={w.kind} onChange={(e) => setW({ kind: e.target.value as Watch["kind"], op: "above" })}>
          <option value="indicator">An indicator crossing a line</option><option value="crowd">A crowd question moving</option>
          <option value="forecast">An IMF forecast being revised</option></select></label>
        {w.kind !== "crowd" && <>
          <label>Indicator<input required value={w.indicator ?? ""} onChange={(e) => setW({ ...w, indicator: e.target.value })} placeholder="inflation" /></label>
          <label>Country<CountryChoice value={w.entity ?? ""} onChange={(c) => setW({ ...w, entity: c })} /></label>
        </>}
        {w.kind === "indicator" && <label>Alert when it goes<span className="row">
          <select value={w.op} onChange={(e) => setW({ ...w, op: e.target.value as "above" | "below" })}><option>above</option><option>below</option></select>
          <input type="number" step="any" required value={w.threshold ?? ""} onChange={(e) => setW({ ...w, threshold: Number(e.target.value) })} style={{ width: 90 }} /></span></label>}
        {w.kind === "forecast" && <label>Revised by at least<input type="number" step="any" value={w.threshold ?? 0.5} onChange={(e) => setW({ ...w, threshold: Number(e.target.value) })} /></label>}
        {w.kind === "crowd" && <>
          <label>Question (site:id)<input required value={w.question_key ?? ""} onChange={(e) => setW({ ...w, question_key: e.target.value })} placeholder="metaculus:12345" /></label>
          <label>Points in a week<input type="number" min={1} max={100} value={w.points ?? ""} placeholder={String(s.crowd_move_points)} onChange={(e) => setW({ ...w, points: e.target.value ? Number(e.target.value) : null })} /></label>
        </>}
        <label>Note<input value={w.note ?? ""} onChange={(e) => setW({ ...w, note: e.target.value })} /></label>
        <div className="row"><button type="submit">Add to the watchlist</button>{error && <span className="error small">{error}</span>}</div>
      </form>
      {!items ? <p className="muted">Loading…</p> : !items.length ? <p className="muted">Nothing watched yet. A crowd question&apos;s page also has <b>Watch</b>.</p> : (
        <div className="card">
          <table className="summary-table">
            <thead><tr><th>Watching</th><th>Now</th><th /></tr></thead>
            <tbody>{items.map((x) => (
              <tr key={x.id}><td>{x.alert && <b className="error">Alert </b>}
                {x.kind === "crowd" ? <Link href={`/crowd/question?key=${x.question_key}`}>{x.title ?? x.question_key}</Link>
                  : <Link href={`/indicator/${x.indicator}?entity=${x.entity}`}>{x.indicator} in {x.entity}</Link>}
                <span className="small muted"> {x.kind === "indicator" ? `${x.op} ${x.threshold}` : x.kind === "forecast" ? `IMF revision of ${x.threshold} or more` : ""}</span>
                {x.note && <div className="small muted">{x.note}</div>}</td>
                <td className="small">{x.text}</td>
                <td><button className="link small" onClick={() => pred.removeWatch(x.id).then(load)}>Remove</button></td></tr>))}</tbody>
          </table>
          <p className="caption">Checked against the newest figures each time this page or the Briefing opens. Crowd moves use the chances saved at each refresh.</p>
        </div>
      )}
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><PredictionsView /></Suspense>;
}
