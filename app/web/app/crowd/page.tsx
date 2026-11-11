"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import AskButton from "@/components/AskButton";
import CrowdRow from "@/components/CrowdRow";
import CountryChoice from "@/components/CountryChoice";
import Flag from "@/components/Flag";
import WorldMap from "@/components/WorldMap";
import { logHistory } from "@/lib/history";
import { CATEGORY_TEXT, type ConflictRow, crowdApi, type CrowdEvents, type CrowdList, type CrowdQ, pct } from "@/lib/predictions";
import { useSettings } from "@/lib/settings";

// Crowd forecasts: Polymarket, Metaculus and Manifold questions matched to countries and
// indicators, the biggest moves, how the crowd did on what happened, and ViEWS conflict forecasts.

type Tab = "questions" | "moves" | "events" | "conflict";
const TABS: [Tab, string][] = [["questions", "Questions"], ["moves", "Biggest moves"], ["events", "Events against predictions"], ["conflict", "Conflict forecasts"]];
const INTRO: Record<Tab, string> = {
  questions: "Questions from Polymarket (a betting market), Metaculus (a forecasting community) and Manifold (play-money markets) on politics, economics, geopolitics, climate and science, matched to the countries and indicators they are about. Sport, crypto and entertainment are left out.",
  moves: "Open yes/no questions whose chance moved most, from the chances the app saves at each refresh.",
  events: "Questions that have resolved: what the crowd said beforehand, when it first leaned the right way, and the surprises.",
  conflict: "ViEWS (Uppsala and the Peace Research Institute Oslo) forecasts deaths in state-based conflict for every country, month by month, for the next three years.",
};
const NOT_LOADED = <p>No crowd questions stored yet. They come with <code>.\refresh.bat</code>; Metaculus needs a free token
  (<code>METACULUS_TOKEN</code> in <code>.env</code>, see <Link href="/settings#keys">Settings &gt; Keys</Link>).</p>;

function CrowdView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "questions");
  const go = (t: Tab) => { setTab(t); router.replace(`/crowd?tab=${t}`, { scroll: false }); };
  useEffect(() => { logHistory({ kind: "page", title: "Crowd forecasts", url: "/crowd", detail: "page" }); }, []);
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Crowd forecasts</h1>
        <AskButton title={`Crowd forecasts: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => {
          const l = await crowdApi.list({ limit: 40 });
          return [{ key: "description", kind: "description", label: "What this page shows", text: INTRO[tab] },
            { key: "data", kind: "data", label: "Busiest open questions", text: l.items.map((q) => `${q.title} | ${q.site_name} | ${pct(q.chance)} | closes ${q.closes?.slice(0, 10) ?? "?"}`).join("\n") }];
        }} />
        <span className="spacer" /><Link href="/predictions" className="small">Your predictions</Link>
        <Link href="/settings#predictions" className="small muted">Settings</Link></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
      {tab === "questions" && <QuestionsTab country={params.get("country") ?? ""} />}
      {tab === "moves" && <MovesTab />}
      {tab === "events" && <EventsTab />}
      {tab === "conflict" && <ConflictTab />}
    </div>
  );
}

function QuestionsTab({ country: start }: { country: string }) {
  const [list, setList] = useState<CrowdList | null>(null);
  const [site, setSite] = useState("");
  const [category, setCategory] = useState("");
  const [country, setCountry] = useState(start);
  const [status, setStatus] = useState("open");
  const [sort, setSort] = useState("busy");
  const [q, setQ] = useState("");
  const [followed, setFollowed] = useState(false);
  const [limit, setLimit] = useState(50);
  useEffect(() => {
    const t = setTimeout(() => crowdApi.list({ site: site || undefined, category: category || undefined, country: country || undefined, status,
      sort, q: q || undefined, followed: followed ? "true" : undefined, limit }).then(setList).catch(() => setList(null)), 200);
    return () => clearTimeout(t);
  }, [site, category, country, status, sort, q, followed, limit]);
  if (list && !list.loaded) return <div className="card">{NOT_LOADED}</div>;
  return (
    <>
      <div className="chips-row small">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the questions" aria-label="Search" />
        <select value={site} onChange={(e) => setSite(e.target.value)} aria-label="Site"><option value="">Every site</option>
          {Object.entries(list?.sites ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category"><option value="">Every category</option>
          {Object.entries(list?.categories ?? {}).map(([c, label]) => <option key={c} value={c}>{label}</option>)}</select>
        <CountryChoice value={country} onChange={setCountry} />
        {country && <button onClick={() => setCountry("")}>All countries</button>}
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="open">Open</option>
          <option value="closed">Closed, not yet resolved</option><option value="resolved">Resolved</option><option value="">All</option></select>
        <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort"><option value="busy">Busiest</option>
          <option value="closing">Closing soonest</option><option value="newest">Newest</option><option value="moved">Moved most this week</option>
          <option value="resolved">Resolved lately</option></select>
        <label><input type="checkbox" checked={followed} onChange={(e) => setFollowed(e.target.checked)} /> Only followed</label>
      </div>
      {!list ? <p className="muted">Loading…</p> : (
        <>
          <p className="small muted">{list.total.toLocaleString()} questions · {list.counts.filter((c) => c.status === "open").map((c) => `${list.sites[c.site] ?? c.site} ${c.n} open`).join(", ")}</p>
          <div className="crowd-list">{list.items.map((x) => <CrowdRow key={x.question_key} q={x} />)}</div>
          {list.total > list.items.length && <button className="link" onClick={() => setLimit(limit + 50)}>Show more</button>}
          <p className="caption">Matched to countries by names, people and places in the title (for example &quot;Luxon&quot; is New Zealand, &quot;the Fed&quot; the US), so a few matches
            will be wrong; Hide a question on its page. Polymarket&apos;s chance is the market price; Metaculus&apos;s is the community forecast; Manifold&apos;s is play money.</p>
        </>
      )}
    </>
  );
}

function MovesTab() {
  const s = useSettings();
  const [days, setDays] = useState(7);
  const [moves, setMoves] = useState<CrowdQ[] | null>(null);
  useEffect(() => { crowdApi.moves({ days }).then(setMoves).catch(() => setMoves([])); }, [days]);
  return (
    <>
      <div className="seg small">{[1, 7, 30].map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d === 1 ? "A day" : `${d} days`}</button>)}</div>
      {!moves ? <p className="muted">Loading…</p> : !moves.length ? (
        <p className="muted">No open question moved {s.crowd_move_points} points or more in {days} days{days === 1 ? "" : ""}. Moves need two refreshes at least {days} days apart.</p>
      ) : <div className="crowd-list">{moves.map((q) => <CrowdRow key={q.question_key} q={q} />)}</div>}
      <p className="caption">At least {s.crowd_move_points} percentage points (Settings &gt; Predictions). The change column is over the last week whatever the span chosen.</p>
    </>
  );
}

function EventsTab() {
  const [e, setE] = useState<CrowdEvents | null>(null);
  useEffect(() => { crowdApi.events().then(setE).catch(() => setE(null)); }, []);
  if (!e) return <p className="muted">Loading…</p>;
  if (!e.n) return <div className="card"><p>No resolved questions with saved chances yet. They build up as the app saves chances at each refresh
    and questions resolve; followed questions also get each site&apos;s own history.</p></div>;
  const Sum = ({ title, rows }: { title: string; rows: CrowdEvents["by_site"] }) => (
    <div className="card"><h3>{title}</h3>
      <table className="summary-table"><thead><tr><th /><th>Questions</th><th>Brier</th><th>Surprises</th><th>Typical lead</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.key}><td>{CATEGORY_TEXT[r.key] ?? r.key}</td><td>{r.n}</td><td>{r.brier?.toFixed(3) ?? "–"}</td><td>{r.surprises}</td>
          <td>{r.median_lead == null ? "–" : `${r.median_lead} days`}</td></tr>)}</tbody></table></div>
  );
  return (
    <>
      <div className="grid two"><Sum title="By site" rows={e.by_site} /><Sum title="By category" rows={e.by_category} /></div>
      <div className="card" style={{ overflowX: "auto" }}>
        <table className="summary-table">
          <thead><tr><th>Question</th><th>Resolved</th><th>Chance {e.score_days} days before</th><th>First leaned right</th><th /></tr></thead>
          <tbody>{e.items.map((i) => (
            <tr key={i.question_key}><td><Link href={`/crowd/question?key=${encodeURIComponent(i.question_key)}`}>{i.title}</Link>
              <div className="small muted">{i.site_name} · {i.closed}</div></td>
              <td>{i.resolution}</td><td>{pct(i.chance)}</td>
              <td className="small">{i.first_right ? `${i.first_right}${i.lead_days != null ? ` (${i.lead_days} days ahead)` : ""}` : "–"}</td>
              <td>{i.surprise && <b className="error small">Surprise</b>}</td></tr>))}</tbody>
        </table>
        <p className="caption">A surprise is a yes the crowd gave under 20%, or a no it gave over 80%, {e.score_days} days before closing. Lead is how long before closing
          the chance first crossed 50% the right way (for questions that resolved yes).</p>
      </div>
    </>
  );
}

function ConflictTab() {
  const [rows, setRows] = useState<ConflictRow[] | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  useEffect(() => { crowdApi.conflict().then((r) => setRows(r.rows)).catch(() => setRows([])); }, []);
  if (!rows) return <p className="muted">Loading…</p>;
  if (!rows.length) return <div className="card"><p>No ViEWS forecasts stored yet. They come with <code>.\refresh.bat</code> about once a month
    (Settings &gt; Predictions, ViEWS conflict forecasts).</p></div>;
  const values = rows.map((r) => ({ entity_id: r.entity_id, value: Math.log10(1 + r.deaths), status: "F" }));
  return (
    <>
      <div className="card">
        <div className="card-head"><h3>Predicted deaths in state-based conflict, next 12 months</h3></div>
        <div className="map-box"><WorldMap values={values} unit="log10 deaths" decimals={1} diverging={false} onPick={(iso) => setPick(iso)} /></div>
        <p className="caption">Colour is on a log scale (1 = 10 deaths, 3 = 1,000). ViEWS run {rows[0]?.run}. Click a country to open its page.</p>
        {pick && <p><Link href={`/entity/${pick}#crowd`}>Open {pick}</Link></p>}
      </div>
      <div className="card">
        <table className="summary-table"><thead><tr><th>Country</th><th>Predicted deaths, 12 months</th><th>Highest monthly chance of 25 or more deaths</th></tr></thead>
          <tbody>{rows.slice(0, 40).map((r) => <tr key={r.entity_id}><td><Flag id={r.entity_id} /> <Link href={`/entity/${r.entity_id}#crowd`}>{r.entity_id}</Link></td>
            <td>{Math.round(r.deaths).toLocaleString()}</td><td>{pct(r.chance)}</td></tr>)}</tbody></table>
        <p className="caption">ViEWS forecasts are a model, not a crowd: they come from past fighting, politics and economics, and are best at saying where fighting
          continues rather than where it starts.</p>
      </div>
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><CrowdView /></Suspense>;
}
