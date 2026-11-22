"use client";

import { Fragment, useEffect, useState } from "react";
import CountryChoice from "@/components/CountryChoice";
import Flag from "@/components/Flag";
import { crowdApi, type Pundit, type PunditCall, type PunditsView, pct, wilson } from "@/lib/predictions";

// Pundits: named forecasters on Prediction Archive (pages saved by hand), how often their graded
// calls came true, their open calls on your key countries, and calls graded lately.

const OUTCOME: Record<string, [string, string]> = {
  correct: ["Came true", "good"], incorrect: ["Wrong", "bad"], indeterminate: ["Can't tell", "muted"], pending: ["Open", "muted"],
};

/** Strict colours: a hit rate is only good when even the low end of its range clears 60%. */
function tone(p: Pundit): string {
  const w = wilson(p.correct ?? 0, p.graded);
  if (!w || p.graded < 5) return "muted";
  if (w[0] >= 0.6) return "good";
  if (w[1] < 0.5) return "bad";
  return "";
}

export function OutcomeBadge({ c }: { c: PunditCall }) {
  if (!c.outcome) return <span className="pundit-badge muted" title="Seen in search results, which do not show grades">Not graded yet</span>;
  const [label, cls] = OUTCOME[c.outcome] ?? [c.outcome, "muted"];
  return <span className={`pundit-badge ${cls}`}>{c.outcome === "pending" && c.next_check ? `Open, next check ${c.next_check}` : label}</span>;
}

export function CallRow({ c, showWho = true }: { c: PunditCall; showWho?: boolean }) {
  const [open, setOpen] = useState(false);
  const more = c.verbatim || c.reasoning || c.source_url || c.horizon;
  return (
    <div className="pundit-call">
      <div>
        {c.countries.slice(0, 3).map((id) => <Flag key={id} id={id} />)}{" "}
        <a href={c.url} target="_blank" rel="noreferrer">{c.title}</a> <OutcomeBadge c={c} />
      </div>
      <div className="meta">
        {showWho && <>{c.predictor ?? "Unknown"}{c.accuracy != null && <> (hits {pct(c.accuracy)} of {(c.graded ?? 0).toLocaleString()} graded)</>} · </>}
        made {c.made ?? "?"}{c.evaluated && <> · graded {c.evaluated}</>}{c.horizon && <> · horizon: {c.horizon}</>}
        {more && <> · <button className="link small" onClick={() => setOpen(!open)}>{open ? "Less" : "More"}</button></>}
      </div>
      {open && (
        <div className="small pundit-more">
          {c.verbatim && <p><b>Their words:</b> &ldquo;{c.verbatim}&rdquo;</p>}
          {c.reasoning && <p><b>Why it was graded so</b>{c.checked_against ? ` (checked against ${c.checked_against} sources)` : ""}: {c.reasoning}</p>}
          {c.source_url && <p><b>Said in:</b> <a href={c.source_url} target="_blank" rel="noreferrer">{c.source_title || c.source_url}</a></p>}
        </div>
      )}
    </div>
  );
}

function HitBar({ p }: { p: Pundit }) {
  const w = wilson(p.correct ?? 0, p.graded);
  return (
    <div className="pundit-hit" title={w ? `95% range ${pct(w[0])} to ${pct(w[1])} from ${p.graded} graded calls` : ""}>
      <div className="meter"><div className={`fill ${tone(p)}`} style={{ width: `${(p.accuracy ?? 0) * 100}%` }} />
        <i style={{ left: "50%" }} /></div>
      <b>{pct(p.accuracy)}</b>
      {w && <span className="small muted">{pct(w[0])}–{pct(w[1])}</span>}
    </div>
  );
}

function PersonCalls({ id }: { id: string }) {
  const [d, setD] = useState<(Pundit & { calls: PunditCall[] }) | null>(null);
  const [only, setOnly] = useState("");
  useEffect(() => { crowdApi.pundit(id).then(setD).catch(() => setD(null)); }, [id]);
  if (!d) return <p className="muted small">Loading…</p>;
  const calls = d.calls.filter((c) => !only || (only === "pending" ? !c.outcome || c.outcome === "pending" : c.outcome === only));
  return (
    <div className="pundit-person">
      {d.about && <p className="small ink-2">{d.about}</p>}
      <div className="seg small">{[["", "All"], ["correct", "Came true"], ["incorrect", "Wrong"], ["indeterminate", "Can't tell"], ["pending", "Open"]].map(([k, l]) =>
        <button key={k} className={only === k ? "on" : ""} onClick={() => setOnly(k)}>{l}</button>)}</div>
      {!calls.length ? <p className="small muted">None among the {d.calls.length} calls saved here. Save more of their pages (the site lists 25 a page).</p>
        : <div className="pundit-calls">{calls.slice(0, 100).map((c) => <CallRow key={c.call_key} c={c} showWho={false} />)}</div>}
    </div>
  );
}

export default function PunditsTab({ country: start = "" }: { country?: string }) {
  const [d, setD] = useState<PunditsView | null>(null);
  const [q, setQ] = useState("");
  const [minGraded, setMinGraded] = useState(10);
  const [sort, setSort] = useState("accuracy");
  const [country, setCountry] = useState(start);
  const [person, setPerson] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => crowdApi.pundits({ q: q || undefined, min_graded: minGraded, sort, country: country || undefined })
      .then(setD).catch(() => setD(null)), 200);
    return () => clearTimeout(t);
  }, [q, minGraded, sort, country]);
  if (!d) return <p className="muted">Loading…</p>;
  if (!d.loaded) return <div className="card"><HowTo first /></div>;
  return (
    <>
      <p className="small muted">{d.n_people.toLocaleString()} forecasters and {d.n_calls.toLocaleString()} calls from the pages you saved
        {d.seen ? `, newest saved ${d.seen}` : ""}. Grades are Prediction Archive&apos;s own, made by an AI reader checking later news.</p>
      <div className="grid two">
        <div className="card">
          <div className="card-head"><h3>Open calls on {country ? <><Flag id={country} /> {country}</> : "your key countries"}</h3></div>
          <div className="chips-row small">
            {d.key_countries.map((id) => <button key={id} className={country === id ? "on" : ""} onClick={() => setCountry(country === id ? "" : id)}>
              <Flag id={id} /> {id}</button>)}
            <CountryChoice value={country} onChange={setCountry} />
            {country && <button onClick={() => setCountry("")}>All key countries</button>}
          </div>
          {!d.open.length ? <p className="small muted">No open calls naming {country || "your key countries"} in the pages saved. Save a search for the
            country&apos;s name on the site (<code>.\verify.bat prediction_archive</code> does this for your key countries).</p>
            : <div className="pundit-calls">{d.open.map((c) => <CallRow key={c.call_key} c={c} />)}</div>}
          <p className="caption">Calls whose title or words name the country (by names, people and places, as for crowd questions), next check first.
            Calls found only through search show &ldquo;Not graded yet&rdquo; because search results carry no grade.</p>
        </div>
        <div className="card">
          <div className="card-head"><h3>Graded lately</h3></div>
          {!d.graded.length ? <p className="small muted">No graded calls in the pages saved yet. Forecaster pages and prediction pages carry grades.</p>
            : <div className="pundit-calls">{d.graded.slice(0, 25).map((c) => <CallRow key={c.call_key} c={c} />)}</div>}
          <p className="caption">Calls on your countries first, then the newest grades.</p>
        </div>
      </div>
      <div className="card" style={{ overflowX: "auto" }}>
        <div className="card-head"><h3>Hit rates</h3></div>
        <div className="chips-row small">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a forecaster" aria-label="Find a forecaster" />
          <label>At least <select value={minGraded} onChange={(e) => setMinGraded(Number(e.target.value))} aria-label="Fewest graded calls">
            {[0, 5, 10, 30, 100].map((n) => <option key={n} value={n}>{n}</option>)}</select> graded calls</label>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
            <option value="accuracy">Best hit rate</option><option value="graded">Most graded</option><option value="rank">Site rank</option>
            <option value="pending">Most still open</option><option value="name">Name</option></select>
        </div>
        <table className="summary-table pundit-table">
          <thead><tr><th>Forecaster</th><th>Came true</th><th>Right</th><th>Wrong</th><th>Can&apos;t tell</th><th>Still open</th><th>Site rank</th></tr></thead>
          <tbody>{d.people.map((p) => (
            <Fragment key={p.predictor_id}>
              <tr>
                <td><button className="link" onClick={() => setPerson(person === p.predictor_id ? null : p.predictor_id)}>{p.name}</button>
                  {p.url && <> <a className="small muted" href={p.url} target="_blank" rel="noreferrer" title="Their page on Prediction Archive">site ↗</a></>}
                  {!p.from_site && <div className="small muted">counted from {p.calls_held} saved calls only</div>}</td>
                <td><HitBar p={p} /></td>
                <td>{(p.correct ?? 0).toLocaleString()}</td><td>{(p.incorrect ?? 0).toLocaleString()}</td>
                <td>{p.indeterminate?.toLocaleString() ?? "–"}</td><td>{p.pending?.toLocaleString() ?? "–"}</td><td>{p.site_rank ?? "–"}</td>
              </tr>
              {person === p.predictor_id && <tr><td colSpan={7}><PersonCalls id={p.predictor_id} /></td></tr>}
            </Fragment>
          ))}</tbody>
        </table>
        {d.hidden > 0 && <p className="small muted">{d.hidden.toLocaleString()} more with fewer than {d.min_graded} graded calls; lower the limit to see them.</p>}
        <p className="caption">Came true is right / (right + wrong); calls the grader couldn&apos;t settle are left out. The grey range is how sure that is
          given the number of calls graded (95%), and the tick marks 50%. Green only when even the low end clears 60%, red when even the high end
          is under 50%. The site&apos;s rank uses the same idea (Wilson score). Who counts as a forecaster is the site&apos;s choice: some are
          bodies or &ldquo;Officials&rdquo;.</p>
      </div>
      <div className="card"><HowTo /></div>
    </>
  );
}

function HowTo({ first = false }: { first?: boolean }) {
  return (
    <>
      {first ? <p>No Prediction Archive pages loaded yet.</p> : <h3>Adding more</h3>}
      <p className="small">Prediction Archive turns programs away, so its pages are saved by hand. In Edge, open a page and press Ctrl+S, keep the name it
        offers (it ends in &ldquo;_ PredictionArchive&rdquo;) and save into <code>var\manual\prediction_archive</code>, then run <code>.\load.bat prediction_archive</code>.
        Or run <code>.\verify.bat prediction_archive</code>, which opens the Top Predictors page and a search for each of your key countries and saves them for you.</p>
      <ul className="small">
        <li><a href="https://predictionarchive.com/top-predictors" target="_blank" rel="noreferrer">Top Predictors</a>: hit rates for the top 100.</li>
        <li>A forecaster&apos;s page: their counts and 25 calls. Click <b>Pending</b> before saving to get their open calls with next check dates.</li>
        <li>A prediction&apos;s page: the words used, the source and the grader&apos;s reasoning.</li>
        <li>A search, such as <a href="https://predictionarchive.com/search?q=New+Zealand&type=prediction" target="_blank" rel="noreferrer">New Zealand</a>: calls naming a country (without grades).</li>
      </ul>
      <p className="small muted">Every saved page is loaded together, so keep them all; a page saved again replaces the older copy&apos;s figures.</p>
    </>
  );
}
