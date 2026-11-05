"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import { api, type BuiltFilter, type EventLink, type RelationDetail, type RelationLabel, type RelationList, type RelationPair, type RelationScan } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { eventPathOption, lagOption, relationScatterOption } from "@/lib/charts";

// Which figures move together, which tends to come first, and which links hold after
// allowing for income and time; plus how figures changed after events. Never cause and effect.
const LABEL_TEXT: Record<RelationLabel, string> = {
  together: "Move together", first: "One comes first", holds: "Holds after income and time",
};
const KIND_TEXT: Record<string, string> = {
  recession: "Recession", boom: "Boom", inflation: "Inflation spike", debt: "Debt surge", crisis: "Financial crisis",
  coup: "Coup", conflict: "War or conflict", election: "Election", leader: "New leader", law: "Law change",
  sanction: "Sanctions", disaster: "Disaster", epidemic: "Epidemic",
};
const PAGE = 100;

function Chips({ labels, builtFrom }: { labels: RelationLabel[]; builtFrom?: string | null }) {
  return (
    <span className="rel-chips">
      {builtFrom && <span className="rel-chip rel-built" title={`One figure is made from the other (${builtFrom}), so they move together by arithmetic`}>Built from each other</span>}
      {labels.map((l) => <span key={l} className={`rel-chip rel-${l}`}>{LABEL_TEXT[l]}</span>)}
    </span>
  );
}

function firstText(p: RelationPair): string {
  if (!p.first) return "";
  const lag = p.best_lag ? `${p.best_lag} yr` : "";
  if (p.first === "both") return `Both ways${lag ? `, ${lag}` : ""}`;
  return `${p.first === "x" ? "Left" : "Right"} first${lag ? `, ${lag}` : ""}`;
}

function RelationshipsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<"pairs" | "events">(params.get("tab") === "events" ? "events" : "pairs");
  const [label, setLabel] = useState(params.get("label") ?? "");
  const [domain, setDomain] = useState(params.get("domain") ?? "");
  const [group, setGroup] = useState(params.get("group") ?? "");
  const [indicator] = useState(params.get("indicator") ?? "");
  const [q, setQ] = useState("");
  const [first, setFirst] = useState(false);
  const [drivers, setDrivers] = useState(false);
  const [showSame, setShowSame] = useState(false);
  const [hideSource, setHideSource] = useState(false);
  const [built, setBuilt] = useState<BuiltFilter>("last");
  const [limit, setLimit] = useState(PAGE);
  const [list, setList] = useState<RelationList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<{ x: string; y: string } | null>(params.get("x") && params.get("y") ? { x: params.get("x")!, y: params.get("y")! } : null);

  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api.relationships({ label: label || undefined, domain: domain || undefined, group: group || undefined, q: q || undefined,
        indicator: indicator || undefined, first, drivers, hide_same: !showSame, hide_same_source: hideSource, built, limit })
        .then((r) => { if (live) { setList(r); setError(null); } }).catch((e) => live && setError(String(e.message || e)));
    }, q ? 250 : 0);
    return () => { live = false; clearTimeout(t); };
  }, [label, domain, group, q, indicator, first, drivers, showSame, hideSource, built, limit]);

  const open = (p: { x: string; y: string } | null) => {
    setPick(p);
    const u = new URLSearchParams(params.toString());
    if (p) { u.set("x", p.x); u.set("y", p.y); } else { u.delete("x"); u.delete("y"); }
    router.replace(`/relationships?${u}`, { scroll: false });
  };
  const switchTab = (t: "pairs" | "events") => {
    setTab(t);
    router.replace(`/relationships?${t === "events" ? "tab=events" : ""}`, { scroll: false });
  };

  if (error) return <p className="error">{error}</p>;
  if (!list) return <p className="muted">Loading…</p>;
  const scan = list.scan;
  return (
    <div className="grid">
      <div className="title-row"><h1>Relationships</h1> <Help note="relationships" /></div>
      {!scan ? (
        <div className="card">
          <p>No scan yet. It runs after each refresh (<code>.\refresh.bat</code>), and once after <code>.\update.bat</code>.
            It takes a few minutes; the switches are in <Link href="/settings#relationships">Settings</Link>.</p>
        </div>
      ) : (
        <>
          <ScanLine scan={scan} />
          <div className="seg" role="tablist">
            <button role="tab" aria-selected={tab === "pairs"} className={tab === "pairs" ? "on" : ""} onClick={() => switchTab("pairs")}>Pairs of figures</button>
            <button role="tab" aria-selected={tab === "events"} className={tab === "events" ? "on" : ""} onClick={() => switchTab("events")}>Before and after events</button>
          </div>
          {tab === "pairs" ? (
            <>
              <div className="chips-row small">
                <label>Evidence <select value={label} onChange={(e) => { setLabel(e.target.value); setLimit(PAGE); }}>
                  <option value="">Any</option>
                  {(Object.keys(LABEL_TEXT) as RelationLabel[]).map((l) => <option key={l} value={l}>{scan.labels[l]} ({scan.label_counts[l]})</option>)}
                </select></label>
                <label>Topic <select value={domain} onChange={(e) => { setDomain(e.target.value); setLimit(PAGE); }}>
                  <option value="">All</option>
                  {scan.domains.map((d) => <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>)}
                </select></label>
                <label>Countries <select value={group} onChange={(e) => { setGroup(e.target.value); setLimit(PAGE); }}>
                  <option value="">All</option>
                  {Object.entries(scan.groups).map(([g, n]) => <option key={g} value={g}>{n}</option>)}
                </select></label>
                <label title="Pairs where one figure is made from the other: a total and the same per person, a figure and its growth, the same thing in other units, a ratio and its parts">
                  Built from each other <select value={built} onChange={(e) => { setBuilt(e.target.value as BuiltFilter); setLimit(PAGE); }}>
                    <option value="last">Listed last</option>
                    <option value="hide">Hidden</option>
                    <option value="only">Only these</option>
                    <option value="mixed">Mixed in</option>
                  </select></label>
                <input type="search" placeholder="Find a figure" value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} aria-label="Find a figure" />
              </div>
              <div className="chips-row small">
                <label><input type="checkbox" checked={first} onChange={(e) => setFirst(e.target.checked)} /> One comes first</label>
                <label><input type="checkbox" checked={drivers} onChange={(e) => setDrivers(e.target.checked)} /> In the forecast model&apos;s driver list</label>
                <label><input type="checkbox" checked={hideSource} onChange={(e) => setHideSource(e.target.checked)} /> Hide pairs from the same source and topic</label>
                <label><input type="checkbox" checked={showSame} onChange={(e) => setShowSame(e.target.checked)} /> Show nearly-the-same figures</label>
              </div>
              {indicator && <p className="small">Pairs with <b>{indicator}</b> only. <Link href="/relationships">Show all</Link></p>}
              {pick && <PairDetail x={pick.x} y={pick.y} close={() => open(null)} />}
              <div className="card">
                <h3>{list.total.toLocaleString()} pair{list.total === 1 ? "" : "s"}{group ? ` where the link also shows among ${scan.groups[group]} countries` : ""}</h3>
                <div style={{ overflowX: "auto" }}>
                  <table className="small rel-table">
                    <thead><tr><th>Left figure</th><th>Right figure</th><th>Evidence</th>
                      <th className="num" title="Correlation of yearly changes, each country's own average change taken out">Together</th>
                      <th>Which first</th><th className="num">Countries</th><th>Years</th></tr></thead>
                    <tbody>
                      {list.rows.map((p) => (
                        <tr key={`${p.x}:${p.y}`} className={pick && pick.x === p.x && pick.y === p.y ? "selected" : ""}
                          onClick={() => open({ x: p.x, y: p.y })} style={{ cursor: "pointer" }}>
                          <td>{p.x_name}{p.in_drivers && <span title="In the forecast model's driver list"> ◆</span>}</td>
                          <td>{p.y_name}{p.saved_driver && <span title="Kept as a what-if driver"> ★</span>}</td>
                          <td><Chips labels={p.labels} builtFrom={p.built_from} /></td>
                          <td className="num">{(group ? p.groups[group]?.[0] ?? p.r : p.r).toFixed(2)}</td>
                          <td>{firstText(p)}</td>
                          <td className="num">{group ? p.groups[group]?.[1] : p.n_countries}</td>
                          <td>{p.year_from}–{p.year_to}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {list.total > list.rows.length && <button className="link small" onClick={() => setLimit(limit + PAGE)}>Show {Math.min(PAGE, list.total - list.rows.length)} more</button>}
                <p className="caption">Click a pair for its charts. ◆ marks pairs the forecast model already links; ★ pairs you kept as what-if drivers.
                  {group ? " With a country group chosen, the correlation and countries are for that group alone (not corrected for the number of pairs)." : ""}</p>
              </div>
            </>
          ) : <EventsView scan={scan} />}
        </>
      )}
    </div>
  );
}

function ScanLine({ scan }: { scan: RelationScan }) {
  const when = new Date(scan.finished_at).toLocaleString();
  return (
    <p className="small ink-2" style={{ margin: 0 }}>
      Last scan {when}: {scan.indicators} indicators, {scan.pairs_tested.toLocaleString()} pairs tested
      ({scan.pairs_thin.toLocaleString()} had too little data in common), {scan.pairs_kept.toLocaleString()} worth a look;
      {" "}{scan.events_kept} links to events. At most {Math.round(+scan.settings.relations_fdr * 100)}% of what is shown should be chance.
      {scan.partial && <b> The scan reached its time limit, so not every pair was tested (Settings: Relationship scan).</b>}
      {scan.stale && " The data has been refreshed since; the next refresh scans it again."}
    </p>
  );
}

function PairDetail({ x, y, close }: { x: string; y: string; close: () => void }) {
  const [d, setD] = useState<RelationDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [country, setCountry] = useState("NZL");
  const [saved, setSaved] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setD(null); setSaved(null);
    api.relationPair(x, y).then((r) => { if (live) { setD(r); setErr(null); } }).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [x, y]);
  const p = d?.pair;
  const countries = useMemo(() => d ? [...new Set(d.points.map((pt) => pt[0]))].sort((a, b) => (d.names[a] ?? a).localeCompare(d.names[b] ?? b)) : [], [d]);
  const scatter = useCallback(() => relationScatterOption(d?.points ?? [], d?.names ?? {},
    { xName: p?.x_name ?? x, yName: p?.y_name ?? y, xUnit: p?.x_unit ?? "", yUnit: p?.y_unit ?? "", highlight: country }), [d, p, x, y, country]);
  const lags = useCallback(() => lagOption(p?.lags ?? [], p?.x_name ?? x, p?.y_name ?? y), [p, x, y]);
  if (err) return <div className="card"><p className="error">{err}</p></div>;
  if (!d || !p) return <div className="card"><p className="muted">Loading…</p></div>;
  const addDriver = (driver: string, target: string) =>
    api.addDriver(driver, target).then((r) => setSaved(r.target)).catch((e) => setSaved(`!${String(e.message || e)}`));
  const leader = p.first === "x" ? p.x_name : p.first === "y" ? p.y_name : null;
  const follower = p.first === "x" ? p.y_name : p.first === "y" ? p.x_name : null;
  const byCountry = p.first === "x" ? p.countries_x_first : p.first === "y" ? p.countries_y_first : null;
  const title = `${p.x_name} and ${p.y_name}`;
  const askText = [`Pair: ${p.x_name} (${p.x_unit}) and ${p.y_name} (${p.y_unit})`, `Evidence: ${p.labels.map((l) => LABEL_TEXT[l]).join(", ") || "none"}`,
    `Correlation of yearly changes: ${p.r.toFixed(2)} (with year effects out: ${p.r_two_way.toFixed(2)}), ${p.n_countries} countries, ${p.year_from}-${p.year_to}`,
    p.beta !== null ? `After income and time: standardised size ${p.beta.toFixed(2)}; ${p.y_name} changes ${p.slope} per unit of ${p.x_name}` : "",
    p.first ? `Which first: ${firstText(p)}` : "", `Lag correlations (-5..5, positive = ${p.x_name} first): ${p.lags.map((v) => v === null ? "–" : v.toFixed(2)).join(", ")}`,
    `Note: ${p.note}`].filter(Boolean).join("\n");
  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}</h3>
        <CardAsk onAsk={() => openAsk({ title, parts: [{ key: "data", kind: "data", label: "What the scan found", text: askText }] })} />
        <button className="link small" onClick={close}>Close</button>
      </div>
      <Chips labels={p.labels} builtFrom={p.built_from} />
      {p.built_from && <p className="small muted">These two are built from each other ({p.built_from}), so they move together by arithmetic.
        Useful to know, but not a link between two separately measured things.</p>}
      <ul className="small rel-facts">
        <li>Yearly changes go together with a correlation of <b>{p.r.toFixed(2)}</b> over {p.n_countries} countries, {p.year_from}–{p.year_to}
          {" "}({p.r_two_way.toFixed(2)} once world-wide swings in each year are taken out).</li>
        {p.beta !== null && <li>After allowing for growth of GDP per person{p.control_used ? "" : " (left out: one of the pair is growth itself)"}, the year and each country&apos;s own trend:
          {" "}<b>{Number(p.slope).toPrecision(3)}</b> {p.y_unit} in {p.y_name} for each 1 {p.x_unit.replace(/^change in /, "")} in {p.x_name}, same year
          {p.labels.includes("holds") ? "." : " (not clear enough to count)."}</li>}
        {leader && <li><b>{leader}</b> tends to move first{p.best_lag ? `, by about ${p.best_lag} year${p.best_lag > 1 ? "s" : ""}` : ""}: its past changes help predict {follower}&apos;s beyond {follower}&apos;s own past
          {byCountry !== null && p.countries_tested ? ` (in ${byCountry} of ${p.countries_tested} countries tested one by one; chance alone would give about ${Math.round(p.countries_tested / 10)})` : ""}.</li>}
        {p.first === "both" && <li>Each one&apos;s past helps predict the other: they feed into each other, or something else drives both.</li>}
        {p.in_drivers && <li>The forecast model already links these two.</li>}
        <li className="muted">{p.note}</li>
      </ul>
      <div className="rel-charts">
        <div>
          <div className="chips-row small">
            <span>Each dot is one country in one year.</span>
            <label>Show <select value={country} onChange={(e) => setCountry(e.target.value)}>
              {countries.map((c) => <option key={c} value={c}>{d.names[c] ?? c}</option>)}
            </select></label>
          </div>
          <EChart option={scatter} height={300} label={`${title}: yearly changes`} />
        </div>
        <div>
          <p className="small" style={{ margin: "4px 0" }}>Which comes first: correlation of the changes with {p.x_name} shifted by each
            number of years. Bars to the right: {p.x_name} moves first; to the left: {p.y_name} moves first.</p>
          <EChart option={lags} height={300} label={`${title}: lag chart`} />
        </div>
      </div>
      {Object.keys(p.groups).length > 0 && (
        <details>
          <summary className="small">By country group</summary>
          <table className="small">
            <thead><tr><th>Group</th><th className="num">Correlation</th><th className="num">Countries</th></tr></thead>
            <tbody>{Object.entries(p.groups).map(([g, [r, n]]) => <tr key={g}><td>{g.replace(/^income-/, "income: ").replace(/-/g, " ")}</td><td className="num">{r.toFixed(2)}</td><td className="num">{n}</td></tr>)}</tbody>
          </table>
        </details>
      )}
      <div className="chips-row small">
        <Link href={`/indicator/${p.x}`}>{p.x_name} →</Link>
        <Link href={`/indicator/${p.y}`}>{p.y_name} →</Link>
        {p.labels.includes("holds") && <>
          <button onClick={() => addDriver(p.x, p.y)}>Use {p.x_name} as a what-if driver of {p.y_name}</button>
          {p.first === "y" || p.first === "both" ? <button onClick={() => addDriver(p.y, p.x)}>…or the other way round</button> : null}
        </>}
        {saved && (saved.startsWith("!") ? <span className="error">{saved.slice(1)}</span>
          : <span>Kept. <Link href={`/forecasts?tab=stat&ind=${saved}`}>Try it on Forecasts →</Link></span>)}
      </div>
    </div>
  );
}

function EventsView({ scan }: { scan: RelationScan }) {
  const [kind, setKind] = useState("");
  const [builtIn, setBuiltIn] = useState(false);
  const [diverging, setDiverging] = useState(false);
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<EventLink[] | null>(null);
  const [pick, setPick] = useState<EventLink | null>(null);
  useEffect(() => {
    let live = true;
    api.eventLinks({ kind: kind || undefined, built_in: builtIn, diverging }).then((r) => live && setRows(r.rows)).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [kind, builtIn, diverging]);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = (rows ?? []).filter((r) => words.every((w) => `${r.name} ${r.kind}`.toLowerCase().includes(w)));
  const chart = useCallback(() => pick ? eventPathOption(pick.h, pick.effect, pick.se, pick.unit, pick.name) : {}, [pick]);
  return (
    <>
      <div className="chips-row small">
        <label>Event <select value={kind} onChange={(e) => { setKind(e.target.value); setPick(null); }}>
          <option value="">Any</option>
          {scan.event_kinds.map((k) => <option key={k} value={k}>{KIND_TEXT[k] ?? k}</option>)}
        </select></label>
        <input type="search" placeholder="Find a figure" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find a figure" />
        <label><input type="checkbox" checked={builtIn} onChange={(e) => setBuiltIn(e.target.checked)} /> Include links that hold by definition</label>
        <label><input type="checkbox" checked={diverging} onChange={(e) => setDiverging(e.target.checked)} /> Include countries already moving apart before</label>
        <Help note="events_link" />
      </div>
      {pick && (
        <div className="card">
          <div className="card-head">
            <h3>{pick.name} around {(KIND_TEXT[pick.kind] ?? pick.kind).toLowerCase()}s</h3>
            <button className="link small" onClick={() => setPick(null)}>Close</button>
          </div>
          <EChart option={chart} height={280} label={`${pick.name} around ${pick.kind}`} />
          <p className="caption">Gap to countries of the same income group with no {(KIND_TEXT[pick.kind] ?? pick.kind).toLowerCase()} in those years, from the year before the event
            ({pick.n_events} events; the band is about 95% of where the true gap lies). A gap already open before the event means the countries were different beforehand.</p>
        </div>
      )}
      <div className="card">
        <h3>{rows === null ? "Loading…" : `${shown.length} link${shown.length === 1 ? "" : "s"} to events`}</h3>
        <div style={{ overflowX: "auto" }}>
          <table className="small">
            <thead><tr><th>Event</th><th>Figure</th><th className="num">Events</th><th className="num">3 years on, vs others</th><th className="num" title="Gap in level 3 years before the event, against the year before it">3 years before</th><th>Unit</th></tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={`${r.kind}:${r.indicator_id}`} onClick={() => setPick(r)} style={{ cursor: "pointer" }}
                  className={pick?.kind === r.kind && pick.indicator_id === r.indicator_id ? "selected" : ""}>
                  <td>{KIND_TEXT[r.kind] ?? r.kind}</td>
                  <td>{r.name}{r.built_in && <span className="muted" title="The event is worked out from this figure or one close to it"> (by definition)</span>}
                    {r.diverging_before && <span className="muted" title="The gap 3 years before is at least half the gap 3 years after: these countries were already moving apart"> (already apart before)</span>}</td>
                  <td className="num">{r.n_events}</td>
                  <td className="num"><b>{r.effect_3 > 0 ? "+" : ""}{r.effect_3.toFixed(1)}</b></td>
                  <td className="num" title="Gap 3 years before the event">{r.pre_trend === null ? "–" : `${r.pre_trend > 0 ? "+" : ""}${r.pre_trend.toFixed(1)}`}</td>
                  <td>{r.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="caption">Only links that pass the false discovery rate are listed. Click one for the year-by-year path.</p>
      </div>
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><RelationshipsPage /></Suspense>;
}
